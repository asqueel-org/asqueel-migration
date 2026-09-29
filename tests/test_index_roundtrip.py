"""Physical index names and ordering survive DDL and introspection (#8, #9)."""

from copy import deepcopy
from uuid import uuid4

import pytest

from genro_sqlmigration import JsonStructureProducer, SqliteDatabase, SqlMigrator
from genro_sqlmigration.writers import MssqlWriter, MysqlWriter, PgWriter, SqliteWriter

from .support.orm_producer import SrcModel
from .support.pg_database import PgTestDatabase


@pytest.mark.parametrize('writer_class', [PgWriter, MysqlWriter, MssqlWriter, SqliteWriter])
@pytest.mark.parametrize('name', ['select', 'ix-with-dash', 'MixedCase', 'ix"quoted',
                                  'ix`tick', 'ix]bracket', 'ix  spaced'])
def test_quoted_index_ddl(writer_class, name):
    writer = writer_class()
    quoted = '"' + name.replace('"', '""') + '"'
    assert writer.quote_identifier(name) == quoted
    target = f'"alfa".{quoted}' if writer_class is SqliteWriter else quoted
    table = '"invoice"' if writer_class is SqliteWriter else '"alfa"."invoice"'
    method = ' USING btree' if writer_class is PgWriter else ''
    assert writer.create_index_sql('alfa', 'invoice', {'title': None, 'id': 'DESC'},
                                   index_name=name) == (
        f'CREATE INDEX {target} ON {table}{method} ("title", "id" DESC);'
    )
    expected_drop = (f'DROP INDEX {quoted} ON "alfa"."invoice";'
                     if writer_class in (MysqlWriter, MssqlWriter)
                     else f'DROP INDEX IF EXISTS "alfa".{quoted};')
    assert writer.drop_index_sql('alfa', 'invoice', name) == expected_drop


@pytest.fixture(params=['sqlite', pytest.param('pg', marks=pytest.mark.postgresql)])
def index_db(request, tmp_path):
    if request.param == 'sqlite':
        db = SqliteDatabase({'dbname': str(tmp_path / 'index.sqlite')},
                            application_schemas=['alfa'])
    else:
        source = SrcModel()
        source.package('alfa')
        db = PgTestDatabase('test_indexes_' + uuid4().hex[:12],
                            request.getfixturevalue('pg_server'), source)
    yield db
    if request.param == 'pg':
        db.dropDb(db.get_dbname())
    else:
        db.closeConnection()


def model(db, name, order='DESC'):
    return JsonStructureProducer({'db': db.get_dbname(), 'schemas': [
        {'name': 'alfa', 'tables': [{'name': 'invoice', 'pkey': 'id', 'columns': [
            {'name': 'id', 'dtype': 'I'}, {'name': 'title', 'dtype': 'T'}],
            'indexes': [{'name': name, 'columns': {'title': None, 'id': order}}]}]}
    ]}).get_json_struct()


def migrator(db, structure, **kwargs):
    result = SqlMigrator(db, **kwargs)
    result.ormStructure = deepcopy(structure)
    result.prepareMigrationCommands()
    return result


@pytest.mark.parametrize('name', ['ix_recipe_title_id', 'select', 'MixedCase',
                                  'ix-with-dash', 'ix"quoted', 'ix  spaced'])
def test_name_order_and_rebuild_roundtrip(index_db, name):
    structure = model(index_db, name)
    (key,) = structure['root']['schemas']['alfa']['tables']['invoice']['indexes']
    first = migrator(index_db, structure)
    first.applyChanges()
    inspected = index_db.adapter.reader.get_json_struct(index_db.get_dbname(), schemas=['alfa'])
    index = inspected['root']['schemas']['alfa']['tables']['invoice']['indexes'][key]
    assert index['attributes']['index_name'] == name
    assert index['attributes']['columns'] == {'title': None, 'id': 'DESC'}
    assert migrator(index_db, structure).getChanges() == ''
    # Changing the ordering keeps the structural identity but replaces the index.
    changed = model(index_db, name, order=None)
    rebuild = migrator(index_db, changed)
    assert 'DROP INDEX' in rebuild.getChanges()
    rebuild.applyChanges()
    assert migrator(index_db, changed).getChanges() == ''
    # Explicit names are changed only when requested by the caller.
    renamed = model(index_db, 'new"name', order=None)
    assert migrator(index_db, renamed).getChanges() == ''
    migrator(index_db, renamed, ignore_constraint_name=False).applyChanges()
    assert migrator(index_db, renamed, ignore_constraint_name=False).getChanges() == ''


@pytest.mark.parametrize('ignore_name', [False, True])
def test_name_and_definition_change_together(index_db, ignore_name):
    migrator(index_db, model(index_db, 'old"name')).applyChanges()
    desired = model(index_db, 'new"name', order=None)
    change = migrator(index_db, desired, ignore_constraint_name=ignore_name)
    change.applyChanges()
    assert migrator(index_db, desired, ignore_constraint_name=ignore_name).getChanges() == ''
    inspected = index_db.adapter.reader.get_json_struct(index_db.get_dbname(), schemas=['alfa'])
    indexes = inspected['root']['schemas']['alfa']['tables']['invoice']['indexes']
    assert {index['attributes']['index_name'] for index in indexes.values()} == {
        'old"name' if ignore_name else 'new"name'
    }


def test_structural_name_is_the_fallback(tmp_path):
    db = SqliteDatabase({'dbname': str(tmp_path / 'unused.sqlite')})
    structure = model(db, 'authored')
    index = next(iter(structure['root']['schemas']['alfa']['tables']['invoice']['indexes'].values()))
    del index['attributes']['index_name']
    sql = SqlMigrator(db).createIndexSql(index)
    assert f'INDEX "alfa"."{index["entity_name"]}"' in sql


@pytest.mark.parametrize('descending', ['title', 'id'])
def test_descending_flag_at_each_ordinal(index_db, descending):
    structure = model(index_db, 'ix_order')
    index = next(iter(structure['root']['schemas']['alfa']['tables']['invoice']['indexes'].values()))
    index['attributes']['columns'] = {
        column: 'DESC' if column == descending else None for column in ['title', 'id']
    }
    migrator(index_db, structure).applyChanges()
    inspected = index_db.adapter.reader.get_json_struct(index_db.get_dbname(), schemas=['alfa'])
    recovered = inspected['root']['schemas']['alfa']['tables']['invoice']['indexes'][index['entity_name']]
    assert recovered['attributes']['columns'] == index['attributes']['columns']
    assert migrator(index_db, structure).getChanges() == ''
