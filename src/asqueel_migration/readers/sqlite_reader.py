# Copyright (c) 2025 Softwell Srl, Milano, Italy
# SPDX-License-Identifier: Apache-2.0

"""
sqlite_reader.py - SQLite introspection reader
===============================================

Reads the actual structure of a SQLite database via the ``PRAGMA``
family and ``sqlite_master``, returning the normalized row format
consumed by the ``process_*`` methods on :class:`BaseReader`.

Schemas
-------

SQLite has no schemas; the package maps one schema to one file. The
reader receives the schema list and the per-schema file paths, ATTACHes
each non-main file right after connecting and then queries the ``"schema".``
namespace natively (``"schema".sqlite_master``, ``PRAGMA "schema".*``).

Declared-type fidelity
----------------------

:class:`SqliteWriter` emits the GenroPy legacy declared types and
SQLite returns them verbatim from ``PRAGMA table_info``; this reader
reverses them with :data:`SQLITE_TYPES_DICT`. The names written by
asqueel-migration 0.2 (``varchar``, ``char``, ``timestamp without time
zone``) map to the same dtypes, so a 0.2 database shows no differences. Parsing is
case-insensitive because SQLite upper-cases the type of an ``integer``
rowid-alias primary key (``INTEGER``).

v1 limitations
--------------

- The reader maps declared types only, so an integer primary key comes
  back as dtype ``I`` (not ``serial``): migrations targeting SQLite must
  declare integer PKs as ``I``.
- Foreign keys are read from PRAGMAs, which omit names and deferral options.
  Deferral options are recovered from the stored CREATE TABLE text.
- ``PRAGMA table_xinfo`` flags generated columns but omits their
  expression: it is recovered from the stored CREATE TABLE text.
- CHECK constraints are not introspected.
"""

import os
import re
import sqlite3
from collections import defaultdict

from asqueel_migration.exceptions import (
    NonExistingDbException,
    SqlConnectionException,
    SqlMigrationError,
)
from asqueel_migration.readers.base_reader import BaseReader

# Declared type base name -> normalized dtype code.
SQLITE_TYPES_DICT = {
    'bigint': 'L',
    'blob': 'O',
    'boolean': 'B',
    'char': 'C',
    'character': 'C',
    'character varying': 'A',
    'date': 'D',
    'integer': 'I',
    'jsonb': 'jsonb',
    'numeric': 'N',
    'real': 'R',
    'text': 'T',
    'time': 'H',
    'time without time zone': 'H',
    'timestamp': 'DH',
    'timestamp without time zone': 'DH',
    'timestamp with time zone': 'DHZ',
    'varchar': 'A',
}

# Literals and quoted identifiers, comments, then runs of other text.
_SQL_PIECES = re.compile(
    r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]"
    r"|--[^\r\n]*|/\*[\s\S]*?\*/|(?:[^-/'\"`\[]|-(?!-)|/(?!\*))+"
)


class SqliteReader(BaseReader):
    """SQLite introspection reader.

    Args:
        connection_params: dict with ``dbname`` (absolute path of the main
            database file).
        schemas: mapping ``{schema_name: file_path}`` of the schema files
            to ATTACH. The adapter builds it from the database's known
            schemas; ``get_json_struct(dbname, schemas)`` still drives the
            flow with the schema-name list.
    """

    reads_generated_expressions = True

    def __init__(self, connection_params=None, schemas=None, connection=None):
        super().__init__(connection_params)
        self._conn = None
        self._borrowed = connection
        self.schema_files = dict(schemas or {})

    def dbname(self):
        """Return the main database file path (used for exception messages)."""
        return self.connection_params.get('dbname')

    def connect(self):
        """Open the connection, ATTACH schema files, enable foreign keys.

        A missing main database file raises :class:`NonExistingDbException`
        (``sqlite3.connect`` would silently create it); any other failure
        raises :class:`SqlConnectionException`. A caller's connection
        (``connection``) is used as it is: the caller has attached the schemas.
        """
        if self._borrowed is not None:
            self._conn = self._borrowed
            return
        dbname = self.dbname()
        if not os.path.exists(dbname):
            raise NonExistingDbException(dbname)
        try:
            self._conn = sqlite3.connect(dbname)
            self._conn.execute('PRAGMA foreign_keys = ON')
            for schema_name, path in self.schema_files.items():
                if schema_name == "main":
                    continue
                self._conn.execute(
                    f'ATTACH DATABASE ? AS {self.quote_identifier(schema_name)}', (path,)
                )
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as error:
            raise SqlConnectionException(dbname, original_error=error) from error

    def close(self):
        """Close the database connection if open; a caller's connection stays open."""
        if self._conn and self._conn is not self._borrowed:
            self._conn.close()
        self._conn = None

    def _fetch(self, sql, params=None):
        """Execute a query and return the rows as tuples."""
        cur = self._conn.execute(sql, params or ())
        return cur.fetchall()

    def _reverse_type(self, declared):
        """Reverse a declared type text into ``(dtype, size)``.

        ``character varying(100)`` -> ('A', '0:100'); ``numeric(10,2)`` -> ('N', '10,2');
        ``character(5)`` -> ('C', '5'); unknown -> ('T', None).
        """
        if not declared:
            return 'T', None
        text = declared.strip().lower()
        match = re.match(r'^([a-z ]+?)\s*(?:\(([^)]*)\))?$', text)
        if not match:
            return 'T', None
        base = match.group(1).strip()
        args = match.group(2)
        dtype = SQLITE_TYPES_DICT.get(base, 'T')
        if dtype == 'A':
            return 'A', f'0:{args}' if args else None
        if dtype == 'C':
            return 'C', args if args else None
        if dtype == 'N':
            return 'N', args if args else None
        return dtype, None

    def fetch_base_structure(self, schemas):
        columns = []
        for schema_name in schemas:
            tables = self._fetch(
                f'SELECT name FROM {self.quote_identifier(schema_name)}.sqlite_master '
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            if not tables:
                # Register the schema even when it has no tables so the base
                # processing can decide whether to keep or drop it.
                columns.append({
                    '_pg_schema_name': schema_name,
                    '_pg_table_name': None,
                    'name': None,
                    '_pg_is_nullable': 'YES',
                })
                continue
            for (table_name,) in tables:
                expressions = None
                for row in self._fetch(
                    f'PRAGMA {self.quote_identifier(schema_name)}.table_xinfo({self.quote_identifier(table_name)})'
                ):
                    _cid, name, declared, notnull, dflt, _pk, hidden = row
                    # hidden: 1 virtual-table hidden column, 2 virtual generated, 3 stored generated.
                    if hidden == 1:
                        continue
                    dtype, size = self._reverse_type(declared)
                    col = {
                        '_pg_schema_name': schema_name,
                        '_pg_table_name': table_name,
                        'name': name,
                        'dtype': dtype,
                        '_pg_is_nullable': 'NO' if notnull else 'YES',
                        'sqldefault': dflt,
                    }
                    if size is not None:
                        col['size'] = size
                    if hidden:
                        if expressions is None:
                            expressions = self._generated_expressions(schema_name, table_name)
                        if name not in expressions:
                            raise SqlMigrationError(
                                f'Cannot introspect generated column {schema_name}.{table_name}.{name}'
                            )
                        col['generated_expression'] = expressions[name]
                    columns.append(col)
        return columns

    def _generated_expressions(self, schema_name, table_name):
        """Return ``{column: expression}`` of the generated columns of a table.

        Each top-level definition of the stored CREATE TABLE text holding an
        ``AS (`` clause outside literals and comments is a generated column;
        the expression is the text between its balanced parentheses.
        """
        row = self._fetch(
            f'SELECT sql FROM {self.quote_identifier(schema_name)}.sqlite_master '
            'WHERE type=\'table\' AND name=?',
            (table_name,),
        )
        result = {}
        for text, masked in self._table_body_items(row[0][0]):
            clause = re.search(r'\bAS\s*\(', masked, re.IGNORECASE)
            if not clause:
                continue
            end, depth = clause.end(), 1
            while end < len(masked) and depth:
                if masked[end] == '(':
                    depth += 1
                elif masked[end] == ')':
                    depth -= 1
                end += 1
            if depth:
                raise SqlMigrationError(f'Cannot introspect generated expression of {schema_name}.{table_name}')
            name = re.match(r'\s*(\S+)', masked)
            result[self._unquote(text[name.start(1):name.end(1)])] = text[clause.end():end - 1].strip()
        return result

    def same_generated_expression(self, schema_name, table_name, wanted, stored):
        """Return True if two generated expressions differ only in comments and spacing."""
        return self._normalized_sql(wanted) == self._normalized_sql(stored)

    @staticmethod
    def _normalized_sql(sql):
        """Return the tokens of an expression: comments and spacing dropped, literals kept."""
        tokens = []
        for match in _SQL_PIECES.finditer(sql):
            piece = match.group()
            if piece.startswith(('--', '/*')):
                continue
            if piece[:1] in '\'"`[':
                tokens.append(piece)
            else:
                tokens.extend(re.findall(r'\w+|\S', piece))
        return tokens

    def fetch_constraints(self, schemas):
        constraints = defaultdict(lambda: defaultdict(dict))
        for schema_name in schemas:
            tables = self._fetch(
                f'SELECT name FROM {self.quote_identifier(schema_name)}.sqlite_master '
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            for (table_name,) in tables:
                table_key = (schema_name, table_name)
                self._fetch_primary_key(schema_name, table_name, constraints[table_key])
                self._fetch_unique(schema_name, table_name, constraints[table_key])
                self._fetch_foreign_keys(schema_name, table_name, constraints[table_key])
        return constraints

    def _fetch_foreign_keys(self, schema_name, table_name, table_constraints):
        groups = defaultdict(list)
        for row in self._fetch(
            f'PRAGMA {self.quote_identifier(schema_name)}.foreign_key_list({self.quote_identifier(table_name)})'
        ):
            groups[row[0]].append(row)
        deferral = self._fk_deferral(schema_name, table_name) if groups else {}
        for fk_id, rows in groups.items():
            rows.sort(key=lambda row: row[1])
            _, _, target, _, _, on_update, on_delete, _ = rows[0]
            related_columns = [row[4] for row in rows]
            if any(name is None for name in related_columns):
                # REFERENCES parent without an explicit target column list
                # means the parent's ordered primary key.
                pk = {}
                self._fetch_primary_key(schema_name, target, pk)
                related_columns = pk.get('PRIMARY KEY', {}).get('columns', [])
            columns = [row[3] for row in rows]
            deferrable, initially_deferred = deferral.get(
                tuple(name.lower() for name in columns), (False, False)
            )
            table_constraints['FOREIGN KEY'][fk_id] = {
                'constraint_type': 'FOREIGN KEY',
                'columns': columns,
                'related_schema': schema_name,
                'related_table': target,
                'related_columns': related_columns,
                'on_update': on_update,
                'on_delete': on_delete,
                'deferrable': deferrable,
                'initially_deferred': initially_deferred,
            }

    def _fk_deferral(self, schema_name, table_name):
        """Return the deferral options of a table's foreign keys.

        SQLite stores the CREATE TABLE text verbatim and the PRAGMAs omit
        deferral, so each top-level definition of the table body holding a
        ``REFERENCES`` clause is parsed. Both the table-constraint form
        (``FOREIGN KEY (cols) REFERENCES ...``) and the column-constraint
        form (``col type REFERENCES ...``) are recognized.

        Returns:
            dict: ``{(local columns, lower-cased): (deferrable,
            initially_deferred)}``.
        """
        row = self._fetch(
            f'SELECT sql FROM {self.quote_identifier(schema_name)}.sqlite_master '
            'WHERE type=\'table\' AND name=?',
            (table_name,),
        )
        result = {}
        for text, masked in self._table_body_items(row[0][0]):
            references = re.search(r'\bREFERENCES\b', masked, re.IGNORECASE)
            if not references:
                continue
            head = re.match(
                r'\s*(?:CONSTRAINT\s+\S+\s+)?FOREIGN\s+KEY\s*\(([^)]*)\)',
                masked, re.IGNORECASE,
            )
            if head:
                columns = text[head.start(1):head.end(1)].split(',')
            else:
                columns = [text.split(None, 1)[0]]
            clause = re.search(
                r'(NOT\s+)?DEFERRABLE(?:\s+INITIALLY\s+(DEFERRED|IMMEDIATE))?',
                masked[references.end():], re.IGNORECASE,
            )
            deferrable = bool(clause) and not clause.group(1)
            initially_deferred = deferrable and (clause.group(2) or '').upper() == 'DEFERRED'
            key = tuple(self._unquote(column).lower() for column in columns)
            result[key] = (deferrable, initially_deferred)
        return result

    @staticmethod
    def _table_body_items(create_sql):
        """Split a CREATE TABLE body into its top-level definitions.

        Returns a list of ``(text, masked)`` pairs: ``masked`` has the same
        length as ``text`` with quoted content and comments blanked, so
        keyword searches never match inside identifiers, string literals or
        comments.
        """
        closers = {'"': '"', "'": "'", '`': '`', '[': ']'}
        masked = []
        index = 0
        while index < len(create_sql):
            char = create_sql[index]
            if create_sql.startswith(('--', '/*'), index):
                if char == '-':
                    end = create_sql.find('\n', index)
                    end = len(create_sql) if end < 0 else end
                else:
                    end = create_sql.find('*/', index + 2)
                    end = len(create_sql) if end < 0 else end + 2
                masked.append(' ' * (end - index))
                index = end
                continue
            if char in closers:
                end = create_sql.find(closers[char], index + 1)
                while closers[char] != ']' and end + 1 < len(create_sql) and create_sql[end + 1] == char:
                    end = create_sql.find(char, end + 2)
                masked.append(char + '_' * (end - index - 1) + closers[char])
                index = end + 1
                continue
            masked.append(char)
            index += 1
        masked = ''.join(masked)
        start = masked.index('(') + 1
        items = []
        depth = 0
        item_start = start
        for position in range(start, len(masked)):
            char = masked[position]
            if char == '(':
                depth += 1
            elif char == ')' and depth:
                depth -= 1
            elif char in ',)' and not depth:
                items.append((create_sql[item_start:position], masked[item_start:position]))
                item_start = position + 1
                if char == ')':
                    break
        return items

    @staticmethod
    def _unquote(identifier):
        """Return an identifier without its SQLite quoting."""
        identifier = identifier.strip()
        if identifier[:1] in '"`' and identifier[-1:] == identifier[:1]:
            quote = identifier[0]
            return identifier[1:-1].replace(quote * 2, quote)
        if identifier[:1] == '[' and identifier[-1:] == ']':
            return identifier[1:-1]
        return identifier

    def _fetch_primary_key(self, schema_name, table_name, table_constraints):
        pk_columns = []
        for row in self._fetch(
            f'PRAGMA {self.quote_identifier(schema_name)}.table_info({self.quote_identifier(table_name)})'
        ):
            _cid, name, _declared, _notnull, _dflt, pk = row
            if pk:
                pk_columns.append((pk, name))
        if pk_columns:
            pk_columns.sort()
            table_constraints["PRIMARY KEY"] = {
                "constraint_name": f'{table_name}_pkey',
                "constraint_type": "PRIMARY KEY",
                "columns": [name for _order, name in pk_columns],
            }

    def _fetch_unique(self, schema_name, table_name, table_constraints):
        for row in self._fetch(
            f'PRAGMA {self.quote_identifier(schema_name)}.index_list({self.quote_identifier(table_name)})'
        ):
            _seq, index_name, unique, origin, _partial = row
            if not self._is_unique_constraint_index(index_name, unique, origin):
                continue
            info = self._fetch(
                f'PRAGMA {self.quote_identifier(schema_name)}.index_info({self.quote_identifier(index_name)})'
            )
            column_names = [name for _seqno, _cid, name in info]
            table_constraints["UNIQUE"][index_name] = {
                "constraint_name": index_name,
                "constraint_type": "UNIQUE",
                "columns": column_names,
            }

    def _is_unique_constraint_index(self, index_name, unique, origin):
        """Return True if an index represents a UNIQUE constraint.

        SQLite reports inline ``UNIQUE`` columns as origin 'u' autoindexes.
        A single-column UNIQUE emitted by the shared command builder arrives
        as ``ALTER TABLE ... ADD CONSTRAINT`` which the adapter rewrites into
        a ``cst_``-named UNIQUE index (origin 'c'); it is recognized here so
        it round-trips back into the column ``unique`` attribute.
        """
        if origin == 'u':
            return True
        return bool(unique) and index_name.startswith('cst_')

    def fetch_indexes(self, schemas):
        indexes = defaultdict(dict)
        for schema_name in schemas:
            master = {
                name: sql
                for _t, name, _tbl, sql in self._fetch(
                    f"SELECT type, name, tbl_name, sql FROM "
                    f'{self.quote_identifier(schema_name)}.sqlite_master WHERE type=\'index\''
                )
            }
            tables = self._fetch(
                f'SELECT name FROM {self.quote_identifier(schema_name)}.sqlite_master '
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            for (table_name,) in tables:
                table_key = (schema_name, table_name)
                for row in self._fetch(
                    f'PRAGMA {self.quote_identifier(schema_name)}.index_list({self.quote_identifier(table_name)})'
                ):
                    _seq, index_name, unique, origin, _partial = row
                    columns = self._index_columns(schema_name, index_name)
                    # Mark constraint-backed indexes (PK / UNIQUE, incl. the
                    # cst_-named UNIQUE index the adapter rewrites) so shared
                    # index processing skips them.
                    if origin != 'c':
                        constraint_type = origin
                    elif self._is_unique_constraint_index(index_name, unique, origin):
                        constraint_type = 'u'
                    else:
                        constraint_type = None
                    indexes[table_key][index_name] = {
                        "unique": False,
                        "columns": columns,
                        "constraint_type": constraint_type,
                        "where": self._index_where(master.get(index_name)),
                    }
        return indexes

    def _index_columns(self, schema_name, index_name):
        """Return the ordered ``{column: sort_order}`` map of an index."""
        columns = {}
        for row in self._fetch(
            f'PRAGMA {self.quote_identifier(schema_name)}.index_xinfo({self.quote_identifier(index_name)})'
        ):
            _seqno, _cid, name, desc, _coll, key = row
            if not key or name is None:
                continue
            columns[name] = "DESC" if desc else None
        return columns

    def _index_where(self, index_sql):
        """Recover a partial index WHERE clause from the stored CREATE INDEX.

        SQLite stores the CREATE INDEX text verbatim, so the substring after
        the final ``) WHERE `` round-trips exactly.
        """
        if not index_sql:
            return None
        match = re.search(r'\)\s+WHERE\s+(.+)$', index_sql, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else None

    def fetch_extensions(self):
        return {}

    def fetch_event_triggers(self):
        return {}

    def is_empty_column(self, schema_name, table_name, column_name):
        """Return True if the column contains only NULL values."""
        sql = (
            f'SELECT COUNT(*) = 0 FROM {self.quote_identifier(schema_name)}.{self.quote_identifier(table_name)} '
            f'WHERE {self.quote_identifier(column_name)} IS NOT NULL'
        )
        try:
            self.connect()
            rows = self._fetch(sql)
            return bool(rows[0][0]) if rows else False
        finally:
            self.close()
