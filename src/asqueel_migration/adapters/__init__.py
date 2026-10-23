# Copyright (c) 2025 Softwell Srl, Milano, Italy
# SPDX-License-Identifier: Apache-2.0

"""
adapters - Concrete Database/BaseAdapter pairs per dialect
===========================================================

Each dialect contributes one module: PostgreSQL, SQLite, MySQL,
Microsoft SQL Server.
"""

from asqueel_migration.adapters.mssql_adapter import MssqlAdapter, MssqlDatabase
from asqueel_migration.adapters.mysql_adapter import MysqlAdapter, MysqlDatabase
from asqueel_migration.adapters.pg_adapter import PgAdapter, PgDatabase
from asqueel_migration.adapters.sqlite_adapter import SqliteAdapter, SqliteDatabase
from asqueel_migration.exceptions import SqlMigrationError

# GenroPy implementation names (``gnr.sql.adapters.gnr<name>``) and their facades.
DATABASE_CLASSES = {
    'mssql': MssqlDatabase,
    'mysql': MysqlDatabase,
    'postgres': PgDatabase,
    'postgres3': PgDatabase,
    'sqlite': SqliteDatabase,
}


def database_for(implementation, connection_params, *, application_schemas=None,
                 read_only_schemas=None, tenant_schemas=None, connection=None):
    """Return the database facade of a GenroPy implementation name.

    ``'name:module'`` names the implementation before the colon, as legacy.
    ``connection`` is a caller's sqlite3 connection (see
    :class:`SqliteDatabase`); the other facades open their own.
    """
    name = implementation.partition(':')[0]
    if name not in DATABASE_CLASSES:
        raise SqlMigrationError(f'Unsupported migration backend: {implementation}')
    kwargs = {}
    if connection is not None:
        if name != 'sqlite':
            raise SqlMigrationError(f'Only SQLite migrates through a caller connection, not {implementation}')
        kwargs['connection'] = connection
    return DATABASE_CLASSES[name](connection_params, application_schemas=application_schemas,
                                  read_only_schemas=read_only_schemas,
                                  tenant_schemas=tenant_schemas, **kwargs)


__all__ = [
    "DATABASE_CLASSES",
    "MssqlAdapter",
    "MssqlDatabase",
    "MysqlAdapter",
    "MysqlDatabase",
    "PgAdapter",
    "PgDatabase",
    "SqliteAdapter",
    "SqliteDatabase",
    "database_for",
]
