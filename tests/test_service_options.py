"""Service options (force, backup, ignore_constraint_name), backup report and facade factory."""

from uuid import uuid4

import pytest

from asqueel_migration import (
    JsonStructureProducer,
    MssqlDatabase,
    MysqlDatabase,
    PgDatabase,
    SqliteDatabase,
    UnsupportedMigration,
    apply_migration,
    database_for,
    plan_migration,
)
from asqueel_migration.exceptions import SqlMigrationError


@pytest.mark.parametrize(('implementation', 'facade'), [
    ('postgres', PgDatabase), ('postgres3', PgDatabase), ('postgres3:custom.module', PgDatabase),
    ('sqlite', SqliteDatabase), ('mysql', MysqlDatabase), ('mssql', MssqlDatabase),
])
def test_database_for_implementation(implementation, facade):
    db = database_for(implementation, {'dbname': 'target'}, application_schemas=['alfa'],
                      read_only_schemas=['ro'], tenant_schemas=['t1'])
    assert type(db) is facade
    assert db.get_dbname() == 'target'
    assert (db.getApplicationSchemas(), db.readOnlySchemas(), db.getTenantSchemas()) == (['alfa'], ['ro'], ['t1'])


def test_database_for_refusals():
    with pytest.raises(SqlMigrationError, match='Unsupported migration backend: oracle'):
        database_for('oracle', {'dbname': 'target'})
    with pytest.raises(SqlMigrationError, match='Only SQLite'):
        database_for('postgres', {'dbname': 'target'}, connection=object())


def model(dtype, indexed=False):
    table = {'name': 'event', 'pkey': 'id', 'columns': [
        {'name': 'id', 'dtype': 'I', 'notnull': True}, {'name': 'happened', 'dtype': dtype},
    ]}
    if indexed:
        table['indexes'] = [{'name': 'event_happened', 'columns': ['happened']}]
    return JsonStructureProducer({'db': 'demo', 'schemas': [{
        'name': 'alfa', 'tables': [table],
    }]}).get_json_struct()


@pytest.fixture
def pg_database(pg_server):
    import psycopg
    from psycopg import sql

    name = 'test_service_options_' + uuid4().hex[:12]
    db = database_for('postgres', dict(pg_server, dbname=name), application_schemas=['alfa'])
    try:
        yield db
    finally:
        db.closeConnection()
        with psycopg.connect(**pg_server, dbname='postgres', autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))


def migrate(db, structure, **options):
    plan = plan_migration(db, structure, **options)
    return apply_migration(db, structure, expected_plan=plan['plan_id'], **options)


def filled(db):
    migrate(db, model('T'))
    db.adapter.execute("INSERT INTO alfa.event (id, happened) VALUES (1, '2026-01-02'), (2, 'not a date')")


@pytest.mark.postgresql
def test_filled_conversion_requires_force(pg_database):
    filled(pg_database)
    with pytest.raises(SqlMigrationError):
        plan_migration(pg_database, model('DH'))
    forced = plan_migration(pg_database, model('DH'), force=True)
    assert forced['plan_id'] != plan_migration(pg_database, model('DH'), backup=True)['plan_id']
    result = apply_migration(pg_database, model('DH'), expected_plan=forced['plan_id'], force=True)
    assert result['verified'] and result['backups'] == {}
    rows = pg_database.execute('SELECT id, happened::date::text FROM alfa.event ORDER BY id').fetchall()
    assert rows == [(1, '2026-01-02'), (2, None)]


@pytest.mark.postgresql
@pytest.mark.parametrize('allow_removals', [False, True])
def test_backup_report_keeps_lost_values(pg_database, allow_removals):
    filled(pg_database)
    result = migrate(pg_database, model('DH'), backup=True, allow_removals=allow_removals)
    report = result['backups']['alfa.event.happened']
    assert report['lost_values'] == 1
    # The comparison after apply runs without removals: it would drop the backup column.
    assert result['verified'], result['remaining']
    backup = report['backup_column']
    assert pg_database.execute(f'SELECT "{backup}" FROM alfa.event WHERE id = 2').fetchone() == ('not a date',)
    pg_database.commit()


@pytest.mark.postgresql
def test_backup_report_is_empty_without_loss(pg_database):
    migrate(pg_database, model('T'))
    pg_database.adapter.execute("INSERT INTO alfa.event (id, happened) VALUES (1, '2026-01-02')")
    result = migrate(pg_database, model('DH'), backup=True)
    assert result['backups'] == {} and result['verified']


@pytest.mark.postgresql
def test_ignore_constraint_name(pg_database):
    migrate(pg_database, model('T', indexed=True))
    pg_database.adapter.execute('ALTER INDEX alfa.event_happened RENAME TO manual_name')
    assert plan_migration(pg_database, model('T', indexed=True))['empty']
    plan = plan_migration(pg_database, model('T', indexed=True), ignore_constraint_name=False)
    assert 'manual_name' in plan['sql'] and 'event_happened' in plan['sql']
    apply_migration(pg_database, model('T', indexed=True), expected_plan=plan['plan_id'],
                    ignore_constraint_name=False)
    names = pg_database.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'alfa' "
                                "AND indexname NOT LIKE '%pkey'").fetchall()
    assert names == [('event_happened',)]
    pg_database.commit()


@pytest.fixture
def sqlite_database(tmp_path):
    db = database_for('sqlite', {'dbname': str(tmp_path / 'demo.db')}, application_schemas=['alfa'])
    try:
        yield db
    finally:
        db.closeConnection()


@pytest.mark.parametrize('options', [{}, {'force': True}, {'backup': True}])
def test_sqlite_refuses_a_dtype_change_whatever_the_options(sqlite_database, options):
    filled(sqlite_database)
    plan = plan_migration(sqlite_database, model('DH'), **options)
    assert [change['capability'] for change in plan['skipped_changes']] == ['alter_column_type']
    with pytest.raises(UnsupportedMigration, match='alter_column_type'):
        apply_migration(sqlite_database, model('DH'), expected_plan=plan['plan_id'], **options)


def test_sqlite_ignore_constraint_name(sqlite_database):
    migrate(sqlite_database, model('T', indexed=True))
    # SQLite has no ALTER INDEX ... RENAME: the index is recreated under another name.
    sqlite_database.adapter.execute('DROP INDEX alfa.event_happened; '
                                    'CREATE INDEX alfa.manual_name ON event (happened)')
    assert plan_migration(sqlite_database, model('T', indexed=True))['empty']
    plan = plan_migration(sqlite_database, model('T', indexed=True), ignore_constraint_name=False)
    assert 'manual_name' in plan['sql'] and 'event_happened' in plan['sql']
    apply_migration(sqlite_database, model('T', indexed=True), expected_plan=plan['plan_id'],
                    ignore_constraint_name=False)
    names = sqlite_database.execute("SELECT name FROM alfa.sqlite_master WHERE type = 'index' "
                                    "AND name NOT LIKE 'sqlite_autoindex%'").fetchall()
    assert names == [('event_happened',)]
