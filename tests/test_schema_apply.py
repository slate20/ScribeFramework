"""
Tests for `scribe schema apply` and transactional SQLite migrations.
"""

import glob
import json
import os

import pytest
from click.testing import CliRunner

from scribe.cli import cli, _apply_refusal
from scribe.database import create_adapter
from scribe.migrations import MigrationTarget, run_migrations

HEADER = "from scribe.schema import Table, Column, Index, ForeignKey, sql, raw_sql, unmanaged\n\n"


def write(path, content):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def make_project(tmp_path, body, auto_migrate=True, setup=()):
    block = {'type': 'sqlite', 'database': str(tmp_path / 'app.db'), 'auto_migrate': auto_migrate}
    write(tmp_path / 'scribe.json', json.dumps({'databases': {'default': block}}))
    write(tmp_path / 'schemas' / 'schema_default.py', HEADER + body)
    os.makedirs(tmp_path / 'migrations', exist_ok=True)
    db = create_adapter({'type': 'sqlite', 'database': str(tmp_path / 'app.db')})
    for statement in setup:
        db.execute(statement)
    return str(tmp_path), db


def run(*args):
    return CliRunner().invoke(cli, list(args))


def migration_names(tmp_path):
    return [os.path.basename(p) for p in sorted(glob.glob(str(tmp_path / 'migrations' / '*.sql')))]


def columns(db, table):
    return [c.name for c in db.get_columns(table)]


# === Eligibility ===

def target(dialect='sqlite', auto_migrate=True, implicit=False):
    return MigrationTarget('default', '/m', auto_migrate, implicit, dialect)


def test_apply_eligibility():
    assert _apply_refusal(target(), 'default') is None
    assert _apply_refusal(target('sqlite', implicit=True), 'default') is None
    assert _apply_refusal(target('postgresql'), 'default') is None
    assert "Migrations are not enabled" in _apply_refusal(None, 'default')
    assert "auto_migrate off" in _apply_refusal(target(auto_migrate=False), 'default')
    assert "no explicit" in _apply_refusal(target('postgresql', implicit=True), 'default')


# === apply ===

def test_apply_writes_and_runs_additive_changes_only(tmp_path):
    path, db = make_project(tmp_path, """
Table("tasks",
    Column("id", "INTEGER", primary_key=True),
    Column("title", "VARCHAR(100)"),
    Column("due_date", "DATE"),
)
Table("tags", Column("id", "INTEGER", primary_key=True), Column("name", "TEXT"))
""", setup=["CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)"])

    result = run('schema', 'apply', '--path', path)

    assert result.exit_code == 0, result.output
    assert migration_names(tmp_path) == ['001_schema_tasks_tags.sql']
    assert columns(db, 'tasks') == ['id', 'title', 'due_date']
    assert db.has_table('tags')
    assert "1 change(s) need review and were left out" in result.output
    text = open(tmp_path / 'migrations' / '001_schema_tasks_tags.sql').read()
    assert 'REVIEW' not in text

    result = run('schema', 'diff', '--path', path)
    assert "title: type TEXT → VARCHAR(100)" in result.output
    assert "0 additive, 1 need review" in result.output


def test_apply_refuses_without_auto_migrate(tmp_path):
    path, db = make_project(tmp_path, 'Table("t", Column("id", "INTEGER"))\n', auto_migrate=False)

    result = run('schema', 'apply', '--database', 'default', '--path', path)

    assert result.exit_code != 0
    assert "auto_migrate off" in result.output
    assert migration_names(tmp_path) == []
    assert not db.has_table('t')


def test_failed_apply_is_rolled_back_and_its_file_removed(tmp_path):
    path, db = make_project(tmp_path, """
Table("tasks",
    Column("id", "INTEGER", primary_key=True),
    Column("title", "TEXT", unique=True),
    Column("due_date", "DATE"),
)
""", setup=["CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)",
            "INSERT INTO tasks (title) VALUES ('same'), ('same')"])

    result = run('schema', 'apply', '--path', path)

    assert result.exit_code != 0
    assert "failed and was rolled back; the file was removed" in result.output
    assert migration_names(tmp_path) == []
    # due_date ran before the failing UNIQUE index, in the same transaction
    assert columns(db, 'tasks') == ['id', 'title']
    assert db.query("SELECT COUNT(*) AS n FROM _migrations")[0]['n'] == 0


def test_apply_runs_pending_migrations_first(tmp_path):
    path, db = make_project(tmp_path, """
Table("tasks", Column("id", "INTEGER", primary_key=True), Column("title", "TEXT"))
""")
    write(tmp_path / 'migrations' / '001_tasks.sql', "CREATE TABLE tasks (id INTEGER PRIMARY KEY);")

    result = run('schema', 'apply', '--path', path)

    assert result.exit_code == 0, result.output
    assert "running 1 pending migration(s) first" in result.output
    assert migration_names(tmp_path) == ['001_tasks.sql', '002_schema_tasks.sql']
    assert columns(db, 'tasks') == ['id', 'title']


def test_apply_dry_run(tmp_path):
    path, db = make_project(tmp_path, 'Table("t", Column("id", "INTEGER"))\n')

    result = run('schema', 'apply', '--dry-run', '--path', path)

    assert result.exit_code == 0, result.output
    assert "CREATE TABLE t" in result.output
    assert migration_names(tmp_path) == []
    assert not db.has_table('t')


def test_apply_with_only_review_changes(tmp_path):
    path, _ = make_project(tmp_path, 'Table("t", Column("id", "INTEGER"))\n',
                           setup=["CREATE TABLE t (id INTEGER, legacy TEXT)"])

    result = run('schema', 'apply', '--path', path)

    assert result.exit_code == 0, result.output
    assert "nothing to apply — 1 change(s) need review" in result.output
    assert migration_names(tmp_path) == []


def test_apply_includes_new_raw_sql_once(tmp_path):
    path, db = make_project(tmp_path, 'raw_sql("v", "CREATE VIEW IF NOT EXISTS v AS SELECT 1 AS one")\n')

    assert run('schema', 'apply', '--path', path).exit_code == 0
    assert db.query("SELECT one FROM v")[0]['one'] == 1
    assert "nothing to apply" in run('schema', 'apply', '--path', path).output


# === Transactional SQLite migrations ===

def test_sqlite_migration_file_is_atomic(tmp_path):
    db = create_adapter({'type': 'sqlite', 'database': str(tmp_path / 'app.db')})
    write(tmp_path / 'migrations' / '001_partial.sql', "CREATE TABLE a (id INTEGER);\nCREATE TABLE broken (;\n")

    with pytest.raises(Exception):
        run_migrations(db, str(tmp_path))

    assert not db.has_table('a')


def test_sqlite_file_with_its_own_transaction_runs_as_written(tmp_path):
    db = create_adapter({'type': 'sqlite', 'database': str(tmp_path / 'app.db')})
    write(tmp_path / 'migrations' / '001_manual.sql',
          "BEGIN;\nCREATE TABLE a (id INTEGER);\nCOMMIT;\nCREATE TABLE b (id INTEGER);\n")

    assert run_migrations(db, str(tmp_path)) == 1
    assert db.has_table('a') and db.has_table('b')


REFERENCED = [
    "CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT)",
    "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))",
    "INSERT INTO parent VALUES (1, 'p')",
    "INSERT INTO child VALUES (1, 1)",
]

REBUILD = """PRAGMA foreign_keys = OFF;
CREATE TABLE parent__new (id INTEGER PRIMARY KEY, name VARCHAR(50));
INSERT INTO parent__new (id, name) SELECT id, name FROM parent {where};
DROP TABLE parent;
ALTER TABLE parent__new RENAME TO parent;
"""


def test_sqlite_rebuild_of_referenced_table(tmp_path):
    db = create_adapter({'type': 'sqlite', 'database': str(tmp_path / 'app.db')})
    for statement in REFERENCED:
        db.execute(statement)
    write(tmp_path / 'migrations' / '001_rebuild.sql', REBUILD.format(where=''))

    assert run_migrations(db, str(tmp_path)) == 1
    assert [c.type for c in db.get_columns('parent')] == ['INTEGER', 'VARCHAR(50)']
    assert db.query("PRAGMA foreign_key_check") == []
    assert db.query("PRAGMA foreign_keys")[0]['foreign_keys'] == 1


def test_sqlite_rebuild_that_breaks_foreign_keys_is_rolled_back(tmp_path):
    db = create_adapter({'type': 'sqlite', 'database': str(tmp_path / 'app.db')})
    for statement in REFERENCED:
        db.execute(statement)
    write(tmp_path / 'migrations' / '001_rebuild.sql', REBUILD.format(where='WHERE id <> 1'))

    with pytest.raises(ValueError, match="foreign key violation"):
        run_migrations(db, str(tmp_path))

    assert [c.type for c in db.get_columns('parent')] == ['INTEGER', 'TEXT']
    assert db.query("SELECT * FROM parent")[0]['name'] == 'p'
    assert db.query("PRAGMA foreign_keys")[0]['foreign_keys'] == 1


def test_generated_rebuild_of_referenced_table_applies(tmp_path):
    path, db = make_project(tmp_path, """
Table("parent", Column("id", "INTEGER", primary_key=True), Column("name", "VARCHAR(50)", nullable=False))
Table("child", Column("id", "INTEGER", primary_key=True), Column("parent_id", "INTEGER", ForeignKey("parent.id")))
""", auto_migrate=False, setup=REFERENCED)

    result = run('schema', 'generate', '--force', '--path', path)
    assert result.exit_code == 0, result.output
    [file] = glob.glob(str(tmp_path / 'migrations' / '*.sql'))
    text = open(file).read()
    assert "-- PRAGMA foreign_keys = OFF;" in text

    lines = [line[3:] if line.startswith('-- ') and line[3:].startswith(
        ('PRAGMA', 'CREATE', 'INSERT', 'DROP', 'ALTER', '    ', ');')) else line for line in text.splitlines()]
    write(file, '\n'.join(lines) + '\n')

    result = run('db', 'migrate', '--path', path)
    assert result.exit_code == 0, result.output
    assert "No differences" in run('schema', 'diff', '--path', path).output
    assert db.query("SELECT parent_id FROM child")[0]['parent_id'] == 1
