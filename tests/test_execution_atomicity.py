"""Execution guarantees shared by all database dialects."""

import sqlite3
from types import SimpleNamespace

import pytest

from genro_sqlmigration import MigrationExecutionError, PgDatabase, SqliteDatabase
from genro_sqlmigration.executor import ExecutorMixin


class RecordingAdapter:
    def __init__(self, atomic, error=None):
        self.supports_atomic_ddl = atomic
        self.error = error
        self.calls = []

    def execute(self, sql, autoCommit=False, manager=False):
        self.calls.append({
            'sql': sql,
            'autoCommit': autoCommit,
            'manager': manager,
        })
        if self.error and not manager:
            raise self.error


class ExecutionHarness(ExecutorMixin):
    def __init__(self, adapter, **phases):
        self.db = SimpleNamespace(adapter=adapter)
        self.sql_commands = {
            'db_creation': phases.get('db_creation'),
            'extensions_commands': phases.get('extensions_commands'),
            'build_commands': phases.get('build_commands'),
        }
        self.warnings = []

    def getChanges(self):
        return ''


def test_atomic_dialect_executes_one_transactional_ddl_unit():
    adapter = RecordingAdapter(atomic=True)
    harness = ExecutionHarness(
        adapter,
        extensions_commands='CREATE EXTENSION demo;',
        build_commands='CREATE TABLE demo (id int);',
    )

    result = harness.applyChanges()

    assert result == {
        'atomic': True,
        'best_effort': False,
        'phases_applied': ['ddl'],
    }
    assert adapter.calls == [{
        'sql': (
            'CREATE EXTENSION demo;\n'
            'CREATE TABLE demo (id int);'
        ),
        'autoCommit': False,
        'manager': False,
    }]
    assert harness.warnings == []


def test_non_atomic_dialect_is_explicit_best_effort():
    adapter = RecordingAdapter(atomic=False)
    harness = ExecutionHarness(adapter, build_commands='CREATE TABLE demo;')

    result = harness.applyChanges()

    assert result['best_effort'] is True
    assert adapter.calls[0]['autoCommit'] is True
    assert any('best-effort' in warning for warning in harness.warnings)


def test_failure_reports_rollback_or_possible_partial_state():
    atomic = ExecutionHarness(
        RecordingAdapter(atomic=True, error=RuntimeError('bad DDL')),
        build_commands='BROKEN;',
    )
    with pytest.raises(MigrationExecutionError) as caught:
        atomic.applyChanges()
    assert caught.value.phase == 'ddl'
    assert caught.value.rolled_back is True
    assert caught.value.partial_state_possible is False

    best_effort = ExecutionHarness(
        RecordingAdapter(atomic=False, error=RuntimeError('bad DDL')),
        build_commands='BROKEN;',
    )
    with pytest.raises(MigrationExecutionError) as caught:
        best_effort.applyChanges()
    assert caught.value.rolled_back is False
    assert caught.value.partial_state_possible is True


def test_created_database_is_reported_separately_on_later_failure():
    adapter = RecordingAdapter(atomic=True, error=RuntimeError('bad DDL'))
    harness = ExecutionHarness(
        adapter,
        db_creation='CREATE DATABASE demo;',
        build_commands='BROKEN;',
    )

    with pytest.raises(MigrationExecutionError) as caught:
        harness.applyChanges()

    assert caught.value.rolled_back is True
    assert caught.value.partial_state_possible is True
    assert adapter.calls[0]['manager'] is True
    assert adapter.calls[1]['manager'] is False


def test_sqlite_rolls_back_statements_before_failure(tmp_path):
    db_path = tmp_path / 'atomicity.db'
    sqlite3.connect(db_path).close()
    adapter = SqliteDatabase({'dbname': str(db_path)}).adapter

    with pytest.raises(sqlite3.OperationalError):
        adapter.execute(
            'CREATE TABLE first_table (id INTEGER);\n'
            'CREATE TABLE broken syntax;'
        )

    with sqlite3.connect(db_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'first_table'"
        ).fetchone()
    assert table is None


@pytest.mark.postgresql
def test_postgresql_rolls_back_statements_before_failure(pg_server):
    psycopg = pytest.importorskip('psycopg')
    params = dict(pg_server, dbname='postgres')
    table_name = '_sqlmigration_atomicity_probe'
    with psycopg.connect(**params, autocommit=True) as connection:
        connection.execute(f'DROP TABLE IF EXISTS "{table_name}"')

    adapter = PgDatabase(params, application_schemas=['public']).adapter
    with pytest.raises(psycopg.errors.UndefinedTable):
        adapter.execute(
            f'CREATE TABLE "{table_name}" (id integer);\n'
            'SELECT * FROM "_sqlmigration_missing_table";'
        )

    with psycopg.connect(**params) as connection:
        table = connection.execute(
            'SELECT to_regclass(%s)', (f'public.{table_name}',)
        ).fetchone()[0]
    assert table is None
