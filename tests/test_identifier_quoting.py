"""Regression coverage for quoted model identifiers (issue #16)."""

from copy import deepcopy
from uuid import uuid4

import pytest

from asqueel_migration import (
    JsonStructureProducer,
    PgDatabase,
    SqliteDatabase,
    SqlMigrator,
    StructureValidator,
)
from asqueel_migration.structures import new_column_item, new_relation_item, new_table_item
from asqueel_migration.writers import MssqlWriter, MysqlWriter, PgWriter, SqliteWriter


def test_empty_table_commands_do_not_require_a_database_adapter():
    table = {'columns': {}, 'relations': {}, 'indexes': {}, 'constraints': {}}
    assert SqlMigrator(object()).sqlCommandsForTable('s"x', 't"x', table) == {
        'commands': [], 'relation_commands': [],
    }


@pytest.mark.parametrize('writer_class', [PgWriter, MysqlWriter, MssqlWriter, SqliteWriter])
def test_writer_quotes_model_identifiers_without_changing_expressions(writer_class):
    writer = writer_class()
    assert writer.table_fullname('s"x', 't"x') == '"s""x"."t""x"'
    definition = writer.column_sql_definition('c"x', 'T', default="'a b'", extra_sql='COLLATE "C"')
    assert definition.startswith('"c""x" ')
    assert definition.endswith('DEFAULT \'a b\' COLLATE "C"')
    assert writer.constraint_sql('u"x', 'UNIQUE', ['c"x']) == (
        'CONSTRAINT "u""x" UNIQUE ("c""x")'
    )
    assert writer.constraint_sql('check"x', 'CHECK', check_clause='length("c""x") > 0') == (
        'CONSTRAINT "check""x" CHECK (length("c""x") > 0)'
    )


@pytest.mark.parametrize('writer_class', [PgWriter, MysqlWriter, MssqlWriter])
def test_writer_quotes_schema_alter_and_foreign_key_identifiers(writer_class):
    writer = writer_class()
    assert writer.create_schema_sql('s"x') == 'CREATE SCHEMA "s""x";'
    assert '"db""x"' in writer.create_db_sql('db"x')
    assert '"c""x"' in writer.alter_column_sql('c"x', 'integer')
    assert '"fk""x"' in writer.drop_constraint_sql('fk"x')
    assert writer.foreign_key_sql('fk"x', ['c"x'], 't"x', 's"x', ['id"x']) == (
        'CONSTRAINT "fk""x" FOREIGN KEY ("c""x") '
        'REFERENCES "s""x"."t""x" ("id""x")'
    )
    primary_key_sql = writer.add_table_pkey_sql('s"x', 't"x', 'Id"key,select')
    assert 'PRIMARY KEY ("Id""key","select")' in primary_key_sql.replace(', ', ',')


@pytest.fixture(params=['sqlite', pytest.param('pg', marks=pytest.mark.postgresql)])
def quoted_database(request, tmp_path):
    if request.param == 'sqlite':
        db = SqliteDatabase({'dbname': str(tmp_path / "quoted'file.db")},
                            application_schemas=['schema"quoted'])
        yield db
        db.closeConnection()
    else:
        import psycopg
        from psycopg import sql

        params = request.getfixturevalue('pg_server')
        name = 'test_quoted_' + uuid4().hex[:12]
        db = PgDatabase(dict(params, dbname=name), application_schemas=['schema"quoted'])
        try:
            yield db
        finally:
            db.closeConnection()
            with psycopg.connect(**params, dbname='postgres', autocommit=True) as connection:
                connection.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(
                    sql.Identifier(name)))


def quoted_model(db):
    return StructureValidator().validate(JsonStructureProducer({
        'db': db.get_dbname(),
        'schemas': [{'name': 'schema"quoted', 'tables': [{
            'name': 'table"quoted', 'pkey': 'Id"key',
            'columns': [
                {'name': 'Id"key', 'dtype': 'I', 'notnull': True},
                {'name': 'label"quoted', 'dtype': 'T'},
            ],
        }]}],
    }).get_json_struct())


def prepare(db, structure, **kwargs):
    migrator = SqlMigrator(db, **kwargs)
    migrator.ormStructure = deepcopy(structure)
    migrator.prepareMigrationCommands()
    return migrator


def test_quoted_identifiers_create_alter_drop_and_idempotence(quoted_database):
    db = quoted_database
    structure = quoted_model(db)
    prepare(db, structure).applyChanges()
    assert prepare(db, structure).getChanges() == ''
    table = structure['root']['schemas']['schema"quoted']['tables']['table"quoted']
    added = deepcopy(table['columns']['label"quoted'])
    added['entity_name'] = added['column_name'] = 'added"column'
    added['attributes']['unique'] = True
    table['columns']['added"column'] = added
    prepare(db, structure).applyChanges()
    assert prepare(db, structure).getChanges() == ''
    # Remove an unconstrained column to exercise the shared DROP COLUMN path.
    del table['columns']['label"quoted']
    prepare(db, structure, removeDisabled=False).applyChanges()
    assert prepare(db, structure, removeDisabled=False).getChanges() == ''
    assert db.adapter.reader.is_empty_column('schema"quoted', 'table"quoted', 'added"column')


def test_postgres_comment_and_primary_key_quoting():
    writer = PgWriter()
    assert writer.comment_on_column_sql('s"x', 't"x', 'c"x', "it's fine") == (
        'COMMENT ON COLUMN "s""x"."t""x"."c""x" IS \'it\'\'s fine\''
    )
    assert writer.drop_table_pkey_sql('s"x', 't"x') == (
        'ALTER TABLE "s""x"."t""x" DROP CONSTRAINT IF EXISTS "t""x_pkey";'
    )
    assert writer.create_extension_sql('uuid-ossp') == 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
    assert writer.add_not_null_sql('c"x') == 'ALTER COLUMN "c""x" SET NOT NULL'
    assert writer.drop_not_null_sql('c"x') == 'ALTER COLUMN "c""x" DROP NOT NULL'


@pytest.mark.postgresql
@pytest.mark.parametrize('quoted_database', ['pg'], indirect=True)
def test_quoted_primary_key_rebuild(quoted_database):
    db = quoted_database
    structure = quoted_model(db)
    table = structure['root']['schemas']['schema"quoted']['tables']['table"quoted']
    table['columns']['select'] = new_column_item(
        'schema"quoted', 'table"quoted', 'select', attributes={'dtype': 'I', 'notnull': True})
    prepare(db, structure).applyChanges()
    table['attributes']['pkeys'] = 'select'
    table['columns']['select']['attributes']['notnull'] = '_auto_'
    table['columns']['Id"key']['attributes']['notnull'] = True
    prepare(db, structure).applyChanges()
    assert prepare(db, structure).getChanges() == ''


@pytest.mark.postgresql
@pytest.mark.parametrize('quoted_database', ['pg'], indirect=True)
def test_quoted_foreign_key_create_rename_and_rebuild(quoted_database):
    db = quoted_database
    structure = quoted_model(db)
    tables = structure['root']['schemas']['schema"quoted']['tables']
    child = new_table_item('schema"quoted', 'child"quoted')
    child['columns']['parent"id'] = new_column_item(
        'schema"quoted', 'child"quoted', 'parent"id', attributes={'dtype': 'I'})
    relation = new_relation_item('schema"quoted', 'child"quoted', ['parent"id'], attributes={
        'related_schema': 'schema"quoted', 'related_table': 'table"quoted',
        'related_columns': ['Id"key'], 'constraint_type': 'FOREIGN KEY',
    })
    child['relations'][relation['entity_name']] = relation
    tables['child"quoted'] = child
    prepare(db, structure, ignore_constraint_name=False).applyChanges()
    assert prepare(db, structure, ignore_constraint_name=False).getChanges() == ''
    for name in ('fk"quoted', 'fk"renamed'):
        relation['attributes']['constraint_name'] = name
        prepare(db, structure, ignore_constraint_name=False).applyChanges()
        assert prepare(db, structure, ignore_constraint_name=False).getChanges() == ''
    relation['attributes']['on_delete'] = 'CASCADE'
    prepare(db, structure, ignore_constraint_name=False).applyChanges()
    assert prepare(db, structure, ignore_constraint_name=False).getChanges() == ''


@pytest.mark.postgresql
@pytest.mark.parametrize('quoted_database', ['pg'], indirect=True)
def test_quoted_type_conversion_and_backup_verification(quoted_database):
    db = quoted_database
    structure = quoted_model(db)
    table = structure['root']['schemas']['schema"quoted']['tables']['table"quoted']
    table['attributes']['comment'] = "table's comment"
    table['columns']['label"quoted']['attributes']['comment'] = "column's comment"
    prepare(db, structure).applyChanges()
    db.adapter.execute(
        'INSERT INTO "schema""quoted"."table""quoted" ("Id""key", "label""quoted") '
        "VALUES (1, 'invalid')")
    table['columns']['label"quoted']['attributes']['dtype'] = 'I'
    migration = prepare(db, structure, backup=True)
    migration.applyChanges()
    report = migration.verifyConversionBackups()
    assert report['schema"quoted.table"quoted.label"quoted']['lost_values'] == 1
    assert report['schema"quoted.table"quoted.label"quoted']['backup_column'] == 'label"quoted__T'
    assert prepare(db, structure).getChanges() == ''
