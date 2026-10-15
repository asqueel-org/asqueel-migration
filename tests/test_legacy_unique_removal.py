"""GenroPy 600f347ef3, cases 13a–13g: real names and uniqueness convergence."""
from copy import deepcopy
from uuid import uuid4

import pytest

from asqueel_migration import JsonStructureProducer, SqlMigrator

from .support.orm_producer import SrcModel
from .support.pg_database import PgTestDatabase

pytestmark = pytest.mark.postgresql


def prepare(db, structure):
    migration = SqlMigrator(db, structure=structure)
    migration.prepareMigrationCommands()
    return migration


@pytest.fixture
def legacy_db(pg_server):
    source = SrcModel()
    source.package('alfa')
    db = PgTestDatabase('test_unique_' + uuid4().hex[:12], pg_server, source)
    desired = JsonStructureProducer({'db': db.get_dbname(), 'schemas': [
        {'name': 'alfa', 'tables': [{'name': 'legacy_unique', 'pkey': 'id',
         'columns': [{'name': 'id', 'dtype': 'I'}, {'name': 'ref_id', 'dtype': 'T'}],
         'indexes': [{'name': 'plain_ref', 'columns': ['ref_id']}]}]}
    ]}).get_json_struct()
    try:
        prepare(db, desired).applyChanges()
        yield db, desired
    finally:
        db.dropDb(db.get_dbname())


@pytest.mark.parametrize('objects', [('constraint',), ('index',), ('constraint', 'index'),
                                    ('constraint', 'constraint2', 'index')])
@pytest.mark.parametrize('plain_index', [False, True])
def test_remove_every_real_unique_object_and_allow_duplicates(legacy_db, objects, plain_index):
    db, desired = legacy_db
    if not plain_index:
        db.execute('DROP INDEX alfa.plain_ref')
    names = {'constraint': 'legacy_ref_key', 'constraint2': 'second_ref_key',
             'index': 'legacy_ref_idx'}
    for kind in objects:
        name = names[kind]
        sql = (f'CREATE UNIQUE INDEX "{name}" ON alfa.legacy_unique (ref_id)' if kind == 'index'
               else f'ALTER TABLE alfa.legacy_unique ADD CONSTRAINT "{name}" UNIQUE (ref_id)')
        db.execute(sql)
    db.commit()
    # Legacy 13a: an existing unique column is accepted without recreating it.
    kept = deepcopy(desired)
    kept['root']['schemas']['alfa']['tables']['legacy_unique']['columns']['ref_id']['attributes']['unique'] = True
    if not plain_index:
        kept['root']['schemas']['alfa']['tables']['legacy_unique']['indexes'].clear()
    assert prepare(db, kept).getChanges() == ''
    # Legacy 13b/13c: remove all uniqueness, even beside a plain index.
    migration = prepare(db, desired)
    key = ('alfa', 'legacy_unique', 'ref_id')
    assert set(migration.column_unique_objects[key]) == {
        ('index' if kind == 'index' else 'constraint', names[kind]) for kind in objects}
    sql = migration.getChanges()
    for kind in objects:
        expected = (f'DROP INDEX IF EXISTS "alfa"."{names[kind]}"' if kind == 'index'
                    else f'DROP CONSTRAINT IF EXISTS "{names[kind]}"')
        assert expected in sql
    assert 'DROP INDEX IF EXISTS "alfa"."plain_ref"' not in sql
    migration.applyChanges()
    converged = prepare(db, desired)
    assert converged.getChanges() == ''
    assert converged.column_unique_objects.get(key, []) == []
    db.execute("INSERT INTO alfa.legacy_unique (id, ref_id) VALUES (1, 'R1'), (2, 'R1')")
    db.commit()
    assert prepare(db, desired).getChanges() == ''


@pytest.mark.parametrize('definition', ['(ref_id) WHERE ref_id IS NOT NULL',
                                       '(ref_id, lower(ref_id))', '(id, ref_id)'])
def test_partial_expression_and_multicolumn_indexes_are_not_column_uniqueness(legacy_db, definition):
    db, desired = legacy_db
    # Legacy 13e, plus partial/multi-column boundaries of the same rule.
    desired['root']['schemas']['alfa']['tables']['legacy_unique']['indexes'].clear()
    db.execute('DROP INDEX alfa.plain_ref')
    db.execute(f'CREATE UNIQUE INDEX protected_ref ON alfa.legacy_unique {definition}')
    db.commit()
    assert prepare(db, desired).getChanges() == ''


def test_desired_unique_index_converges_with_existing_index(legacy_db):
    db, desired = legacy_db
    # Legacy 13f/13g: a single-column unique index expresses column uniqueness.
    table = desired['root']['schemas']['alfa']['tables']['legacy_unique']
    index = next(iter(table['indexes'].values()))
    index['attributes']['unique'] = True
    db.execute('DROP INDEX alfa.plain_ref')
    db.execute('CREATE UNIQUE INDEX legacy_ref_idx ON alfa.legacy_unique (ref_id)')
    db.commit()
    before = deepcopy(desired)
    assert prepare(db, desired).getChanges() == ''
    assert desired == before


def test_explicit_unique_index_keeps_its_name_and_definition(legacy_db):
    db, desired = legacy_db
    index = next(iter(desired['root']['schemas']['alfa']['tables']['legacy_unique']['indexes'].values()))
    index['attributes']['unique'] = True
    index['attributes']['columns']['ref_id'] = 'DESC'
    before = deepcopy(desired)
    migration = prepare(db, desired)
    assert 'CREATE UNIQUE INDEX "plain_ref"' in migration.getChanges()
    assert '"ref_id" DESC' in migration.getChanges()
    migration.applyChanges()
    assert prepare(db, desired).getChanges() == ''
    assert desired == before
