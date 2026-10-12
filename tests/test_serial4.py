"""PostgreSQL serial widths, sequence preservation and legacy integer adoption."""

import copy
import json
from importlib.resources import files
from uuid import uuid4
from xml.etree import ElementTree

import pytest

from asqueel_migration import (
    JsonStructureProducer,
    MssqlDatabase,
    MysqlDatabase,
    PgDatabase,
    SqliteDatabase,
    SqlMigrator,
    StructureValidator,
    XmlStructureProducer,
    apply_migration,
    plan_migration,
)
from asqueel_migration.exceptions import SqlMigrationError, SqlValidationError
from asqueel_migration.structures import DTYPE_CODES


def desired(dtype='serial4'):
    return JsonStructureProducer({'db': 'logical', 'schemas': [{
        'name': 'app', 'tables': [{'name': 'items', 'pkey': 'id', 'columns': [
            {'name': 'id', 'dtype': dtype},
        ]}],
    }]}).get_json_struct()


def test_serial4_json_xml_and_packaged_contracts_agree():
    source = desired()
    xml = '<db name="logical"><schema name="app"><table name="items" pkey="id"><column name="id" dtype="serial4"/></table></schema></db>'
    assert XmlStructureProducer(xml).get_json_struct() == source
    assert StructureValidator().validate(source)['root'] == source['root']
    package = files('asqueel_migration')
    schema = json.loads(package.joinpath('schemas/structure-1.0.json').read_text())
    assert set(schema['$defs']['dtype']['enum']) == set(DTYPE_CODES)
    xsd = ElementTree.fromstring(package.joinpath('schemas/sql_model-1.0.xsd').read_text())
    ns = {'xs': 'http://www.w3.org/2001/XMLSchema'}
    values = {node.get('value') for node in xsd.findall("xs:simpleType[@name='dtype']/xs:restriction/xs:enumeration", ns)}
    assert values == set(DTYPE_CODES)


@pytest.mark.parametrize('attribute,value', [('size', '12'), ('sqldefault', '42')])
def test_serial4_cannot_override_its_width_or_sequence_default(attribute, value):
    source = desired()
    source['root']['schemas']['app']['tables']['items']['columns']['id']['attributes'][attribute] = value
    with pytest.raises(SqlValidationError, match='serial4 defines its own'):
        StructureValidator().validate(source)


@pytest.mark.parametrize('database_class', [SqliteDatabase, MysqlDatabase, MssqlDatabase])
def test_serial4_unsupported_dialects_fail_before_connection(database_class, tmp_path, monkeypatch):
    db = database_class({'dbname': str(tmp_path / 'absent')}, application_schemas=['app'])
    def unexpected_connection(*args, **kwargs):
        pytest.fail('unsupported dtype must fail before opening a database')
    monkeypatch.setattr(db.adapter, 'connect', unexpected_connection)
    with pytest.raises(SqlMigrationError, match='serial4 is supported only by PostgreSQL'):
        plan_migration(db, desired())


@pytest.fixture
def pg_database(pg_server):
    import psycopg
    from psycopg import sql
    name = 'serial4_' + uuid4().hex[:12]
    db = PgDatabase(dict(pg_server, dbname=name), application_schemas=['app'])
    yield db
    db.closeConnection()
    with psycopg.connect(**dict(pg_server, dbname='postgres'), autocommit=True) as admin:
        admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(name)))


def create_existing(db):
    db.adapter.execute(db.adapter.createDbSql(db.get_dbname()), manager=True)
    db.adapter.execute('CREATE SCHEMA app')


def apply(db, source):
    plan = plan_migration(db, source)
    assert not plan['skipped']
    result = apply_migration(db, source, expected_plan=plan['plan_id'])
    assert result['verified'], result['remaining']
    return plan


@pytest.mark.postgresql
@pytest.mark.parametrize('dtype,sql_type', [('serial4', 'integer'), ('serial', 'bigint')])
@pytest.mark.parametrize('existing_database', [False, True])
def test_fresh_serial_width_and_generated_keys(pg_database, dtype, sql_type, existing_database):
    db = pg_database
    if existing_database:
        create_existing(db)
    source = desired(dtype)
    original = copy.deepcopy(source)
    plan = apply(db, source)
    assert ('serial4' if dtype == 'serial4' else 'serial8') in plan['sql']
    assert db.execute("SELECT data_type FROM information_schema.columns WHERE table_schema='app' AND table_name='items' AND column_name='id'").fetchone() == (sql_type,)
    assert db.execute('INSERT INTO app.items DEFAULT VALUES RETURNING id').fetchone() == (1,)
    db.commit()
    db.closeConnection()
    assert db.execute('INSERT INTO app.items DEFAULT VALUES RETURNING id').fetchone() == (2,)
    db.commit()
    assert plan_migration(db, source)['empty']
    assert source == original
    struct = db.adapter.reader.get_json_struct(db.get_dbname(), schemas=['app'])
    assert struct['root']['schemas']['app']['tables']['items']['columns']['id']['attributes']['dtype'] == dtype


def sequence_snapshot(db):
    seq = db.execute("SELECT pg_get_serial_sequence('app.items','id')").fetchone()[0]
    return (
        seq,
        db.execute("SELECT attnum,atttypid,attnotnull FROM pg_attribute WHERE attrelid='app.items'::regclass AND attname='id'").fetchall(),
        db.execute("SELECT pg_get_expr(adbin,adrelid) FROM pg_attrdef WHERE adrelid='app.items'::regclass").fetchall(),
        db.execute("SELECT oid,conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid IN ('app.items'::regclass,'app.children'::regclass) ORDER BY oid").fetchall(),
        db.execute('SELECT seqrelid,seqtypid,seqstart,seqincrement,seqmax,seqmin,seqcache,seqcycle FROM pg_sequence').fetchall(),
        db.execute('SELECT last_value,is_called FROM app.custom_keys').fetchall(),
        db.execute('SELECT * FROM app.items ORDER BY id').fetchall(),
        db.execute('SELECT * FROM app.children ORDER BY parent_id').fetchall(),
    )


@pytest.mark.postgresql
@pytest.mark.parametrize('dtype', ['serial4', 'I'])
@pytest.mark.parametrize('populated', [False, True])
def test_adopt_existing_serial4_preserves_sequence_data_and_dependencies(pg_database, dtype, populated):
    db = pg_database
    create_existing(db)
    db.adapter.execute('''
        CREATE TABLE app.items (id SERIAL PRIMARY KEY);
        ALTER SEQUENCE app.items_id_seq RENAME TO custom_keys;
        ALTER SEQUENCE app.custom_keys INCREMENT BY 3 START WITH 7 RESTART WITH 7 MINVALUE 7 MAXVALUE 2000000000 CACHE 1;
        CREATE TABLE app.children (parent_id integer REFERENCES app.items(id));
    ''')
    if populated:
        db.execute('INSERT INTO app.items VALUES (42)')
        db.execute('INSERT INTO app.children VALUES (42)')
    db.execute("SELECT setval('app.custom_keys', 100, false)")
    db.commit()
    before = sequence_snapshot(db)
    assert apply(db, desired(dtype))['empty']
    assert sequence_snapshot(db) == before
    db.closeConnection()
    assert db.execute('INSERT INTO app.items DEFAULT VALUES RETURNING id').fetchone() == (100,)
    assert db.execute('INSERT INTO app.items DEFAULT VALUES RETURNING id').fetchone() == (103,)
    db.commit()
    assert plan_migration(db, desired(dtype))['empty']


@pytest.mark.postgresql
@pytest.mark.parametrize('dtype', ['serial4', 'serial'])
@pytest.mark.parametrize('populated', [False, True])
@pytest.mark.parametrize('mode', [{}, {'force': True}, {'backup': True}])
def test_serial_width_conversion_is_never_implicit(pg_database, dtype, populated, mode):
    db = pg_database
    apply(db, desired(dtype))
    if populated:
        db.execute('INSERT INTO app.items DEFAULT VALUES')
        db.commit()
    target = 'serial' if dtype == 'serial4' else 'serial4'
    migrator = SqlMigrator(db, structure=desired(target), **mode)
    with pytest.raises(SqlMigrationError, match='explicit migration'):
        migrator.prepareMigrationCommands()
    assert plan_migration(db, desired(dtype))['empty']


@pytest.mark.postgresql
def test_plain_integer_is_not_mistaken_for_serial4(pg_database):
    db = pg_database
    apply(db, desired('I'))
    db.execute('INSERT INTO app.items VALUES (42)')
    db.commit()
    with pytest.raises(SqlMigrationError, match='explicit migration'):
        plan_migration(db, desired())
    assert db.execute("SELECT pg_get_serial_sequence('app.items','id')").fetchone() == (None,)
    assert plan_migration(db, desired('I'))['empty']
