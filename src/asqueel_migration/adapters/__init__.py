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

__all__ = [
    "MssqlAdapter",
    "MssqlDatabase",
    "MysqlAdapter",
    "MysqlDatabase",
    "PgAdapter",
    "PgDatabase",
    "SqliteAdapter",
    "SqliteDatabase",
]
