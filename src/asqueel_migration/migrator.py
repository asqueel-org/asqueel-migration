"""
migrator.py - SQL migration orchestrator
==========================================

This module contains the :class:`SqlMigrator` class, the main entry point
of the migration system. SqlMigrator **composes** the three mixins
that implement the different phases of migration:

- :class:`DiffMixin` (from ``diff_engine.py``): desired vs current schema comparison
- :class:`CommandBuilderMixin` (from ``command_builder.py``): SQL generation
- :class:`ExecutorMixin` (from ``executor.py``): assembly and execution

Architecture
-------------

SqlMigrator follows the **orchestrator** pattern: it does not directly
implement comparison or SQL generation logic, but coordinates the
components that do. Its responsibilities are:

1. **Initialization**: stores the database facade, snapshots the supplied
   structure and configures migration parameters (force, backup, etc.)

2. **Structure preparation**: restores a working copy of the desired schema,
   filters dialect capabilities and reads the current database structure

3. **Diff computation**: delegates to DiffMixin to produce events

4. **Command generation**: delegates to CommandBuilderMixin to create SQL

5. **Execution**: delegates to ExecutorMixin to apply changes

Complete migration flow
------------------------

::

    SqlMigrator
        |
        +-- __init__()
        |   +-- snapshot the caller's normalized structure
        |
        +-- prepareStructures()
        |   +-- extractOrm() -> fresh copy of the supplied structure
        |   +-- applyCapabilities() -> filter the working copy, record warnings
        |   +-- extractSql() -> db.adapter.reader.get_json_struct(dbname, schemas)
        |
        +-- prepareMigrationCommands()  [uses DiffMixin + CommandBuilderMixin]
        |   +-- dictDifferChanges()  -> added/changed/removed events
        |   +-- handler(**kw)  -> SQL commands in self.commands
        |
        +-- getChanges()  [uses ExecutorMixin]
        |   +-- sqlCommandsForTable()  -> assembled SQL
        |
        +-- applyChanges()  [uses ExecutorMixin]
            +-- db.adapter.execute()

Configuration parameters
--------------------------

- **structure**: normalized dictionary or JSON document describing the
  desired schema, including extensions in ``root.extensions``. Producers
  own extraction from application models.

- **extensions**: retained as a legacy constructor parameter; storing this
  list alone does not add extensions to the desired structure.

- **ignore_constraint_name** (default True): ignores differences in
  constraint and index names. Useful because producers generate hashed
  names that may differ from manually created names in the DB.

- **excludeReadOnly** (default True): excludes schemas declared read-only
  by the database facade from introspection. Command generation always
  skips entities in those schemas.

- **removeDisabled** (default True): skips removal events. Disabling this
  flag enables the implemented removal handler, ``DROP COLUMN``; other
  removal handlers preserve database-only entities.

- **force** (default False): forces type conversions even on non-empty
  columns. Incompatible values become NULL.

- **backup** (default False, implies force): before a type conversion,
  creates a backup column with the original data. Allows verifying
  the conversion and recovering lost data.

Usage
------

Typical usage example::

    from asqueel_migration import SqlMigrator

    # Compute differences without applying them
    # db is a database facade; desired is normalized JSON or a dictionary.
    # The caller owns db and closes its connections when finished.
    migrator = SqlMigrator(db, structure=desired)
    sql = migrator.getChanges()
    print(sql)

    # Apply differences
    migrator.applyChanges()

    # With backup for type conversions
    migrator = SqlMigrator(db, structure=desired, backup=True)
    migrator.applyChanges()
    report = migrator.verifyConversionBackups()
"""

import copy
import json

from .command_builder import CommandBuilderMixin
from .diff_engine import DiffMixin
from .exceptions import NonExistingDbException, SqlMigrationError
from .executor import ExecutorMixin
from .structures import nested_defaultdict, unique_index_column


class SqlMigrator(DiffMixin, CommandBuilderMixin, ExecutorMixin):
    """Main SQL migration orchestrator.

    Coordinates caller-supplied structures and database introspection, comparison,
    SQL command generation and execution.

    Inherits from mixins:
    - :class:`DiffMixin`: ``diff`` property, ``dictDifferChanges()``
    - :class:`CommandBuilderMixin`: ``added_*``, ``changed_*``,
      ``removed_*`` handlers, SQL helpers
    - :class:`ExecutorMixin`: ``getChanges()``, ``applyChanges()``,
      ``verifyConversionBackups()``

    Args:
        db: Database facade exposing an adapter and connection/schema settings.
        extensions: Legacy comma-separated extension list. Desired extensions
            must be supplied in the structure's ``root.extensions`` container.
        ignore_constraint_name: If True, ignores differences in constraint
            names (default True).
        excludeReadOnly: If True, excludes read-only schemas from introspection
            (default True). Commands for those schemas are always skipped.
        removeDisabled: If True, does not generate removal commands (default True).
        force: If True, forces type conversions on non-empty columns
            (default False).
        backup: If True, creates backups before conversions. Implies force
            (default False).
        structure: Normalized dictionary or JSON document, validated and copied
            when supplied. Otherwise assign ``ormStructure`` before preparation.
    """

    def __init__(self, db,
                 extensions=None,
                 ignore_constraint_name=True,
                 excludeReadOnly=True,
                 removeDisabled=True,
                 force=False,
                 backup=False,
                 *, structure=None):
        self.db = db
        self.extensions = extensions.split(',') if extensions else []
        self.commands = {}
        self.sql_commands = {
            'db_creation': None,
            'build_commands': None,
            'extensions_commands': None
        }
        self.excludeReadOnly = excludeReadOnly
        self.removeDisabled = removeDisabled
        self.ignore_constraint_name = ignore_constraint_name
        self.force = force or backup  # backup implies force
        self.backup = backup
        self.ormStructure = {}
        self.warnings = []
        self.skipped = []
        if structure is not None:
            from .validation import StructureValidator
            self.ormStructure = StructureValidator().validate(self._decode_structure(structure))

    @staticmethod
    def _decode_structure(value):
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise TypeError('structure must be a dict or a JSON document containing an object')
        return value

    @property
    def ormStructure(self):
        """Current working structure; assign a new input to replace the source.

        Assignment accepts a dict or serialized JSON and takes an independent
        snapshot. Preparation always starts from that snapshot, before dialect
        filtering. Mutating this working view does not update the source.
        """
        return self._orm_structure

    @ormStructure.setter
    def ormStructure(self, value):
        self._source_structure = copy.deepcopy(self._decode_structure(value))
        self._orm_structure = copy.deepcopy(self._source_structure)
        self.commands = {}
        self.sql_commands = {}

    def prepareMigrationCommands(self):
        """Prepare migration commands by comparing ORM and DB.

        This is the method that orchestrates the complete flow:

        1. Calls ``prepareStructures()`` to copy the desired schema and read the DB
        2. Initializes ``self.commands`` as a nested defaultdict
        3. Iterates over diff events (from DiffMixin)
        4. For each event, calls the corresponding handler
           (from CommandBuilderMixin) which populates ``self.commands``

        'removed' events are skipped if ``removeDisabled`` is True.
        Entities in read-only schemas are ignored.
        """
        self.prepareStructures()
        self.commands = nested_defaultdict()
        self.sql_commands = {}
        for evt, kw in self.dictDifferChanges():
            if evt == 'removed' and self.removeDisabled:
                continue
            item = kw['item']
            if item.get('schema_name') in self.readOnly_schemas:
                continue
            handler = getattr(
                self, f'{evt}_{kw["entity"]}', self.missing_handler_cb
            )
            handler(**kw)

    def prepareStructures(self):
        """Prepare the desired working copy and read the database structure.

        Determines which schemas to inspect:
        - ``application_schemas``: schemas managed by the application
        - ``readOnly_schemas``: schemas to exclude if excludeReadOnly is True
        - ``tenant_schemas``: multi-tenant schemas

        Restores the supplied structure, filters unsupported capabilities and
        introspects the selected schemas through the adapter's reader.
        """
        self.warnings = []
        self.skipped = []
        self.application_schemas = self.db.getApplicationSchemas()
        self.readOnly_schemas = self.db.readOnlySchemas()
        if self.excludeReadOnly:
            self.application_schemas = [
                schema for schema in self.application_schemas
                if schema not in self.readOnly_schemas
            ]
        try:
            self.tenant_schemas = self.db.getTenantSchemas()
        except NonExistingDbException:
            self.tenant_schemas = []
        self.extractOrm()
        self.applyCapabilities()
        self.extractSql(
            schemas=self.application_schemas + self.tenant_schemas
        )

    def extractOrm(self):
        """Restore a fresh working copy of the caller-injected source.

        Producers own schema extraction. Dialect filtering only changes this
        working copy; every preparation starts with the complete source and
        regenerates its warnings. The version envelope never enters the diff.
        """
        self._orm_structure = copy.deepcopy(self._source_structure)
        self._orm_structure.pop('format_version', None)

    def applyCapabilities(self):
        """Strip from ormStructure what the target dialect cannot represent.

        Gating happens before the diff: an attribute the dialect cannot
        store never appears on the DB side, so keeping it in the ORM
        structure would produce a permanent false diff. Every removal
        appends a warning to ``self.warnings``.
        """
        caps = self.db.adapter.capabilities
        root = self.ormStructure.get('root')
        if not root:
            return
        for entity_kind in ('extensions', 'event_triggers'):
            if entity_kind not in caps and root.get(entity_kind):
                names = ', '.join(root[entity_kind])
                root[entity_kind] = {}
                self.record_skipped(entity_kind, names, action="ignored")
        for schema_name, schema in root.get('schemas', {}).items():
            for table_name, table in schema.get('tables', {}).items():
                self.applyTableCapabilities(
                    caps, f'{schema_name}.{table_name}', table
                )

    def applyTableCapabilities(self, caps, tablepath, table):
        """Strip unsupported attributes from one table of the ormStructure."""
        if 'serial4' not in caps:
            for column_name, column in table.get('columns', {}).items():
                if column['attributes'].get('dtype') == 'serial4':
                    raise SqlMigrationError(
                        f'serial4 is supported only by PostgreSQL: {tablepath}.{column_name}'
                    )
        if 'foreign_keys' not in caps and table.get('relations'):
            names = ', '.join(table['relations'])
            table['relations'] = {}
            self.record_skipped("foreign_keys", f"relations on {tablepath} ({names})", action="ignored")
        if 'inline_foreign_keys' in caps:
            for name, relation in list(table.get('relations', {}).items()):
                if relation['attributes']['related_schema'] != relation['schema_name']:
                    del table['relations'][name]
                    self.record_skipped(
                        'cross_schema_foreign_keys', f"relation on {tablepath} ({name})", action="ignored"
                    )
        if 'table_constraints' not in caps and table.get('constraints'):
            unsupported_names = [
                name for name, constraint in table['constraints'].items()
                if not ('unique_constraints' in caps and constraint['attributes']['constraint_type'] == 'UNIQUE')
            ]
            if unsupported_names:
                for name in unsupported_names:
                    del table['constraints'][name]
                names = ', '.join(unsupported_names)
                self.record_skipped("table_constraints", f"constraints on {tablepath} ({names})", action="ignored")
        if 'comments' not in caps:
            if table['attributes'].pop('comment', None):
                self.record_skipped("comments", f"comment on {tablepath}", action="ignored")
            for column_name, column in table.get('columns', {}).items():
                if column['attributes'].pop('comment', None):
                    self.record_skipped("comments", f"comment on {tablepath}.{column_name}", action="ignored")
        if 'fk_deferrable' not in caps:
            for relation_name, relation in table.get('relations', {}).items():
                for key in ('deferrable', 'initially_deferred'):
                    if relation['attributes'].pop(key, None):
                        self.record_skipped(
                            "fk_deferrable", f"'{key}' on {tablepath} relation {relation_name}", action="ignored"
                        )
        index_capabilities = (
            ('index_where', 'where'), ('index_method', 'method'),
            ('index_tablespace', 'tablespace'),
            ('index_with_options', 'with_options'),
        )
        for capability, attribute in index_capabilities:
            if capability in caps:
                continue
            for index_name, index in table.get('indexes', {}).items():
                if index['attributes'].pop(attribute, None):
                    self.record_skipped(
                        capability, f"'{attribute}' on {tablepath} index {index_name}", action="ignored"
                    )

    def extractSql(self, schemas=None):
        """Extract the JSON structure from the actual database.

        Args:
            schemas: List of schemas to inspect.
        """
        reader = self.db.adapter.reader
        self.sqlStructure = reader.get_json_struct(self.db.get_dbname(), schemas=schemas)
        self.column_unique_objects = copy.deepcopy(reader.column_unique_objects)
        self._match_explicit_unique_indexes(reader)

    def _match_explicit_unique_indexes(self, reader):
        """Keep authored index declarations distinct from column unique=True.

        The legacy column rule must not discard the name, ordering or options
        of explicit indexes in the existing JSON contract. Restore those
        objects for the ordinary index diff, which already uses real names.
        """
        for schema_name, schema in self.ormStructure.get('root', {}).get('schemas', {}).items():
            for table_name, table in schema.get('tables', {}).items():
                for index_key, index in table.get('indexes', {}).items():
                    column = unique_index_column(index['attributes'], table['attributes'].get('pkeys'))
                    key = (schema_name, table_name, column)
                    candidates = reader.column_unique_indexes.get(key, ())
                    if not candidates:
                        continue
                    desired_name = index['attributes'].get('index_name')
                    existing = next((candidate for candidate in candidates
                                     if candidate['attributes']['index_name'] == desired_name), candidates[0])
                    actual = self.sqlStructure['root']['schemas'][schema_name]['tables'][table_name]
                    actual['indexes'][index_key] = copy.deepcopy(existing)
                    name = existing['attributes']['index_name']
                    self.column_unique_objects[key].remove(('index', name))
                    if (not self.column_unique_objects[key]
                            and not table['columns'][column]['attributes'].get('unique')):
                        actual['columns'][column]['attributes'].pop('unique', None)

    def clearSql(self):
        """Reset the SQL structure extracted from the database."""
        self.sqlStructure = {}

    def clearOrm(self):
        """Reset the ORM structure."""
        self.ormStructure = {}

    def clearCommands(self):
        """Reset the DB creation commands to force regeneration."""
        self.commands.pop('db', None)
