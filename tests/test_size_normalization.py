"""Public producers normalize legacy varchar sizes before schema comparison."""

from copy import deepcopy
from uuid import uuid4
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

from asqueel_migration import JsonStructureProducer, SqlMigrator, XmlStructureProducer

from .support.orm_producer import SrcModel
from .support.pg_database import PgTestDatabase


def produce(format_name, name, pkey, columns):
    model = {'db': name, 'schemas': [{'name': 'alfa', 'tables': [
        {'name': 'example', 'pkey': pkey, 'columns': columns}]}]}
    if format_name == 'json':
        before = deepcopy(model)
        result = JsonStructureProducer(model).get_json_struct()
        assert model == before
        return result
    root = Element('db', name=name)
    schema = SubElement(root, 'schema', name='alfa')
    table = SubElement(schema, 'table', name='example', pkey=pkey)
    for column in columns:
        SubElement(table, 'column', **column)
    return XmlStructureProducer(tostring(root, encoding='unicode')).get_json_struct()


@pytest.mark.parametrize('dtype', ['A', None])
@pytest.mark.parametrize('size', [':80', '0:80', '5:80'])
def test_json_xml_varchar_size_equivalence(dtype, size):
    column = {'name': 'title', 'size': size}
    if dtype:
        column['dtype'] = dtype
    json_result = produce('json', 'test', '', [column])
    assert produce('xml', 'test', '', [column]) == json_result
    attrs = json_result['root']['schemas']['alfa']['tables']['example']['columns']['title']['attributes']
    assert attrs['size'] == '0:80'
    assert column['size'] == size


@pytest.mark.parametrize('dtype,size', [('C', '10'), ('N', '12,2'), ('T', None)])
def test_non_varchar_sizes_are_preserved(dtype, size):
    column = {'name': 'value', 'dtype': dtype}
    if size is not None:
        column['size'] = size
    result = produce('json', 'test', '', [column])
    assert produce('xml', 'test', '', [column]) == result
    attrs = result['root']['schemas']['alfa']['tables']['example']['columns']['value']['attributes']
    assert attrs.get('size') == size


@pytest.mark.postgresql
@pytest.mark.parametrize('format_name', ['json', 'xml'])
@pytest.mark.parametrize('minimum', ['', '0', '5'])
@pytest.mark.parametrize('is_primary_key', [False, True])
def test_varchar_widening_converges_with_existing_data(pg_server, format_name, minimum, is_primary_key):
    model = SrcModel()
    model.package('alfa', sqlschema='alfa')
    db = PgTestDatabase('test_sizes_' + uuid4().hex[:12], pg_server, model)
    start, end = (80, 306) if is_primary_key else (40, 255)
    key = 'value' if is_primary_key else 'id'
    columns = [{'name': 'value', 'dtype': 'A', 'size': f'{minimum}:{start}'}]
    if not is_primary_key:
        columns.insert(0, {'name': 'id', 'dtype': 'I'})

    def prepare():
        migrator = SqlMigrator(db)
        migrator.ormStructure = produce(format_name, db.get_dbname(), key, columns)
        migrator.prepareMigrationCommands()
        return migrator

    try:
        prepare().applyChanges()
        if is_primary_key:
            db.adapter.execute('INSERT INTO "alfa"."example" (value) VALUES (\'kept\');')
        else:
            db.adapter.execute('INSERT INTO "alfa"."example" (id, value) VALUES (1, \'kept\');')
        assert prepare().getChanges() == ''
        columns[-1]['size'] = f'{minimum}:{end}'
        migrator = prepare()
        assert migrator.getChanges() == (
            f'ALTER TABLE "alfa"."example"\nALTER COLUMN "value" TYPE character varying({end});')
        migrator.applyChanges()
        assert prepare().getChanges() == ''
        with db.adapter.connect() as connection:
            assert connection.execute('SELECT value FROM "alfa"."example"').fetchall() == [('kept',)]
    finally:
        db.dropDb(db.get_dbname())
