"""Input ownership, repeatable preparation and reviewed-plan execution."""

import copy
import json
from types import SimpleNamespace

import pytest

from asqueel_migration import (
    JsonStructureProducer,
    SqliteDatabase,
    SqlMigrator,
    StaleMigrationPlan,
    apply_migration,
    plan_migration,
)
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


def test_plan_apply_verify_and_stale_plan(tmp_path):
    db = SqliteDatabase({'dbname': str(tmp_path / 'db.sqlite')}, application_schemas=['alfa'])
    try:
        desired = structure()
        plan = plan_migration(db, desired)
        assert 'CREATE TABLE' in plan['sql']
        with pytest.raises(StaleMigrationPlan):
            apply_migration(db, desired, expected_plan='wrong')
        assert plan_migration(db, desired)['plan_id'] == plan['plan_id']
        result = apply_migration(db, desired, expected_plan=plan['plan_id'])
        assert result['verified']
        assert result['remaining']['empty']
        with pytest.raises(StaleMigrationPlan):
            apply_migration(db, desired, expected_plan=plan['plan_id'])
    finally:
        db.closeConnection()
