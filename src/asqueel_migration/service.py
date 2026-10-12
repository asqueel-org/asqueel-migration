"""Transport-independent migration operations on caller-owned databases.

The caller owns connection cleanup. No HTTP, MCP or Kajenn dependency belongs
here. Plan identifiers detect changes between review and execution; they are
not authorization tokens and cannot prevent concurrent external DDL.
"""

import hashlib
import json

from .exceptions import SqlMigrationError
from .migrator import SqlMigrator


class StaleMigrationPlan(SqlMigrationError):
    """The reviewed plan no longer matches the target and desired structure."""


class UnsupportedMigration(SqlMigrationError):
    """The target cannot perform all requested operations."""


def _prepare(database, structure, allow_removals=False):
    migrator = SqlMigrator(database, structure=structure, removeDisabled=not allow_removals)
    migrator.prepareMigrationCommands()
    sql = migrator.getChanges()
    warnings = list(migrator.warnings)
    skipped = [warning for warning in warnings if warning.startswith("unsupported '")]
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
    }
    plan_id = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return migrator, {
        'plan_id': plan_id, 'sql': sql, 'warnings': warnings,
        'skipped': skipped, 'empty': not sql.strip(),
    }


def plan_migration(database, structure, *, allow_removals=False):
    """Validate and plan a normalized dict/JSON document without executing DDL."""
    return _prepare(database, structure, allow_removals)[1]


def apply_migration(database, structure, *, expected_plan, allow_removals=False):
    """Replan, require the reviewed identifier, apply and verify convergence.

    Unsupported operations prevent execution. Database creation is a separate
    operation; atomicity and failures follow the underlying adapter contract.
    ``verified`` reports the post-apply comparison, not transactional rollback.
    """
    migrator, plan = _prepare(database, structure, allow_removals)
    if not expected_plan or expected_plan != plan['plan_id']:
        raise StaleMigrationPlan('The migration plan changed; request and review a new plan')
    if plan['skipped']:
        raise UnsupportedMigration('; '.join(plan['skipped']))
    execution = migrator.applyChanges()
    remaining = plan_migration(database, structure, allow_removals=allow_removals)
    return {
        **plan, 'execution': execution, 'warnings': list(migrator.warnings),
        'verified': remaining['empty'] and not remaining['skipped'],
        'remaining': remaining,
    }
