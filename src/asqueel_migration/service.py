"""Transport-independent migration operations on caller-owned databases.

The caller owns connection cleanup. No HTTP, MCP or Kajenn dependency belongs
here. Plan identifiers detect changes between review and execution; they are
not authorization tokens and cannot prevent concurrent external DDL.
"""

import hashlib
import json

from .exceptions import SqlMigrationError, SqlValidationError
from .migrator import SqlMigrator


class StaleMigrationPlan(SqlMigrationError):
    """The reviewed plan no longer matches the target and desired structure."""


class UnsupportedMigration(SqlMigrationError):
    """The target cannot perform all requested operations."""


def _prepare(database, structure, allow_removals=False, *, force=False, backup=False,
             ignore_constraint_name=True):
    # The legacy constructor permits deferred assignment; service operations
    # require an explicit desired schema before inspecting the database.
    if structure is None:
        raise SqlValidationError(["structure must be a dict or a JSON document containing an object"])
    migrator = SqlMigrator(database, structure=structure, removeDisabled=not allow_removals,
                           force=force, backup=backup, ignore_constraint_name=ignore_constraint_name)
    migrator.prepareMigrationCommands()
    sql = migrator.getChanges()
    warnings = list(migrator.warnings)
    skipped_changes = [dict(change) for change in migrator.skipped]
    skipped = [change["warning"] for change in skipped_changes]
    snapshot = {
        'database': database.get_dbname(),
        'target': {key: value for key, value in database.connection_params().items()
                   if key in {'host', 'port', 'user', 'dbname', 'database', 'server'}},
        'adapter': type(database.adapter).__name__,
        'current': migrator.sqlStructure,
        'desired': migrator.ormStructure,
        'sql': sql,
        'warnings': warnings,
        'allow_removals': allow_removals,
        'force': force,
        'backup': backup,
        'ignore_constraint_name': ignore_constraint_name,
    }
    plan_id = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    # A changed generated expression emits no SQL, yet the database differs.
    empty = not sql.strip() and not any(
        change['capability'] == 'alter_generated_expression' for change in skipped_changes)
    return migrator, {
        'plan_id': plan_id, 'sql': sql, 'warnings': warnings,
        'skipped': skipped, 'skipped_changes': skipped_changes, 'empty': empty,
    }


def plan_migration(database, structure, *, allow_removals=False, force=False, backup=False,
                   ignore_constraint_name=True):
    """Validate and plan a normalized dict/JSON document without executing DDL.

    ``force`` converts a filled column whose values may not convert (they
    become NULL); ``backup`` keeps the old values in a backup column and
    implies ``force``; ``ignore_constraint_name`` ignores constraint and
    index name differences (see :class:`SqlMigrator`). ``empty`` is False
    when SQL is planned or a generated expression changed.
    """
    return _prepare(database, structure, allow_removals, force=force, backup=backup,
                    ignore_constraint_name=ignore_constraint_name)[1]


def apply_migration(database, structure, *, expected_plan, allow_removals=False, force=False,
                    backup=False, ignore_constraint_name=True):
    """Replan, require the reviewed identifier, apply and verify convergence.

    The options are those of :func:`plan_migration`. Unsupported operations
    prevent execution. Database creation is a separate operation; atomicity
    and failures follow the underlying adapter contract. ``backups`` is the
    report of :meth:`SqlMigrator.verifyConversionBackups`: the backup columns
    kept because values were lost or could not be verified. With a backup
    column kept, the post-apply comparison runs without removals, which
    would drop it. ``verified`` reports that comparison, not transactional
    rollback.
    """
    migrator, plan = _prepare(database, structure, allow_removals, force=force, backup=backup,
                              ignore_constraint_name=ignore_constraint_name)
    if not expected_plan or expected_plan != plan['plan_id']:
        raise StaleMigrationPlan('The migration plan changed; request and review a new plan')
    if plan['skipped']:
        raise UnsupportedMigration('; '.join(plan['skipped']))
    execution = migrator.applyChanges()
    backups = migrator.verifyConversionBackups()
    remaining = plan_migration(database, structure, allow_removals=allow_removals and not backups,
                               ignore_constraint_name=ignore_constraint_name)
    return {
        **plan, 'execution': execution, 'warnings': list(migrator.warnings),
        'backups': backups,
        'verified': remaining['empty'] and not remaining['skipped'],
        'remaining': remaining,
    }
