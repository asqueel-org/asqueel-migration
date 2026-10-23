"""Generated columns: introspection, equal expressions, changes recorded as skipped."""

import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from asqueel_migration import (
    JsonStructureProducer,
    SqlMigrator,
    UnsupportedMigration,
    apply_migration,
    database_for,
    plan_migration,
)
from asqueel_migration.readers import SqliteReader


def model(expression='value * 2'):
    return JsonStructureProducer({'db': 'demo', 'schemas': [{
        'name': 'alfa', 'tables': [{'name': 'item', 'pkey': 'id', 'columns': [
            {'name': 'id', 'dtype': 'I', 'notnull': True},
            {'name': 'value', 'dtype': 'L'},
            {'name': 'computed', 'dtype': 'L', 'generated_expression': expression},
        ]}],
    }]}).get_json_struct()


@pytest.fixture(params=['sqlite', pytest.param('postgres', marks=pytest.mark.postgresql)])
def database(request, tmp_path):
    if request.param == 'sqlite':
        db = database_for('sqlite', {'dbname': str(tmp_path / 'main.db')}, application_schemas=['alfa'])
        try:
            yield db
        finally:
            db.closeConnection()
        return
    import psycopg
    from psycopg import sql

    pg_server = request.getfixturevalue('pg_server')
    name = 'test_generated_' + uuid4().hex[:12]
    db = database_for('postgres', dict(pg_server, dbname=name), application_schemas=['alfa'])
    try:
        yield db
    finally:
        db.closeConnection()
        with psycopg.connect(**pg_server, dbname='postgres', autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))


def migrate(db, structure):
    plan = plan_migration(db, structure)
    result = apply_migration(db, structure, expected_plan=plan['plan_id'])
    assert result['verified'], result['remaining']
    return result


def test_generated_column_round_trips(database):
    migrate(database, model())
    current = SqlMigrator(database, structure=model())
    current.prepareMigrationCommands()
    column = current.sqlStructure['root']['schemas']['alfa']['tables']['item']['columns']['computed']
    assert column['attributes']['generated_expression']
    plan = plan_migration(database, model())
    assert plan['empty'] and not plan['skipped'] and not plan['sql'].strip()


@pytest.mark.parametrize('expression', ['value * 3', 'value +', None])
def test_generated_expression_change_requires_explicit_migration(database, expression):
    migrate(database, model())
    database.adapter.execute('INSERT INTO "alfa"."item" ("id", "value") VALUES (1, 4)')
    desired = model(expression)
    plan = plan_migration(database, desired)
    assert not plan['empty'] and not plan['sql'].strip()
    assert [change['capability'] for change in plan['skipped_changes']] == ['alter_generated_expression']
    assert plan['skipped'] == [
        "unsupported 'alter_generated_expression': skipped alfa.item.computed; explicit migration required"
    ]
    with pytest.raises(UnsupportedMigration, match='explicit migration required'):
        apply_migration(database, desired, expected_plan=plan['plan_id'])
    assert database.execute('SELECT "computed" FROM "alfa"."item"').fetchall() == [(8,)]
    database.commit()


def test_sqlite_expression_parser_skips_literals_and_comments(tmp_path):
    path = str(tmp_path / 'main.db')
    expression = "coalesce(\"odd,name\", ') AS (') || '/*text*/'"
    connection = sqlite3.connect(path)
    connection.execute(
        f'CREATE TABLE x ("odd,name" TEXT, -- a, (b\n'
        f' result TEXT AS ({expression}) STORED /* AS (bad) */,'
        ' "v w" integer GENERATED ALWAYS AS (1 + 2) VIRTUAL)'
    )
    connection.close()
    reader = SqliteReader({'dbname': path})
    reader.connect()
    try:
        assert reader._generated_expressions('main', 'x') == {'result': expression, 'v w': '1 + 2'}
        hidden = {column['name']: column.get('generated_expression')
                  for column in reader.fetch_base_structure(['main'])}
        assert hidden == {'odd,name': None, 'result': expression, 'v w': '1 + 2'}
    finally:
        reader.close()


@pytest.mark.parametrize(('wanted', 'stored', 'same'), [
    ('value*2', 'value * 2 -- doubled', True),
    ('value /* x */ * 2', 'value\n*\n2', True),
    ("'a  b'", "'a b'", False),
    ('a b', 'ab', False),
])
def test_sqlite_expression_comparison(wanted, stored, same):
    assert SqliteReader({'dbname': 'unused'}).same_generated_expression('main', 'x', wanted, stored) is same


def test_reader_without_generated_expressions_records_nothing():
    reader = SimpleNamespace(reads_generated_expressions=False)
    migrator = SqlMigrator(SimpleNamespace(adapter=SimpleNamespace(reader=reader)))
    item = {'schema_name': 'alfa', 'table_name': 'item', 'entity_name': 'computed'}
    migrator.changed_generated_expression(item, None, 'value * 2')
    assert migrator.skipped == [] and migrator.warnings == []
