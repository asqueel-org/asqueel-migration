"""Backup verification on live PostgreSQL must not block on its own read lock."""

import threading
from copy import deepcopy
from uuid import uuid4

import pytest

from asqueel_migration import JsonStructureProducer, PgDatabase, SqlMigrator

pytestmark = pytest.mark.postgresql

TIMEOUT = 15


@pytest.fixture
def pg_database(pg_server):
    import psycopg
    from psycopg import sql

    name = 'test_backup_verify_' + uuid4().hex[:12]
    db = PgDatabase(dict(pg_server, dbname=name), application_schemas=['alfa'])
    try:
        yield db
    finally:
        db.closeConnection()
        with psycopg.connect(**pg_server, dbname='postgres', autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(
                sql.Identifier(name)))


def model(db, dtype):
    return JsonStructureProducer({
        'db': db.get_dbname(),
        'schemas': [{'name': 'alfa', 'tables': [{
            'name': 'event', 'pkey': 'id',
            'columns': [
                {'name': 'id', 'dtype': 'I', 'notnull': True},
                {'name': 'happened', 'dtype': dtype},
            ],
        }]}],
    }).get_json_struct()


def prepare(db, structure, **kwargs):
    migrator = SqlMigrator(db, **kwargs)
    migrator.ormStructure = deepcopy(structure)
    migrator.prepareMigrationCommands()
    return migrator


def verify_with_timeout(db, migration):
    """Run verifyConversionBackups in a thread; fail instead of hanging."""
    outcome = {}
    worker = threading.Thread(
        target=lambda: outcome.update(report=migration.verifyConversionBackups()),
        daemon=True,
    )
    worker.start()
    worker.join(TIMEOUT)
    if worker.is_alive():
        # Closing the persistent connection releases the read lock, so the
        # blocked DROP completes and the thread ends.
        db.closeConnection()
        worker.join(TIMEOUT)
        pytest.fail(f'verifyConversionBackups blocked for more than {TIMEOUT}s')
    return outcome['report']


def backup_columns(db):
    rows = db.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'alfa' AND table_name = 'event' ORDER BY column_name"
    ).fetchall()
    db.commit()
    return [row[0] for row in rows]


def test_lossless_conversion_drops_backup_without_blocking(pg_database):
    db = pg_database
    prepare(db, model(db, 'T')).applyChanges()
    db.adapter.execute("INSERT INTO alfa.event (id, happened) VALUES (1, '2026-01-02')")
    migration = prepare(db, model(db, 'DH'), backup=True)
    migration.applyChanges()
    assert verify_with_timeout(db, migration) == {}
    assert backup_columns(db) == ['happened', 'id']
    assert db.execute('SELECT happened::date::text FROM alfa.event').fetchall() == [('2026-01-02',)]
