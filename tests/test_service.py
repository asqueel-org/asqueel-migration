"""Input ownership, repeatable preparation and reviewed-plan execution."""

import copy
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from asqueel_migration import (
    JsonStructureProducer,
    PgDatabase,
    SqliteDatabase,
    SqlMigrator,
    StaleMigrationPlan,
    UnsupportedMigration,
    apply_migration,
    plan_migration,
)
from asqueel_migration.exceptions import MigrationExecutionError, SqlValidationError
from asqueel_migration.writers import SqliteWriter


def structure():
    return JsonStructureProducer({'db': 'demo', 'schemas': [{
        'name': 'alfa', 'tables': [{'name': 'items', 'pkey': 'id',
                                  'columns': [{'name': 'id', 'dtype': 'I'}]}],
    }]}).get_json_struct()


@pytest.mark.parametrize('serialized', [False, True])
def test_preparation_preserves_source_and_warnings(serialized):
    source = structure()
    source['root']['schemas']['alfa']['tables']['items']['attributes']['comment'] = 'Items'
    original = copy.deepcopy(source)
    db = SimpleNamespace(adapter=SimpleNamespace(capabilities=SqliteWriter.CAPABILITIES))
    migrator = SqlMigrator(db, structure=json.dumps(source) if serialized else source)
    warnings = []
    for _ in range(2):
        migrator.warnings = []
        migrator.extractOrm()
        migrator.applyCapabilities()
        warnings.append(list(migrator.warnings))
    assert source == original
    assert warnings[0] == warnings[1]
    assert any('comments' in warning for warning in warnings[0])


def test_assignment_takes_snapshot_and_replaces_cached_commands():
    source = structure()
    migrator = SqlMigrator(object())
    migrator.ormStructure = source
    source['root']['schemas'].clear()
    migrator.extractOrm()
    assert 'alfa' in migrator.ormStructure['root']['schemas']
    migrator.commands = {'db': {'command': 'stale'}}
    migrator.sql_commands = {'build_commands': 'stale'}
    migrator.ormStructure = structure()
    assert migrator.commands == migrator.sql_commands == {}


@pytest.mark.parametrize('value', [[], '[]', 42, None])
def test_legacy_assignment_rejects_non_objects(value):
    with pytest.raises(TypeError):
        SqlMigrator(object()).ormStructure = value


@pytest.mark.parametrize('serialized', [False, True])
def test_plan_apply_verify_and_stale_plan(tmp_path, serialized):
    db = SqliteDatabase({'dbname': str(tmp_path / 'db.sqlite')}, application_schemas=['alfa'])
    try:
        desired = structure()
        original = copy.deepcopy(desired)
        if serialized:
            desired = json.dumps(desired)
        plan = plan_migration(db, desired)
        assert 'CREATE TABLE' in plan['sql']
        with pytest.raises(StaleMigrationPlan):
            apply_migration(db, desired, expected_plan='wrong')
        assert plan_migration(db, desired)['plan_id'] == plan['plan_id']
        result = apply_migration(db, desired, expected_plan=plan['plan_id'])
        assert result['verified']
        assert result['remaining']['empty']
        assert (json.loads(desired) if serialized else desired) == original
        with pytest.raises(StaleMigrationPlan):
            apply_migration(db, desired, expected_plan=plan['plan_id'])
    finally:
        db.closeConnection()


@pytest.mark.parametrize('operation', [plan_migration, apply_migration])
@pytest.mark.parametrize('allow_removals', [False, True])
def test_missing_structure_rejected_before_database_access(operation, allow_removals):
    db = Mock()
    kwargs = {'expected_plan': 'reviewed'} if operation is apply_migration else {}
    with pytest.raises(SqlValidationError, match='structure'):
        operation(db, None, allow_removals=allow_removals, **kwargs)
    assert db.mock_calls == []


@pytest.mark.parametrize('operation', [plan_migration, apply_migration])
@pytest.mark.parametrize(('desired', 'error_type'), [
    ('{', json.JSONDecodeError),
    ('null', TypeError),
    ([], TypeError),
    ({'root': None}, SqlValidationError),
    ('{"root": {"schemas": []}}', SqlValidationError),
])
def test_invalid_service_inputs_fail_before_database_access(operation, desired, error_type):
    db = Mock()
    kwargs = {'expected_plan': 'reviewed'} if operation is apply_migration else {}
    with pytest.raises(error_type):
        operation(db, desired, **kwargs)
    assert db.mock_calls == []


@pytest.mark.postgresql
@pytest.mark.parametrize('legacy', [False, True])
def test_creation_uses_connection_destination(pg_server, legacy):
    import psycopg
    from psycopg import sql

    target = 'test_target_"' + uuid4().hex[:12]
    label = 'test_model_' + uuid4().hex[:12]
    db = PgDatabase(dict(pg_server, dbname=target), application_schemas=['alfa'])
    desired = structure()
    desired['root']['entity_name'] = label
    original = copy.deepcopy(desired)
    try:
        if legacy:
            migrator = SqlMigrator(db)
            migrator.ormStructure = desired
            planned_sql = migrator.getChanges()
        else:
            plan = plan_migration(db, desired)
            planned_sql = plan['sql']
        quoted_target = target.replace('"', '""')
        assert planned_sql.startswith(f'CREATE DATABASE "{quoted_target}"')
        if legacy:
            migrator.applyChanges()
        else:
            result = apply_migration(db, desired, expected_plan=plan['plan_id'])
            assert result['verified']
        assert plan_migration(db, desired)['empty']
        assert desired == original
        with psycopg.connect(**pg_server, dbname='postgres', autocommit=True) as conn:
            names = {row[0] for row in conn.execute(
                'SELECT datname FROM pg_database WHERE datname IN (%s, %s)', (target, label))}
            assert names == {target}
    finally:
        db.closeConnection()
        with psycopg.connect(**pg_server, dbname='postgres', autocommit=True) as conn:
            for name in (target, label):
                conn.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture
def existing_database(tmp_path):
    path = tmp_path / 'existing.db'
    sqlite3.connect(path).close()
    db = SqliteDatabase({'dbname': str(path)}, application_schemas=['alfa'])
    try:
        yield db
    finally:
        db.closeConnection()


def test_full_preparation_repeats_warnings_and_discards_old_sql(existing_database):
    db = existing_database
    desired = structure()
    desired['root']['schemas']['alfa']['tables']['items']['attributes']['comment'] = 'Items'
    original = copy.deepcopy(desired)
    migrator = SqlMigrator(db, structure=desired)
    first_sql = migrator.getChanges()
    first_warnings = list(migrator.warnings)
    assert first_sql and first_warnings
    migrator.prepareMigrationCommands()
    assert migrator.getChanges() == first_sql
    assert migrator.warnings == first_warnings

    # Another caller applies the representable schema. Reusing the migrator
    # must discard its old CREATE TABLE SQL, but retain repeatable warnings.
    supported = structure()
    plan = plan_migration(db, supported)
    apply_migration(db, supported, expected_plan=plan['plan_id'])
    migrator.prepareMigrationCommands()
    assert migrator.getChanges() == ''
    assert migrator.warnings == first_warnings
    assert desired == original


@pytest.mark.parametrize('change', ['database', 'structure', 'destination', 'removals'])
def test_real_drift_rejected_before_execution(existing_database, tmp_path, monkeypatch, change):
    db = existing_database
    desired = structure()
    plan = plan_migration(db, desired)
    kwargs = {}
    if change == 'database':
        db.execute('CREATE TABLE alfa.external_change (id integer)')
        db.commit()
    elif change == 'structure':
        desired['root']['schemas']['alfa']['tables']['items']['columns']['id']['attributes']['dtype'] = 'T'
    elif change == 'destination':
        db = SqliteDatabase({'dbname': str(tmp_path / 'other.db')}, application_schemas=['alfa'])
    else:
        kwargs['allow_removals'] = True
    execute = Mock(wraps=db.adapter.execute)
    monkeypatch.setattr(db.adapter, 'execute', execute)
    try:
        with pytest.raises(StaleMigrationPlan):
            apply_migration(db, desired, expected_plan=plan['plan_id'], **kwargs)
        execute.assert_not_called()
    finally:
        if db is not existing_database:
            db.closeConnection()


def test_unsupported_representation_blocks_even_database_creation(tmp_path, monkeypatch):
    path = tmp_path / 'absent.db'
    db = SqliteDatabase({'dbname': str(path)}, application_schemas=['alfa'])
    desired = structure()
    desired['root']['schemas']['alfa']['tables']['items']['attributes']['comment'] = 'Items'
    original = copy.deepcopy(desired)
    execute = Mock(wraps=db.adapter.execute)
    monkeypatch.setattr(db.adapter, 'execute', execute)
    try:
        plan = plan_migration(db, desired)
        assert plan['skipped'] and not plan['empty']
        with pytest.raises(UnsupportedMigration, match='comments'):
            apply_migration(db, desired, expected_plan=plan['plan_id'])
        execute.assert_not_called()
        assert not path.exists()
        assert desired == original
        assert plan_migration(db, desired) == plan
    finally:
        db.closeConnection()


def test_unsupported_alteration_blocks_supported_commands(existing_database, monkeypatch):
    db = existing_database
    desired = structure()
    plan = plan_migration(db, desired)
    apply_migration(db, desired, expected_plan=plan['plan_id'])
    table = desired['root']['schemas']['alfa']['tables']['items']
    table['columns']['id']['attributes']['dtype'] = 'T'
    new_column = copy.deepcopy(table['columns']['id'])
    new_column['entity_name'] = new_column['column_name'] = 'label'
    table['columns']['label'] = new_column
    plan = plan_migration(db, desired)
    assert plan['skipped'] and 'ADD COLUMN' in plan['sql']
    execute = Mock(wraps=db.adapter.execute)
    monkeypatch.setattr(db.adapter, 'execute', execute)
    with pytest.raises(UnsupportedMigration, match='alter_column_type'):
        apply_migration(db, desired, expected_plan=plan['plan_id'])
    execute.assert_not_called()


def test_service_removals_require_explicit_opt_in(existing_database):
    db = existing_database
    desired = structure()
    plan = plan_migration(db, desired)
    apply_migration(db, desired, expected_plan=plan['plan_id'])
    db.execute('ALTER TABLE alfa.items ADD COLUMN obsolete text')
    db.execute('CREATE TABLE alfa.retained (id integer)')
    db.commit()
    plan = plan_migration(db, desired)
    assert plan['empty']
    result = apply_migration(db, desired, expected_plan=plan['plan_id'])
    assert result['verified']
    assert db.execute('SELECT obsolete FROM alfa.items').fetchall() == []
    assert db.execute('SELECT COUNT(*) FROM alfa.retained').fetchone() == (0,)
    plan = plan_migration(db, desired, allow_removals=True)
    assert 'DROP COLUMN "obsolete"' in plan['sql']
    assert 'DROP TABLE' not in plan['sql']
    result = apply_migration(db, desired, expected_plan=plan['plan_id'], allow_removals=True)
    assert result['verified']
    columns = {row[1] for row in db.execute('PRAGMA alfa.table_info(items)')}
    assert columns == {'id'}
    # The existing contract never infers whole-table removal, even on opt-in.
    assert db.execute('SELECT COUNT(*) FROM alfa.retained').fetchone() == (0,)


@pytest.mark.parametrize('outcome', [
    'success', 'validation', 'introspection', 'execution', 'verification', 'verification_error',
])
def test_services_leave_connection_owned_by_caller(existing_database, monkeypatch, outcome):
    db = existing_database
    db.startup()
    connection = db._connection
    close = Mock(wraps=db.closeConnection)
    desired = structure()
    plan = plan_migration(db, desired)
    with monkeypatch.context() as patch:
        patch.setattr(db, 'closeConnection', close)
        if outcome == 'validation':
            with pytest.raises(SqlValidationError):
                plan_migration(db, None)
        elif outcome == 'introspection':
            patch.setattr(db.adapter.reader, 'get_json_struct', Mock(side_effect=RuntimeError('read failed')))
            with pytest.raises(RuntimeError, match='read failed'):
                plan_migration(db, desired)
        elif outcome == 'execution':
            patch.setattr(db.adapter, 'execute', Mock(side_effect=RuntimeError('DDL failed')))
            with pytest.raises(MigrationExecutionError):
                apply_migration(db, desired, expected_plan=plan['plan_id'])
        elif outcome == 'verification':
            # A successful adapter call that applies no DDL must not be
            # mistaken for a converged migration.
            patch.setattr(db.adapter, 'execute', Mock())
            result = apply_migration(db, desired, expected_plan=plan['plan_id'])
            assert not result['verified']
            assert not result['remaining']['empty']
        elif outcome == 'verification_error':
            reader = db.adapter.reader
            current = reader.get_json_struct(db.get_dbname(), schemas=['alfa'])
            patch.setattr(reader, 'get_json_struct', Mock(side_effect=[current, RuntimeError('verify failed')]))
            with pytest.raises(RuntimeError, match='verify failed'):
                apply_migration(db, desired, expected_plan=plan['plan_id'])
            assert connection.execute("SELECT name FROM alfa.sqlite_master WHERE name='items'").fetchone() == ('items',)
        else:
            assert apply_migration(db, desired, expected_plan=plan['plan_id'])['verified']
        close.assert_not_called()
        assert db._connection is connection
        assert connection.execute('SELECT 1').fetchone() == (1,)
