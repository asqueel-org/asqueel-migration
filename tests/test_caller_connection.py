"""SqliteDatabase over a caller's connection: every read and DDL through it, never closed."""

import sqlite3

import pytest

from asqueel_migration import JsonStructureProducer, apply_migration, database_for, plan_migration
from asqueel_migration.exceptions import SqlMigrationError


def model(schema):
    return JsonStructureProducer({'db': 'memory', 'schemas': [{
        'name': schema, 'tables': [{'name': 'item', 'pkey': 'id', 'columns': [
            {'name': 'id', 'dtype': 'I', 'notnull': True},
            {'name': 'value', 'dtype': 'L'},
            {'name': 'computed', 'dtype': 'L', 'generated_expression': 'value * 2'},
        ]}],
    }]}).get_json_struct()


@pytest.fixture
def connection():
    connection = sqlite3.connect(':memory:')
    yield connection
    connection.close()


@pytest.mark.parametrize('schema', ['main', 'alfa'])
def test_migration_runs_on_the_caller_connection(connection, schema):
    if schema != 'main':
        connection.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
    db = database_for('sqlite', {'dbname': ':memory:'}, application_schemas=[schema], connection=connection)
    desired = model(schema)
    plan = plan_migration(db, desired)
    result = apply_migration(db, desired, expected_plan=plan['plan_id'])
    assert result['verified']
    db.closeConnection()
    connection.execute(f'INSERT INTO "{schema}"."item" ("id", "value") VALUES (1, 3)')
    assert connection.execute(f'SELECT "computed" FROM "{schema}"."item"').fetchone() == (6,)
    connection.commit()
    assert plan_migration(db, desired)['empty']
    assert db.adapter.reader._conn is None
    assert connection.execute('SELECT 1').fetchone() == (1,)


def test_apply_refuses_a_connection_inside_a_transaction(connection):
    connection.execute('CREATE TABLE pending (id INTEGER)')
    connection.execute('INSERT INTO pending VALUES (1)')
    assert connection.in_transaction
    db = database_for('sqlite', {'dbname': ':memory:'}, application_schemas=['main'], connection=connection)
    desired = model('main')
    plan = plan_migration(db, desired)
    with pytest.raises(SqlMigrationError, match='Commit or rollback'):
        apply_migration(db, desired, expected_plan=plan['plan_id'])
    assert connection.in_transaction
    assert connection.execute('SELECT id FROM pending').fetchall() == [(1,)]
