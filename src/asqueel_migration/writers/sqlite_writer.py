# Copyright (c) 2025 Softwell Srl, Milano, Italy
# SPDX-License-Identifier: Apache-2.0

"""
sqlite_writer.py - SQL generator for SQLite
============================================

Generates SQL fragments and commands specific to SQLite.

Declared-type fidelity trick
----------------------------

SQLite stores the *declared* type text verbatim and ``PRAGMA table_info``
returns it unchanged. This writer emits the GenroPy legacy type names
(``character varying(N)``, ``character(N)``, ``timestamp``, ...) that the
:class:`SqliteReader` maps back exactly, so a round-trip through the live
database is diff-stable.

Capabilities
------------

SQLite supports partial indexes, inline same-schema foreign keys and UNIQUE
constraints on new tables. CHECK, comments, extensions and event triggers are
stripped from the desired structure before the diff; ``alter_column_type``,
``drop_constraint`` and ``add_constraint`` are gated by the shared command
builder. The unsupported DDL methods below are therefore never reached
through the gates/strips and raise an explicit error if called directly.
"""

from asqueel_migration.exceptions import SqlMigrationError
from asqueel_migration.writers.base_writer import BaseWriter

# Normalized dtype -> declared SQL type text. The names follow the GenroPy
# legacy SQLite adapter (gnrsqlite ``revTypesDict``).
# 'serial' collapses to 'integer': a single-column integer PK is a rowid
# alias in SQLite, so autoincrement semantics are implicit.
REV_TYPES_DICT = {
    'A': 'character varying',
    'B': 'boolean',
    'C': 'character',
    'D': 'date',
    'DH': 'timestamp',
    'DHZ': 'timestamp with time zone',
    'H': 'time',
    'I': 'integer',
    'L': 'bigint',
    'N': 'numeric',
    'O': 'blob',
    'R': 'real',
    'T': 'text',
    'X': 'blob',
    'jsonb': 'jsonb',
    'serial': 'integer',
}


class SqliteWriter(BaseWriter):
    """SQL generator for SQLite.

    Emits ANSI double-quoted identifiers and the GenroPy legacy declared
    types (see module docstring). No type conversions are supported.
    """

    TYPE_CONVERSIONS: dict[tuple[str, str], str | bool | None] = {}

    # Represent FKs and UNIQUE, but gate ALTER ADD/DROP separately.
    CAPABILITIES = frozenset({
        'index_where', 'foreign_keys', 'inline_foreign_keys', 'unique_constraints',
        'fk_deferrable',
    })

    def column_sql_type(self, dtype, size=None):
        """Return the declared SQLite type for a dtype and size.

        Args:
            dtype: Normalized dtype code ('T', 'I', 'N', 'C', ...).
            size: Column size ('0:N' for varchar, 'P,S' for numeric, ...).

        Returns:
            str: Declared type text (e.g. ``character varying(100)``, ``numeric(10,2)``).
        """
        if dtype != 'N' and size:
            if ':' in size:
                size = size.split(':')[1]
                dtype = 'A'
            else:
                dtype = 'C'
        if size:
            return f'{REV_TYPES_DICT[dtype]}({size})'
        return REV_TYPES_DICT[dtype]

    def column_sql_definition(self, column_name, dtype, size=None,
                              notnull=False, default=None,
                              extra_sql=None, generated_expression=None):
        """Generate the full SQL definition of a SQLite column.

        Args:
            column_name: Column name.
            dtype: Normalized dtype code.
            size: Column size.
            notnull: If truthy, appends NOT NULL.
            default: SQL default value.
            extra_sql: Extra SQL appended verbatim.
            generated_expression: Expression for a generated column.

        Returns:
            str: Column definition (e.g. ``"name" character varying(100) NOT NULL``).
        """
        sql_type = self.column_sql_type(dtype, size)
        parts = [f'{self.quote_identifier(column_name)} {sql_type}']
        if generated_expression:
            parts.append(f'GENERATED ALWAYS AS ({generated_expression}) STORED')
        else:
            if default:
                parts.append(f'DEFAULT {default}')
            if notnull:
                parts.append('NOT NULL')
        if extra_sql:
            parts.append(extra_sql)
        return ' '.join(parts)

    def table_fullname(self, schema_name, table_name):
        """Return the quoted qualified table name (``"schema"."table"``)."""
        return f'{self.quote_identifier(schema_name)}.{self.quote_identifier(table_name)}'

    def alter_table_commands(self, schema_name, table_name, column_fragments):
        """Emit one ALTER TABLE per fragment (SQLite allows one action each)."""
        full_table = self.table_fullname(schema_name, table_name)
        return [
            f'ALTER TABLE {full_table}\n{fragment};'
            for fragment in column_fragments
        ]

    def constraint_sql(self, constraint_name, constraint_type, columns=None,
                       check_clause=None):
        """Generate an inline constraint definition (UNIQUE or CHECK).

        Used inline by CREATE TABLE (``added_table``); ANSI-quoted to match
        the PostgreSQL writer's shape.
        """
        if constraint_type == "UNIQUE":
            columns_str = ', '.join(self.quote_identifier(col) for col in columns)
            return f'CONSTRAINT {self.quote_identifier(constraint_name)} UNIQUE ({columns_str})'
        elif constraint_type == "CHECK":
            return f'CONSTRAINT {self.quote_identifier(constraint_name)} CHECK ({check_clause})'
        raise ValueError(f"Unsupported constraint type: {constraint_type}")

    def create_index_sql(self, schema_name, table_name, columns,
                         index_name=None, unique=False, method=None,
                         with_options=None, tablespace=None, where=None):
        """Generate CREATE [UNIQUE] INDEX for SQLite.

        The index name lives in the schema namespace, so the working form
        with ATTACHed schemas is ``CREATE INDEX "schema"."name" ON "table"
        (...)``. An optional partial ``WHERE`` clause is appended.

        Args:
            schema_name: Schema name (the ATTACHed database alias).
            table_name: Table name.
            columns: Dict {column: sort_order} or list of columns.
            index_name: Index name.
            unique: If True, UNIQUE index.
            method/with_options/tablespace: Ignored (unsupported by SQLite).
            where: Partial-index condition.

        Returns:
            str: CREATE INDEX command.
        """
        q = self.quote_identifier
        if isinstance(columns, dict):
            column_defs = []
            for column, order in columns.items():
                if order:
                    column_defs.append(f'{q(column)} {order}')
                else:
                    column_defs.append(q(column))
            column_list = ", ".join(column_defs)
        else:
            column_list = ", ".join(q(col) for col in columns)
        where_clause = f"WHERE {where}" if where else ""
        unique_clause = ' UNIQUE ' if unique else " "
        sql = (
            f'CREATE{unique_clause}INDEX {q(schema_name)}.{q(index_name)} '
            f'ON {q(table_name)} ({column_list}) {where_clause}'
        )
        return sql.rstrip() + ';'

    # -- Unsupported DDL: reached only if called directly (never via gates) --

    def _unsupported(self, operation):
        raise SqlMigrationError(f'{operation} is not supported by SQLite')

    def create_db_sql(self, dbname, encoding='UNICODE'):
        self._unsupported('create_db_sql')

    def create_schema_sql(self, schema_name):
        self._unsupported('create_schema_sql')

    def alter_column_sql(self, column_name, new_sql_type):
        self._unsupported('alter_column_sql')

    def alter_column_with_conversion_sql(self, column_name, new_sql_type,
                                         conversion_expression):
        self._unsupported('alter_column_with_conversion_sql')

    def add_not_null_sql(self, column_name):
        self._unsupported('add_not_null_sql')

    def drop_not_null_sql(self, column_name):
        self._unsupported('drop_not_null_sql')

    def drop_constraint_sql(self, constraint_name):
        self._unsupported('drop_constraint_sql')

    def drop_table_pkey_sql(self, schema_name, table_name):
        self._unsupported('drop_table_pkey_sql')

    def add_table_pkey_sql(self, schema_name, table_name, pkeys):
        self._unsupported('add_table_pkey_sql')

    def create_extension_sql(self, extension_name):
        self._unsupported('create_extension_sql')

    def comment_on_column_sql(self, schema_name, table_name, column_name,
                              comment):
        self._unsupported('comment_on_column_sql')

    def comment_on_table_sql(self, schema_name, table_name, comment):
        self._unsupported('comment_on_table_sql')

    def foreign_key_sql(self, fk_name, columns, related_table, related_schema,
                        related_columns, on_delete=None, on_update=None,
                        deferrable=False, initially_deferred=False):
        q = self.quote_identifier
        local = ', '.join(q(col) for col in columns)
        remote = ', '.join(q(col) for col in related_columns)
        # SQLite resolves REFERENCES within the table's own database and
        # rejects a schema-qualified target. Cross-schema relations are gated.
        sql = f'CONSTRAINT {q(fk_name)} FOREIGN KEY ({local}) REFERENCES {q(related_table)} ({remote})'
        for clause, action in (('DELETE', on_delete), ('UPDATE', on_update)):
            if action:
                sql += f' ON {clause} {action}'
        # Same rule as the PostgreSQL writer: INITIALLY DEFERRED only
        # together with DEFERRABLE.
        if deferrable:
            sql += ' DEFERRABLE'
            if initially_deferred:
                sql += ' INITIALLY DEFERRED'
        return sql

    def execute(self, sql, auto_commit=False, manager=False):
        self._unsupported('execute')
