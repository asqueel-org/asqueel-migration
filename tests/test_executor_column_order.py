"""Legacy #1194: column DDL must survive a simultaneous primary-key rebuild."""

from copy import deepcopy
from uuid import uuid4

import pytest

from genro_sqlmigration import (
    JsonStructureProducer,
    MssqlDatabase,
    MysqlDatabase,
    PgDatabase,
    SqliteDatabase,
    SqlMigrator,
)

from .support.orm_producer import SrcModel
from .support.pg_database import PgTestDatabase


def table_commands(command=None, columns=None, indexes=None, relations=None):
    return {'command': command, 'columns': columns or {}, 'constraints': {},
            'indexes': indexes or {}, 'relations': relations or {}}


def test_added_column_kept_with_pkey_rebuild():
    migrator = SqlMigrator(PgDatabase({'dbname': 'unused'}))
    table = table_commands(
        command='ALTER TABLE "public"."example" ADD PRIMARY KEY (id,code);',
        columns={'code': {'command': 'ADD COLUMN "code" text'}},
        indexes={'code_idx': {'command': 'CREATE INDEX code_idx ON "public"."example" (code);'}},
        relations={'code_fk': {'command': 'ADD CONSTRAINT code_fk FOREIGN KEY (code) REFERENCES codes(code)'}},
    )
    result = migrator.sqlCommandsForTable('public', 'example', table)
    assert len(result['commands']) == 3
    assert 'ADD COLUMN "code"' in result['commands'][0]
    assert result['commands'][1] == table['command']
    assert result['commands'][2] == table['indexes']['code_idx']['command']
    assert 'FOREIGN KEY (code)' in result['relation_commands'][0]


def test_new_table_emits_only_create_table():
    migrator = SqlMigrator(PgDatabase({'dbname': 'unused'}))
    command = 'CREATE TABLE "public"."example" (id integer PRIMARY KEY);'
    assert migrator.sqlCommandsForTable('public', 'example', table_commands(command)) == {
        'commands': [command], 'relation_commands': []}


def test_changed_column_without_pkey_rebuild():
    migrator = SqlMigrator(PgDatabase({'dbname': 'unused'}))
    table = table_commands(columns={
        'code': {'command': 'ADD COLUMN "code" text'},
        'title': {'command': 'ADD COLUMN "title" text'},
    })
    assert migrator.sqlCommandsForTable('public', 'example', table)['commands'] == [
        'ALTER TABLE "public"."example"\nADD COLUMN "code" text,\nADD COLUMN "title" text;']


@pytest.mark.postgresql
@pytest.mark.parametrize('new_key', ['id,code', 'code'])
def test_pkey_rebuild_applies_column_changes_and_converges(pg_server, new_key):
    model = SrcModel()
    model.package('alfa', sqlschema='alfa')
    db = PgTestDatabase('test_pkey_order_' + uuid4().hex[:12], pg_server, model)

    def structure(pkey, columns):
        return JsonStructureProducer({'db': db.get_dbname(), 'schemas': [
            {'name': 'alfa', 'tables': [{'name': 'example', 'pkey': pkey,
                                         'columns': columns}]}]}).get_json_struct()

    def prepare(source):
        migrator = SqlMigrator(db)
        migrator.ormStructure = deepcopy(source)
        migrator.prepareMigrationCommands()
        return migrator

    try:
        prepare(structure('id', [{'name': 'id', 'dtype': 'I'},
                                 {'name': 'title', 'dtype': 'A', 'size': '0:10'}])).applyChanges()
        target = structure(new_key, [{'name': 'id', 'dtype': 'I', 'notnull': True},
                                     {'name': 'title', 'dtype': 'A', 'size': '0:30'},
                                     {'name': 'code', 'dtype': 'I', 'sqldefault': '7'}])
        db.adapter.execute('INSERT INTO "alfa"."example" (id, title) VALUES (1, \'kept\');')
        migrator = prepare(target)
        sql = migrator.getChanges()
        assert sql.index('ADD COLUMN "code"') < sql.index('ADD PRIMARY KEY')
        assert sql.index('ALTER COLUMN "title"') < sql.index('ADD PRIMARY KEY')
        migrator.applyChanges()
        assert prepare(target).getChanges() == ''
        with db.adapter.connect() as connection:
            assert connection.execute('SELECT id, title, code FROM "alfa"."example"').fetchall() == [(1, 'kept', 7)]
    finally:
        db.dropDb(db.get_dbname())


@pytest.mark.parametrize('database_class', [PgDatabase, MysqlDatabase, MssqlDatabase, SqliteDatabase])
def test_column_changes_keep_dialect_assembly(database_class):
    migrator = SqlMigrator(database_class({'dbname': 'unused'}))
    fragments = ['ADD COLUMN "code" text', 'ADD COLUMN "title" text']
    table = table_commands(command='PRIMARY KEY REBUILD', columns={
        str(i): {'command': fragment} for i, fragment in enumerate(fragments)})
    commands = migrator.sqlCommandsForTable('alfa', 'example', table)['commands']
    assert commands[:-1] == migrator.db.adapter.struct_alter_table_commands(
        'alfa', 'example', fragments)
    assert commands[-1] == 'PRIMARY KEY REBUILD'
