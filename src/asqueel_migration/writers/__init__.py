# Copyright (c) 2025 Softwell Srl, Milano, Italy
# SPDX-License-Identifier: Apache-2.0

"""
writers - SQL generation modules
=================================

Writers generate SQL specific to each database engine: column
definitions, constraints, indexes, foreign keys and ALTER TABLE
commands.

- :class:`PgWriter`: PostgreSQL
- :class:`SqliteWriter`: SQLite
- :class:`MysqlWriter`: MySQL
- :class:`MssqlWriter`: Microsoft SQL Server (T-SQL)

All writers inherit from :class:`BaseWriter`.
"""

from asqueel_migration.writers.base_writer import BaseWriter
from asqueel_migration.writers.mssql_writer import MssqlWriter
from asqueel_migration.writers.mysql_writer import MysqlWriter
from asqueel_migration.writers.pg_writer import PgWriter
from asqueel_migration.writers.sqlite_writer import SqliteWriter

__all__ = [
    "BaseWriter",
    "MssqlWriter",
    "MysqlWriter",
    "PgWriter",
    "SqliteWriter",
]
