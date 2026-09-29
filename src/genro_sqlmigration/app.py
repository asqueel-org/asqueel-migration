# Copyright (c) 2025 Softwell Srl, Milano, Italy
# SPDX-License-Identifier: Apache-2.0

"""
app.py - the DB <-> XML editor as a web/MCP application
=======================================================

Exposes the transport-agnostic editor operations from
:mod:`editor_service` as an HTTP + MCP application, built on kajenn's
``McpOpenApiApplication`` ("one router, two faces": the same routes are
reachable as REST endpoints and as MCP tools).

kajenn is an optional dependency: install the ``app`` extra
(``pip install genro-sqlmigration[app,postgresql]``). The import lives in
this module only, so the core package stays installable with just
``dictdiffer`` and its driver. Kajenn is the successor of genro-asgi;
no legacy ``gnr.*`` imports are needed.

Launch with the kajenn CLI (no server code of our own)::

    kajenn serve application=src/genro_sqlmigration/app.py:EditorApp \
        --host 127.0.0.1

Endpoints then live at ``/introspect``, ``/migrate``, ``/apply``; the MCP
JSON-RPC face is at ``/mcp`` and Swagger UI at ``/_meta/docs``.

This is a **local development tool**, not a remotely deployable service. The
application rejects non-loopback clients even if the server is accidentally
bound to a public interface. REST operations accept POST JSON bodies only;
query strings are rejected so database passwords cannot enter URLs or access
logs.

Safety: ``introspect`` and ``migrate`` (dry-run: it returns the SQL diff,
never executes) are exposed as MCP tools; ``apply`` — which runs DDL on a
live database — is deliberately REST-only, so an agent cannot apply a
destructive migration through the MCP face.
"""

from collections.abc import Callable
from ipaddress import ip_address
from typing import TypeVar

from genro_routes import route
from kajenn import (
    HTTPBadRequest,
    HTTPException,
    HTTPForbidden,
    McpOpenApiApplication,
)

# Absolute import: the kajenn CLI can load this module as a standalone
# file (application=.../app.py:EditorApp), where a relative import has no
# parent package. The package is installed, so the absolute form works both
# as a file target and as a module target.
from genro_sqlmigration.editor_service import introspect_to_xml, migrate_from_xml
from genro_sqlmigration.exceptions import SqlMigrationError

_EDITOR_ENDPOINTS = {'introspect', 'migrate', 'apply'}
_Result = TypeVar('_Result')


def _is_loopback_client(scope):
    """Return True only for an ASGI peer on the local loopback interface."""
    client = scope.get('client')
    if not client:
        return False
    host = str(client[0]).split('%', 1)[0]
    if host.lower() == 'localhost':
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _request_content_type(scope):
    """Return the normalized media type from raw ASGI headers."""
    for name, value in scope.get('headers') or []:
        if name.lower() == b'content-type':
            return value.decode('latin-1').partition(';')[0].strip().lower()
    return ''


def _without_secret_leak(
    operation: Callable[[], _Result], password: object | None
) -> _Result:
    """Run a web-boundary operation without reflecting its password on error."""
    try:
        return operation()
    except Exception as error:
        message = str(error)
        if password:
            message = message.replace(str(password), '[REDACTED]')
        raise SqlMigrationError(message) from None


def _connection_params(host, port, user, password, dbname):
    """Assemble the psycopg connection dict, dropping unset values."""
    params = {"host": host, "port": port, "user": user,
              "password": password, "dbname": dbname}
    return {k: v for k, v in params.items() if v is not None}


def _schema_list(schemas):
    """Turn a comma-joined schema string into a list (None if empty)."""
    return [s.strip() for s in schemas.split(",") if s.strip()] if schemas else None


class EditorApp(McpOpenApiApplication):
    """DB <-> XML editor restricted to local development clients."""

    mount = ""

    openapi_info = {
        "title": "genro-sqlmigration editor",
        "version": "1.0.0",
        "description": "Introspect a database to SQL-model XML and migrate "
                       "a database to match an edited XML.",
    }

    async def __call__(self, scope, receive, send):
        """Reject non-local peers and unsafe REST parameter transport."""
        if scope.get('type') == 'http':
            if not _is_loopback_client(scope):
                raise HTTPForbidden(
                    'The SQL migration editor is restricted to localhost'
                )
            path_segment = str(scope.get('path', '/')).lstrip('/').partition('/')[0]
            if path_segment in _EDITOR_ENDPOINTS:
                if str(scope.get('method', 'GET')).upper() != 'POST':
                    raise HTTPException(
                        405, 'Method Not Allowed', headers=[(b'allow', b'POST')]
                    )
                if scope.get('query_string'):
                    raise HTTPBadRequest(
                        'Editor parameters must be sent in the JSON request body'
                    )
                if _request_content_type(scope) != 'application/json':
                    raise HTTPBadRequest(
                        'Editor endpoints require an application/json request body'
                    )
        await super().__call__(scope, receive, send)

    @route(
        media_type="application/xml",
        channel_channels="mcp,rest",
        openapi_method="post",
    )
    def introspect(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        dbname: str | None = None,
        schemas: str | None = None,
    ) -> str:
        """Read a live database's structure and return it as SQL-model XML.

        Connection is given field by field (host, port, user, password,
        dbname). ``schemas`` optionally limits introspection to a
        comma-separated list of schema names.
        """
        return _without_secret_leak(
            lambda: introspect_to_xml(
                _connection_params(host, port, user, password, dbname),
                schemas=_schema_list(schemas),
            ),
            password,
        )

    @route(
        media_type="application/json",
        channel_channels="mcp,rest",
        openapi_method="post",
    )
    def migrate(
        self,
        xml: str = "",
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        dbname: str | None = None,
        schemas: str | None = None,
    ) -> dict:
        """Dry-run: return the SQL that would align the database to the XML.

        Diffs the edited SQL-model ``xml`` against the live database and
        returns the migration SQL without executing it (empty string means
        the database already matches). Use ``apply`` to execute it.
        """
        sql = _without_secret_leak(
            lambda: migrate_from_xml(
                _connection_params(host, port, user, password, dbname),
                xml, apply=False, schemas=_schema_list(schemas),
            ),
            password,
        )
        return {"sql": sql}

    @route(
        media_type="application/json",
        channel_channels="rest",
        openapi_method="post",
    )
    def apply(
        self,
        xml: str = "",
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        dbname: str | None = None,
        schemas: str | None = None,
    ) -> dict:
        """REST-only: execute the migration that aligns the database to the XML.

        Not an MCP tool by design — it runs DDL on a live database, so it
        stays a deliberate REST call rather than an agent-callable tool.
        """
        sql = _without_secret_leak(
            lambda: migrate_from_xml(
                _connection_params(host, port, user, password, dbname),
                xml, apply=True, schemas=_schema_list(schemas),
            ),
            password,
        )
        return {"sql": sql, "applied": True}
