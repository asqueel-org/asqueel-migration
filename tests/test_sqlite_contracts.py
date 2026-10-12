"""Public plan/apply contracts for SQLite adoption and new-table constraints."""

import copy
import sqlite3

import pytest

from asqueel_migration import (
    JsonStructureProducer,
    SqliteDatabase,
    SqlMigrator,
    UnsupportedMigration,
    apply_migration,
    plan_migration,
)


def model(schema='main', *, foreign_key=True, unique=True, composite=False):
    parent = {'name': 'tenants', 'pkey': 'id', 'columns': [{'name': 'id', 'dtype': 'T'}]}
    child = {
        'name': 'messages', 'pkey': 'pk', 'columns': [
            {'name': 'pk', 'dtype': 'T'}, {'name': 'tenant_id', 'dtype': 'T', 'notnull': True},
            {'name': 'id', 'dtype': 'T', 'notnull': True},
        ],
    }
    if composite:
        parent['pkey'] = 'id,region'
        parent['columns'].append({'name': 'region', 'dtype': 'T'})
        child['columns'].append({'name': 'region', 'dtype': 'T'})
    if foreign_key:
        child['relations'] = [{
            'columns': ['tenant_id', 'region'] if composite else ['tenant_id'],
            'related_schema': schema, 'related_table': 'tenants',
            'related_columns': ['id', 'region'] if composite else ['id'],
            'on_delete': 'CASCADE', 'on_update': 'CASCADE',
        }]
    if unique:
        child['constraints'] = [{'type': 'UNIQUE', 'columns': ['tenant_id', 'id']}]
    # Child first exercises references to a table created later in the script.
    return JsonStructureProducer({'db': 'logical', 'schemas': [
        {'name': schema, 'tables': [child, parent]},
    ]}).get_json_struct()


def apply(db, desired):
    plan = plan_migration(db, desired)
    assert not plan['skipped'], plan['skipped']
    result = apply_migration(db, desired, expected_plan=plan['plan_id'])
    assert result['verified'], result['remaining']
    return plan


@pytest.mark.parametrize('existing', [False, True])
def test_main_and_attached_schema_persist(tmp_path, existing):
    path = tmp_path / 'base.db'
    if existing:
        sqlite3.connect(path).close()
    desired = model(foreign_key=False, unique=False)
    desired['root']['schemas'].update(model('mail', foreign_key=False, unique=False)['root']['schemas'])
    for _ in range(2):
        db = SqliteDatabase({'dbname': str(path)}, application_schemas=['main', 'mail'])
        try:
            plan = apply(db, desired)
            assert 'ATTACH DATABASE' not in plan['sql'] or 'AS "main"' not in plan['sql']
            for schema in ('main', 'mail'):
                db.execute(f"INSERT OR IGNORE INTO {schema}.tenants VALUES ('kept')")
                assert db.execute(f'SELECT id FROM {schema}.tenants').fetchall() == [('kept',)]
            db.commit()
            assert plan_migration(db, desired)['empty']
        finally:
            db.closeConnection()
    assert not (tmp_path / 'base_main.db').exists()
    assert (tmp_path / 'base_mail.db').exists()


@pytest.mark.parametrize('schema', ['main', 'mail'])
@pytest.mark.parametrize('declared', ['TIMESTAMP', 'timestamp', 'Timestamp'])
def test_legacy_timestamp_preserved(tmp_path, schema, declared):
    path = tmp_path / 'base.db'
    sqlite3.connect(path).close()
    actual = path if schema == 'main' else tmp_path / 'base_mail.db'
    with sqlite3.connect(actual) as conn:
        conn.execute(f'CREATE TABLE tenants (id TEXT PRIMARY KEY, created_at {declared} DEFAULT CURRENT_TIMESTAMP)')
        conn.execute("INSERT INTO tenants VALUES ('kept', '2025-01-02 03:04:05')")
        original_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='tenants'").fetchone()
    desired = JsonStructureProducer({'db': 'logical', 'schemas': [{'name': schema, 'tables': [
        {'name': 'tenants', 'pkey': 'id', 'columns': [
            {'name': 'id', 'dtype': 'T'},
            {'name': 'created_at', 'dtype': 'DH', 'sqldefault': 'CURRENT_TIMESTAMP'},
        ]},
    ]}]}).get_json_struct()
    db = SqliteDatabase({'dbname': str(path)}, application_schemas=[schema])
    try:
        assert apply(db, desired)['empty']
        assert db.execute(f'SELECT * FROM {schema}.tenants').fetchall() == [('kept', '2025-01-02 03:04:05')]
        assert db.execute(f"SELECT sql FROM {schema}.sqlite_master WHERE name='tenants'").fetchone() == original_sql
    finally:
        db.closeConnection()


@pytest.mark.parametrize('schema', ['main', 'mail'])
@pytest.mark.parametrize('composite', [False, True])
def test_fresh_constraints_enforced_and_survive_restart(tmp_path, schema, composite):
    path = tmp_path / 'base.db'
    desired = model(schema, composite=composite)
    original = copy.deepcopy(desired)
    db = SqliteDatabase({'dbname': str(path)}, application_schemas=[schema])
    try:
        plan = apply(db, desired)
        assert 'FOREIGN KEY' in plan['sql'] and ' UNIQUE ' in plan['sql']
        db.closeConnection()
        assert plan_migration(db, desired)['empty']
        suffix = ", 'eu'" if composite else ''
        for tenant in ('a', 'b'):
            db.execute(f"INSERT INTO {schema}.tenants VALUES ('{tenant}'{suffix})")
        db.execute(f"INSERT INTO {schema}.messages VALUES ('pk1', 'a', 'same'{suffix})")
        db.execute(f"INSERT INTO {schema}.messages VALUES ('pk2', 'b', 'same'{suffix})")
        with pytest.raises(sqlite3.IntegrityError, match='UNIQUE'):
            db.execute(f"INSERT INTO {schema}.messages VALUES ('pk3', 'a', 'same'{suffix})")
        with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'):
            db.execute(f"INSERT INTO {schema}.messages VALUES ('pk4', 'missing', 'other'{suffix})")
        db.execute(f"UPDATE {schema}.tenants SET id='renamed' WHERE id='a'")
        assert db.execute(f"SELECT tenant_id FROM {schema}.messages WHERE pk='pk1'").fetchone() == ('renamed',)
        db.execute(f"DELETE FROM {schema}.tenants WHERE id='renamed'")
        assert db.execute(f'SELECT pk FROM {schema}.messages').fetchall() == [('pk2',)]
        db.commit()
        db.closeConnection()
        assert not plan_migration(db, desired)['skipped']
        assert plan_migration(db, desired)['empty']
        assert db.execute(f'SELECT pk FROM {schema}.messages').fetchall() == [('pk2',)]
        assert desired == original
    finally:
        db.closeConnection()


@pytest.mark.parametrize('kind', ['foreign_key', 'unique'])
def test_existing_table_constraint_additions_refused(tmp_path, kind):
    db = SqliteDatabase({'dbname': str(tmp_path / 'base.db')}, application_schemas=['main'])
    try:
        apply(db, model(foreign_key=False, unique=False))
        desired = model(foreign_key=kind == 'foreign_key', unique=kind == 'unique')
        plan = plan_migration(db, desired)
        assert plan['skipped_changes'][0]['capability'] == 'add_constraint'
        with pytest.raises(UnsupportedMigration, match='add_constraint'):
            apply_migration(db, desired, expected_plan=plan['plan_id'])
        assert not db.execute('PRAGMA main.foreign_key_list(messages)').fetchall()
    finally:
        db.closeConnection()


@pytest.mark.parametrize('change', ['cross_schema', 'deferrable', 'check'])
def test_unsupported_features_refused_before_creation(tmp_path, change):
    path = tmp_path / 'base.db'
    db = SqliteDatabase({'dbname': str(path)}, application_schemas=['main'])
    desired = model()
    table = desired['root']['schemas']['main']['tables']['messages']
    relation = next(iter(table['relations'].values()))['attributes']
    if change == 'cross_schema':
        relation['related_schema'] = 'elsewhere'
        desired['root']['schemas'].update(model('elsewhere')['root']['schemas'])
        db = SqliteDatabase({'dbname': str(path)}, application_schemas=['main', 'elsewhere'])
    elif change == 'deferrable':
        relation['deferrable'] = True
    else:
        constraint = next(iter(table['constraints'].values()))['attributes']
        constraint.pop('columns')
        constraint.update(constraint_type='CHECK', check_clause='id IS NOT NULL')
    plan = plan_migration(db, desired)
    with pytest.raises(UnsupportedMigration):
        apply_migration(db, desired, expected_plan=plan['plan_id'])
    assert not path.exists()


def test_skipped_changes_are_structured_repeatable_and_keep_warnings(tmp_path):
    db = SqliteDatabase({'dbname': str(tmp_path / 'base.db')}, application_schemas=['main'])
    try:
        desired = model(foreign_key=False, unique=False)
        apply(db, desired)
        table = desired['root']['schemas']['main']['tables']['messages']
        table['columns']['id']['attributes']['dtype'] = 'I'
        table['attributes']['comment'] = 'not supported'
        migrator = SqlMigrator(db, structure=desired)
        migrator.prepareMigrationCommands()
        skipped = copy.deepcopy(migrator.skipped)
        assert {entry['capability'] for entry in skipped} == {'comments', 'alter_column_type'}
        assert migrator.warnings == [entry['warning'] for entry in skipped]
        assert "unsupported 'alter_column_type': skipped dtype change on main.messages.id" in migrator.warnings
        migrator.prepareMigrationCommands()
        assert migrator.skipped == skipped
        plan = plan_migration(db, desired)
        assert plan['skipped_changes'] == skipped
        assert plan['skipped'] == migrator.warnings
    finally:
        db.closeConnection()


@pytest.mark.parametrize('schema', ['main', 'mail'])
def test_add_constrained_table_to_populated_database(tmp_path, schema):
    db = SqliteDatabase({'dbname': str(tmp_path / 'base.db')}, application_schemas=[schema])
    desired = model(schema)
    initial = copy.deepcopy(desired)
    del initial['root']['schemas'][schema]['tables']['messages']
    try:
        apply(db, initial)
        db.execute(f"INSERT INTO {schema}.tenants VALUES ('kept')")
        db.commit()
        plan = apply(db, desired)
        assert 'CREATE TABLE' in plan['sql'] and 'FOREIGN KEY' in plan['sql']
        assert db.execute(f'SELECT id FROM {schema}.tenants').fetchall() == [('kept',)]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"INSERT INTO {schema}.messages VALUES ('pk', 'absent', 'id')")
    finally:
        db.closeConnection()


@pytest.mark.parametrize('change', ['fk_action', 'unique_columns', 'constraint_name'])
def test_constraint_changes_do_not_modify_existing_data(tmp_path, change):
    db = SqliteDatabase({'dbname': str(tmp_path / 'base.db')}, application_schemas=['main'])
    desired = model()
    try:
        apply(db, desired)
        db.execute("INSERT INTO main.tenants VALUES ('kept')")
        db.execute("INSERT INTO main.messages VALUES ('pk', 'kept', 'id')")
        db.commit()
        table = desired['root']['schemas']['main']['tables']['messages']
        if change == 'fk_action':
            next(iter(table['relations'].values()))['attributes']['on_delete'] = 'RESTRICT'
        elif change == 'unique_columns':
            # Different membership requires an unsupported new constraint.
            source = {'db': 'logical', 'schemas': [{'name': 'main', 'tables': [{
                'name': 'messages', 'constraints': [{'type': 'UNIQUE', 'columns': ['pk', 'id']}],
            }]}]}
            table['constraints'] = JsonStructureProducer(source).get_json_struct()['root']['schemas']['main']['tables']['messages']['constraints']
        else:
            # SQLite PRAGMAs do not retain authored names. Strict name tracking
            # must record a skip instead of emitting an invalid RENAME.
            migrator = SqlMigrator(db, structure=desired, ignore_constraint_name=False)
            migrator.prepareMigrationCommands()
            assert migrator.skipped
            assert 'RENAME CONSTRAINT' not in migrator.getChanges()
            return
        plan = plan_migration(db, desired)
        with pytest.raises(UnsupportedMigration):
            apply_migration(db, desired, expected_plan=plan['plan_id'])
        assert db.execute('SELECT * FROM main.messages').fetchall() == [('pk', 'kept', 'id')]
    finally:
        db.closeConnection()


def test_introspect_legacy_fk_with_implicit_parent_primary_key(tmp_path):
    path = tmp_path / 'base.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE tenants (id TEXT PRIMARY KEY)')
        conn.execute('CREATE TABLE messages (pk TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, id TEXT NOT NULL, FOREIGN KEY (tenant_id) REFERENCES tenants)')
    desired = model(unique=False)
    relation = next(iter(desired['root']['schemas']['main']['tables']['messages']['relations'].values()))['attributes']
    relation.pop('on_update')
    relation.pop('on_delete')
    db = SqliteDatabase({'dbname': str(path)}, application_schemas=['main'])
    try:
        assert apply(db, desired)['empty']
    finally:
        db.closeConnection()
