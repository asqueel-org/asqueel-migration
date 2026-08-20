"""Security boundary of the local-only development editor."""

import asyncio
import json
from unittest.mock import Mock, patch

import pytest

pytest.importorskip('genro_asgi', minversion='0.33')

from genro_asgi import AsgiServer  # noqa: E402

from genro_sqlmigration.app import EditorApp  # noqa: E402
from genro_sqlmigration.editor_service import migrate_from_xml  # noqa: E402


def _request(
    server,
    path,
    *,
    method='GET',
    client='127.0.0.1',
    query=b'',
    payload=None,
):
    """Drive one HTTP request through the real ASGI stack."""
    body = json.dumps(payload).encode() if payload is not None else b''
    headers = [(b'content-type', b'application/json')] if payload is not None else []

    async def run():
        scope = {
            'type': 'http',
            'method': method,
            'path': path,
            'query_string': query,
            'headers': headers,
            'client': (client, 12345),
        }
        sent = []

        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def send(message):
            sent.append(message)

        await server(scope, receive, send)
        status = next(
            message['status']
            for message in sent
            if message['type'] == 'http.response.start'
        )
        response_body = b''.join(
            message.get('body', b'')
            for message in sent
            if message['type'] == 'http.response.body'
        )
        return status, response_body

    return asyncio.run(run())


@pytest.fixture
def editor_server():
    return AsgiServer(applications=[EditorApp(mount='')])


def test_non_loopback_client_is_rejected(editor_server):
    status, body = _request(
        editor_server, '/apply', method='POST', client='192.0.2.10'
    )
    assert status == 403
    assert b'localhost' in body


def test_editor_endpoints_require_post_and_json_body(editor_server):
    get_status, _ = _request(editor_server, '/apply')
    query_status, query_body = _request(
        editor_server,
        '/migrate',
        method='POST',
        query=b'password=must-not-enter-a-url',
    )

    assert get_status == 405
    assert query_status == 400
    assert b'JSON request body' in query_body
    assert b'must-not-enter-a-url' not in query_body

    form_status, _ = _request(
        editor_server,
        '/apply',
        method='POST',
        payload=None,
    )
    assert form_status == 400


def test_local_json_request_does_not_echo_password(editor_server, monkeypatch):
    captured = {}

    def fake_migrate(params, xml, apply, schemas):
        captured.update(params=params, xml=xml, apply=apply, schemas=schemas)
        return 'CREATE TABLE demo (id integer);'

    monkeypatch.setattr('genro_sqlmigration.app.migrate_from_xml', fake_migrate)
    password = 'local-secret-value'
    status, body = _request(
        editor_server,
        '/migrate',
        method='POST',
        payload={
            'xml': '<db/>',
            'host': 'localhost',
            'user': 'developer',
            'password': password,
            'dbname': 'demo',
            'schemas': 'public',
        },
    )

    assert status == 200
    assert password.encode() not in body
    assert captured['params']['password'] == password
    assert captured['apply'] is False
    assert captured['schemas'] == ['public']


def test_password_is_redacted_from_operation_errors(editor_server, monkeypatch):
    password = 'never-reflect-this-secret'

    def fail(params, xml, apply, schemas):
        raise RuntimeError(f'connection failed with password {params["password"]}')

    monkeypatch.setattr('genro_sqlmigration.app.migrate_from_xml', fail)
    status, body = _request(
        editor_server,
        '/migrate',
        method='POST',
        payload={'xml': '<db/>', 'password': password},
    )

    assert status == 500
    assert password.encode() not in body


def test_openapi_declares_body_only_post_operations(editor_server):
    status, body = _request(editor_server, '/_meta/schema_json')
    schema = json.loads(body)

    assert status == 200
    for path in ('/introspect', '/migrate', '/apply'):
        assert set(schema['paths'][path]) == {'post'}
        operation = schema['paths'][path]['post']
        assert 'requestBody' in operation
        assert 'parameters' not in operation


def test_apply_is_not_exposed_as_an_mcp_tool(editor_server):
    status, body = _request(
        editor_server,
        '/mcp',
        method='POST',
        payload={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}},
    )
    tools = json.loads(body)['result']['tools']
    names = {tool['name'] for tool in tools}

    assert status == 200
    assert names == {'introspect', 'migrate'}


def test_editor_service_keeps_database_only_objects():
    db = object()
    migrator = Mock()
    with (
        patch('genro_sqlmigration.editor_service.PgDatabase', return_value=db),
        patch(
            'genro_sqlmigration.editor_service.SqlMigrator', return_value=migrator
        ) as migrator_class,
        patch('genro_sqlmigration.editor_service.XmlStructureProducer') as producer,
        patch('genro_sqlmigration.editor_service.StructureValidator') as validator,
    ):
        producer.return_value.get_json_struct.return_value = {'root': {}}
        validator.return_value.validate.return_value = {'root': {}}
        migrator.getChanges.return_value = ''

        migrate_from_xml({'dbname': 'demo'}, '<db/>', apply=False)

    migrator_class.assert_called_once_with(db, removeDisabled=True)
