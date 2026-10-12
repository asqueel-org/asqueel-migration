"""XML helpers own their connections, including on unsuccessful operations."""

from unittest.mock import Mock

import pytest

from asqueel_migration import JsonStructureProducer, editor_service


@pytest.mark.parametrize('failure', [False, True])
def test_introspection_closes_owned_database(monkeypatch, failure):
    db = Mock()
    db.adapter.reader.get_json_struct.return_value = JsonStructureProducer({
        'db': 'demo', 'schemas': [],
    }).get_json_struct()
    monkeypatch.setattr(editor_service, 'PgDatabase', Mock(return_value=db))
    if failure:
        db.adapter.reader.get_json_struct.side_effect = RuntimeError('read failed')
        with pytest.raises(RuntimeError, match='read failed'):
            editor_service.introspect_to_xml({'dbname': 'demo'})
    else:
        assert 'demo' in editor_service.introspect_to_xml({'dbname': 'demo'})
    db.closeConnection.assert_called_once_with()


@pytest.mark.parametrize('outcome', ['plan', 'apply', 'parse_error', 'prepare_error', 'execute_error'])
def test_xml_migration_closes_owned_database(monkeypatch, outcome):
    db = Mock()
    migrator = Mock()
    migrator.getChanges.return_value = 'CREATE TABLE example (id integer);'
    monkeypatch.setattr(editor_service, 'PgDatabase', Mock(return_value=db))
    monkeypatch.setattr(editor_service, 'SqlMigrator', Mock(return_value=migrator))
    xml = '<db xmlns="urn:genro:sql-model:1.0" name="demo"/>'
    apply = outcome in {'apply', 'execute_error'}
    if outcome == 'parse_error':
        from xml.etree.ElementTree import ParseError

        with pytest.raises(ParseError):
            editor_service.migrate_from_xml({'dbname': 'demo'}, '<db')
        migrator.prepareMigrationCommands.assert_not_called()
    elif outcome.endswith('_error'):
        method = migrator.applyChanges if apply else migrator.prepareMigrationCommands
        method.side_effect = RuntimeError('migration failed')
        with pytest.raises(RuntimeError, match='migration failed'):
            editor_service.migrate_from_xml({'dbname': 'demo'}, xml, apply=apply)
    else:
        result = editor_service.migrate_from_xml({'dbname': 'demo'}, xml, apply=apply)
        assert result == migrator.getChanges.return_value
        assert migrator.applyChanges.call_count == int(apply)
    db.closeConnection.assert_called_once_with()
