"""
Tests for schema files: the DSL, loading, introspection, diff, pull, and the schema CLI.
"""

import json
import os
import re

import pytest
from click.testing import CliRunner

from scribe.cli import cli
from scribe.database import create_adapter, ColumnInfo, IndexInfo, ForeignKeyInfo
from scribe.schema import Table, Column, Index, ForeignKey, sql, SchemaError
from scribe.schema.diff import diff_schema
from scribe.schema.dsl import SchemaDefinition
from scribe.schema.introspect import LiveTable, read_live_schema
from scribe.schema.loader import load_schema
from scribe.schema.normalize import (
    default_to_python, declared_default_sql, normalize_default, normalize_type,
)
from scribe.schema.writer import pull_into_file


def write(path, content):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def schema_file(tmp_path, body):
    path = tmp_path / 'schemas' / 'schema_default.py'
    write(path, "from scribe.schema import Table, Column, Index, ForeignKey, sql, raw_sql, unmanaged\n\n" + body)
    return str(path)


def sqlite(tmp_path, *statements):
    db = create_adapter({'type': 'sqlite', 'database': str(tmp_path / 'app.db')})
    for statement in statements:
        db.execute(statement)
    return db


def kinds(result):
    return sorted((c.kind, c.table, c.column) for c in result.changes)


# === DSL and loading ===

def test_dsl_objects_register_only_while_loading(tmp_path):
    Table("outside", Column("id", "INTEGER"))  # no error, registers nothing

    definition = load_schema(schema_file(tmp_path, """
Table("users", Column("id", "INTEGER", primary_key=True), Column("email", "TEXT", unique=True))
Table("audit", managed=False)
unmanaged("legacy")
Index("idx_users_email", "users", ["email"])
raw_sql("view", "CREATE VIEW v AS SELECT 1")
"""))

    assert list(definition.tables) == ['users', 'audit']
    assert [t.name for t in definition.managed_tables] == ['users']
    assert definition.unmanaged == {'legacy': 'legacy'}
    assert [i.name for i in definition.indexes] == ['idx_users_email']
    assert list(definition.raw_sql) == ['view']


def test_dsl_needs_no_imports(tmp_path):
    path = tmp_path / 'schemas' / 'schema_default.py'
    write(path, 'scope(include=["t*"])\nTable("t", Column("id", "INTEGER"))\n')
    definition = load_schema(str(path))
    assert list(definition.tables) == ['t'] and definition.scope.include == ['t*']


def test_reloading_does_not_duplicate(tmp_path):
    path = schema_file(tmp_path, 'Table("users", Column("id", "INTEGER"))\n')
    load_schema(path)
    assert list(load_schema(path).tables) == ['users']


@pytest.mark.parametrize('body, message', [
    ('Table("t", Column("a", "TEXT"))\nTable("T", Column("a", "TEXT"))', "declared more than once"),
    ('Table("t", Column("a", "TEXT"), Column("A", "TEXT"))', "defined twice"),
    ('Table("t")', "needs at least one Column"),
    ('Table("t", Column("a", "TEXT", "oops"))', "Only ForeignKey"),
    ('Table("t", Column("a", "TEXT", default=[1]))', "default must be"),
    ('Table("t", Column("a", "TEXT", ForeignKey("users")))', "must name a column"),
    ('Index("i", "missing", ["a"])', "refers to table 'missing'"),
    ('Table("t", Column("a", "TEXT"))\nIndex("i", "t", ["b"])', "refers to column 'b'"),
    ('Table("t", Column("a", "TEXT", nullabel=False))', "Column() got an unexpected keyword"),
])
def test_invalid_schema_files(tmp_path, body, message):
    with pytest.raises(SchemaError, match=re.escape(message)):
        load_schema(schema_file(tmp_path, body))


def test_errors_include_the_line_number(tmp_path):
    path = schema_file(tmp_path, '\n\nTable("t", Column("a", "TEXT", "oops"))\n')
    with pytest.raises(SchemaError, match=r"schema_default\.py:5: "):
        load_schema(path)


def test_sql_expression_repr():
    assert repr(sql("CURRENT_TIMESTAMP")) == 'sql("CURRENT_TIMESTAMP")'


# === Normalization ===

@pytest.mark.parametrize('declared, live', [
    ('varchar(255)', 'character varying(255)'),
    ('VARCHAR( 255 )', 'character varying(255)'),
    ('INT', 'integer'),
    ('decimal(12, 2)', 'numeric(12,2)'),
    ('timestamp', 'timestamp without time zone'),
    ('timestamptz', 'timestamp with time zone'),
    ('timestamp(3)', 'timestamp(3) without time zone'),
    ('bool', 'boolean'),
    ('char', 'character(1)'),
    ('int[]', 'integer[]'),
])
def test_postgresql_type_aliases(declared, live):
    assert normalize_type(declared, 'postgresql')[0] == normalize_type(live, 'postgresql')[0]


def test_postgresql_serial_implies_autoincrement():
    assert normalize_type('BIGSERIAL', 'postgresql') == ('bigint', True)
    assert normalize_type('integer', 'postgresql') == ('integer', False)


def test_mssql_and_sqlite_types():
    assert normalize_type('INTEGER', 'mssql')[0] == 'int'
    assert normalize_type('NVARCHAR(MAX)', 'mssql')[0] == 'nvarchar(max)'
    # SQLite reports the declared type verbatim, so only spelling is normalized
    assert normalize_type('Numeric(12, 2)', 'sqlite')[0] == 'numeric(12,2)'
    assert normalize_type('INT', 'sqlite')[0] != normalize_type('INTEGER', 'sqlite')[0]


@pytest.mark.parametrize('dialect, live, expected', [
    ('mssql', '((0))', '0'),
    ('mssql', "(N'open')", "'open'"),
    ('mssql', '(getdate())', 'GETDATE()'),
    ('postgresql', "'open'::text", "'open'"),
    ('postgresql', "'x'::character varying", "'x'"),
    ('postgresql', "(0)::numeric(12,2)", '0'),
    ('postgresql', 'true', '1'),
    ('postgresql', 'now()', 'CURRENT_TIMESTAMP'),
    ('sqlite', 'NULL', None),
    ('sqlite', 'TRUE', '1'),
    ('sqlite', '1.50', '1.5'),
    ('sqlite', "'it''s'", "'it''s'"),
])
def test_normalize_default(dialect, live, expected):
    assert normalize_default(live, dialect) == expected


@pytest.mark.parametrize('value, dialect, live', [
    ("open", 'postgresql', "'open'::text"),
    (True, 'postgresql', 'true'),
    (True, 'sqlite', '1'),
    (False, 'mssql', '((0))'),
    (0, 'mssql', '((0))'),
    (sql("CURRENT_TIMESTAMP"), 'sqlite', 'current_timestamp'),
    ("it's", 'sqlite', "'it''s'"),
])
def test_declared_defaults_match_live(value, dialect, live):
    assert normalize_default(declared_default_sql(value, dialect), dialect) == normalize_default(live, dialect)


def test_default_to_python():
    assert default_to_python("'open'::text", 'postgresql') == "open"
    assert default_to_python("'it''s'", 'sqlite') == "it's"
    assert default_to_python('((5))', 'mssql') == 5
    assert default_to_python('true', 'postgresql', 'boolean') is True
    assert default_to_python('(getdate())', 'mssql') == sql('getdate()')
    assert default_to_python('NULL', 'sqlite') is None


# === SQLite introspection ===

def test_sqlite_indexes_and_foreign_keys(tmp_path):
    db = sqlite(
        tmp_path,
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT)",
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users, "
        "status TEXT, code TEXT, UNIQUE (status, code))",
        "CREATE INDEX idx_orders_status ON orders (status)",
        "CREATE INDEX idx_users_lower ON users (LOWER(name))",
    )

    users = {c.name: c for c in db.get_columns('users')}
    assert users['id'].autoincrement and not users['email'].autoincrement
    assert not any(c.autoincrement for c in db.get_columns('orders'))

    by_name = {i.name: i for i in db.get_indexes('orders')}
    assert by_name['idx_orders_status'] == IndexInfo('idx_orders_status', ['status'], False, 'index')
    composite = [i for i in by_name.values() if i.origin == 'unique']
    assert composite[0].columns == ['status', 'code'] and composite[0].unique

    expression = [i for i in db.get_indexes('users') if i.name == 'idx_users_lower'][0]
    assert expression.columns == [None]

    fks = db.get_foreign_keys('orders')
    assert fks == [ForeignKeyInfo(columns=['user_id'], ref_table='users', ref_columns=['id'])]


def test_live_schema_skips_internal_tables(tmp_path):
    db = sqlite(tmp_path, "CREATE TABLE a (id INTEGER PRIMARY KEY AUTOINCREMENT)",
                "CREATE TABLE _migrations (id INTEGER)")
    db.execute("INSERT INTO a DEFAULT VALUES")  # creates sqlite_sequence
    assert list(read_live_schema(db)) == ['a']


# === Diff ===

def test_create_table_and_its_indexes(tmp_path):
    definition = load_schema(schema_file(tmp_path, """
Table("orders", Column("id", "INTEGER", primary_key=True), Column("status", "TEXT"))
Index("idx_orders_status", "orders", ["status"])
"""))
    result = diff_schema(definition, {}, 'sqlite')

    assert kinds(result) == [('add_index', 'orders', None), ('create_table', 'orders', None)]
    assert all(c.additive for c in result.changes)


def test_column_changes(tmp_path):
    db = sqlite(tmp_path, "CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT, b TEXT NOT NULL, c TEXT DEFAULT 'x', old TEXT)")
    definition = load_schema(schema_file(tmp_path, """
Table("t",
    Column("id", "INTEGER", primary_key=True),
    Column("a", "VARCHAR(10)"),
    Column("b", "TEXT"),
    Column("c", "TEXT", default="y"),
    Column("new_nullable", "INTEGER"),
    Column("new_required", "TEXT", nullable=False),
)
"""))
    result = diff_schema(definition, read_live_schema(db), 'sqlite')
    changes = {(c.kind, c.column): c for c in result.changes}

    assert changes[('alter_column_type', 'a')].description == "type TEXT → VARCHAR(10)"
    assert changes[('alter_column_nullable', 'b')].description == "allow NULL"
    assert changes[('alter_column_default', 'c')].description == "default 'x' → 'y'"
    assert changes[('add_column', 'new_nullable')].additive
    assert not changes[('add_column', 'new_required')].additive
    assert changes[('drop_column', 'old')].destructive
    assert not any(c.additive for k, c in changes.items() if k[0].startswith(('alter', 'drop')))


def test_possible_rename(tmp_path):
    db = sqlite(tmp_path, "CREATE TABLE t (id INTEGER PRIMARY KEY, password_hash TEXT)")
    definition = load_schema(schema_file(tmp_path, """
Table("t", Column("id", "INTEGER", primary_key=True), Column("pw_hash", "TEXT"))
"""))
    result = diff_schema(definition, read_live_schema(db), 'sqlite')

    assert len(result.changes) == 2
    assert all("possible rename of password_hash → pw_hash" in c.description for c in result.changes)
    assert not any(c.additive for c in result.changes)


def test_index_unique_and_foreign_key_changes(tmp_path):
    db = sqlite(
        tmp_path,
        "CREATE TABLE users (id INTEGER PRIMARY KEY)",
        "CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT UNIQUE, b TEXT, user_id INTEGER REFERENCES users(id), "
        "owner_id INTEGER)",
        "CREATE INDEX idx_extra ON t (b)",
        "CREATE INDEX idx_changed ON t (a)",
    )
    definition = load_schema(schema_file(tmp_path, """
Table("users", Column("id", "INTEGER", primary_key=True))
Table("t",
    Column("id", "INTEGER", primary_key=True),
    Column("a", "TEXT"),
    Column("b", "TEXT", unique=True),
    Column("user_id", "INTEGER"),
    Column("owner_id", "INTEGER", ForeignKey("users.id")),
)
Index("idx_changed", "t", ["a", "b"])
Index("idx_new", "t", ["b"])
"""))
    result = diff_schema(definition, read_live_schema(db), 'sqlite')
    changes = {(c.kind, c.column or getattr(c.declared, 'name', None) or c.live.name): c for c in result.changes}

    assert set(changes) == {
        ('alter_index', 'idx_changed'), ('add_index', 'idx_new'), ('drop_index', 'idx_extra'),
        ('add_unique', 'b'), ('drop_unique', 'a'),
        ('drop_foreign_key', 'user_id'), ('add_foreign_key', 'owner_id'),
    }
    assert changes[('add_index', 'idx_new')].additive
    assert changes[('add_unique', 'b')].additive
    # SQLite can't add a foreign key to an existing column without rebuilding the table
    assert not changes[('add_foreign_key', 'owner_id')].additive


def test_unmanaged_and_untracked_tables(tmp_path):
    db = sqlite(tmp_path, "CREATE TABLE a (id INTEGER)", "CREATE TABLE b (id INTEGER)",
                "CREATE TABLE c (id INTEGER)", "CREATE TABLE d (id INTEGER)")
    definition = load_schema(schema_file(tmp_path, """
Table("a", Column("id", "TEXT"), managed=False)
unmanaged("b")
Table("c", Column("id", "INTEGER"))
"""))
    result = diff_schema(definition, read_live_schema(db), 'sqlite')

    assert result.changes == []
    assert result.in_sync == ['c']
    assert sorted(result.unmanaged) == ['a', 'b']
    assert result.untracked == ['d']


def test_primary_key_change(tmp_path):
    db = sqlite(tmp_path, "CREATE TABLE t (a INTEGER, b INTEGER, PRIMARY KEY (a, b))")
    definition = load_schema(schema_file(tmp_path, """
Table("t", Column("a", "INTEGER", primary_key=True), Column("b", "INTEGER", nullable=False))
"""))
    assert kinds(diff_schema(definition, read_live_schema(db), 'sqlite')) == [('alter_primary_key', 't', None)]


def test_postgresql_spelling_differences_are_not_changes():
    definition = SchemaDefinition()
    definition.add('table', Table(
        "orders",
        Column("id", "SERIAL", primary_key=True),
        Column("code", "varchar(20)", nullable=False),
        Column("status", "TEXT", default="open"),
        Column("paid", "BOOLEAN", default=False),
        Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
    ))
    live = {'orders': LiveTable('orders', columns=[
        ColumnInfo('id', 'integer', nullable=False, primary_key=True, autoincrement=True),
        ColumnInfo('code', 'character varying(20)', nullable=False),
        ColumnInfo('status', 'text', default="'open'::text"),
        ColumnInfo('paid', 'boolean', default='false'),
        ColumnInfo('created_at', 'timestamp without time zone', default='now()'),
    ], indexes=[IndexInfo('orders_pkey', ['id'], True, 'primary_key')])}

    assert diff_schema(definition, live, 'postgresql').changes == []


def test_mssql_spelling_differences_are_not_changes():
    definition = SchemaDefinition()
    definition.add('table', Table(
        "orders",
        Column("id", "INTEGER", primary_key=True, autoincrement=True),
        Column("qty", "int", default=0),
        Column("name", "NVARCHAR(100)", default="x"),
    ))
    live = {'orders': LiveTable('orders', columns=[
        ColumnInfo('id', 'int', nullable=False, primary_key=True, autoincrement=True),
        ColumnInfo('qty', 'int', default='((0))'),
        ColumnInfo('name', 'nvarchar(100)', default="(N'x')"),
    ])}

    assert diff_schema(definition, live, 'mssql').changes == []


# === Pull ===

RICH_SCHEMA = [
    "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, "
    "active BOOLEAN DEFAULT 1, note TEXT DEFAULT 'it''s', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), "
    "total NUMERIC(12,2) NOT NULL DEFAULT 0, status TEXT DEFAULT 'open')",
    "CREATE INDEX idx_orders_status ON orders (status)",
    "CREATE UNIQUE INDEX idx_orders_user_status ON orders (user_id, status)",
    "CREATE TABLE pairs (a INTEGER, b INTEGER, PRIMARY KEY (a, b))",
]


def test_pull_round_trips_with_no_differences(tmp_path):
    db = sqlite(tmp_path, *RICH_SCHEMA)
    path = str(tmp_path / 'schemas' / 'schema_default.py')

    added, skipped = pull_into_file(path, 'default', 'sqlite', list(read_live_schema(db).values()))
    assert sorted(added) == ['orders', 'pairs', 'users'] and skipped == []

    with open(path) as f:
        content = f.read()
    assert content.count('    managed=False,') == 3
    write(path, content.replace('    managed=False,', '    managed=True,'))

    result = diff_schema(load_schema(path), read_live_schema(db), 'sqlite')
    assert result.changes == [], [c.description for c in result.changes]
    assert sorted(result.in_sync) == ['orders', 'pairs', 'users']


def test_pull_appends_without_touching_existing_declarations(tmp_path):
    db = sqlite(tmp_path, "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    path = schema_file(tmp_path, '# my notes\nTable("users", Column("id", "INTEGER", primary_key=True))\n')
    with open(path) as f:
        original = f.read()

    db.execute("CREATE TABLE audit (id INTEGER)")
    added, skipped = pull_into_file(path, 'default', 'sqlite', list(read_live_schema(db).values()))

    assert added == ['audit'] and skipped == ['users']
    with open(path) as f:
        content = f.read()
    assert content.startswith(original.rstrip('\n'))
    assert 'Added by `scribe schema pull`' in content
    assert list(load_schema(path).tables) == ['users', 'audit']


def test_pull_restores_the_file_if_the_result_does_not_load(tmp_path):
    db = sqlite(tmp_path, "CREATE TABLE audit (id INTEGER)")
    path = str(tmp_path / 'schemas' / 'schema_default.py')
    # Shadowing a DSL name breaks the code pull appends
    write(path, "Column = None\n")

    with pytest.raises(SchemaError):
        pull_into_file(path, 'default', 'sqlite', list(read_live_schema(db).values()))
    with open(path) as f:
        assert f.read() == "Column = None\n"


# === CLI ===

def make_project(tmp_path, databases=None):
    databases = databases or {'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')}}
    write(tmp_path / 'scribe.json', json.dumps({'databases': databases}))
    return str(tmp_path)


def run(*args):
    return CliRunner().invoke(cli, list(args))


def test_commands_without_schemas_dir(tmp_path):
    path = make_project(tmp_path)
    for command in ('diff', 'status'):
        result = run('schema', command, '--path', path)
        assert result.exit_code == 0
        assert "No schemas/ directory" in result.output


def test_init_creates_files_without_overwriting(tmp_path):
    path = make_project(tmp_path, {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')},
        'analytics': {'type': 'postgresql'},
    })
    write(tmp_path / 'schemas' / 'schema_default.py', "# mine\n")

    result = run('schema', 'init', '--path', path)

    assert result.exit_code == 0, result.output
    assert "schemas/schema_default.py already exists" in result.output
    assert "Created schemas/schema_analytics.py" in result.output
    assert (tmp_path / 'schemas' / 'schema_default.py').read_text() == "# mine\n"
    assert load_schema(str(tmp_path / 'schemas' / 'schema_analytics.py')).tables == {}


def test_pull_diff_status_flow(tmp_path):
    path = make_project(tmp_path)
    db = sqlite(tmp_path, "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")

    result = run('schema', 'pull', '--path', path)
    assert result.exit_code == 0, result.output
    assert "added 1 table(s)" in result.output

    file = tmp_path / 'schemas' / 'schema_default.py'
    file.write_text(file.read_text().replace('managed=False', 'managed=True')
                    + '\nTable("orders", Column("id", "INTEGER", primary_key=True))\n')
    db.execute("CREATE TABLE audit (id INTEGER)")

    result = run('schema', 'diff', '--path', path)
    assert result.exit_code == 0, result.output
    assert "orders\n    + create table (1 columns)" in result.output
    assert "1 additive, 0 need review" in result.output

    result = run('schema', 'status', '--path', path)
    assert result.exit_code == 0, result.output
    assert "managed:     2 table(s) — 1 in sync, 1 with changes (orders)" in result.output
    assert "untracked:   1 table(s)" in result.output and "audit" in result.output
    assert "migrations:  0 pending" in result.output

    # diff and status never write to the database
    assert sorted(db.get_tables()) == ['audit', 'users']


def test_diff_reports_schema_file_errors(tmp_path):
    path = make_project(tmp_path)
    write(tmp_path / 'schemas' / 'schema_default.py', 'Table("t")\n')

    result = run('schema', 'diff', '--path', path)

    assert result.exit_code != 0
    assert "a managed table needs at least one Column" in result.output


def test_diff_for_connection_without_schema_file(tmp_path):
    path = make_project(tmp_path)
    os.makedirs(tmp_path / 'schemas')

    result = run('schema', 'diff', '--database', 'default', '--path', path)

    assert result.exit_code != 0
    assert "No schema file for 'default'" in result.output


def test_unknown_connection(tmp_path):
    path = make_project(tmp_path)
    result = run('schema', 'pull', '--database', 'nope', '--path', path)
    assert result.exit_code != 0
    assert "Database connection 'nope' not found" in result.output


# === scope() ===

from scribe.schema.dsl import Scope
from scribe.schema.introspect import read_live_schema_counted
from scribe.schema.writer import render_scope


@pytest.mark.parametrize('pattern, table, schema, expected', [
    ('orders', 'orders', None, True),
    ('ORDERS', 'orders', None, True),
    ('orders*', 'order_lines', None, False),
    ('order*', 'order_lines', None, True),
    # Patterns without a dot match the table name in any schema
    ('*_backup', 'reporting.daily_backup', 'public', True),
    ('orders', 'reporting.orders', 'public', True),
    # Patterns with a dot match schema.table; unqualified tables are in the default schema
    ('reporting.*', 'reporting.daily_sales', 'public', True),
    ('reporting.*', 'daily_sales', 'public', False),
    ('public.*', 'orders', 'public', True),
    ('public.orders', 'reporting.orders', 'public', False),
    ('*.audit_*', 'hr.audit_log', 'public', True),
])
def test_scope_patterns(pattern, table, schema, expected):
    assert Scope(include=[pattern]).matches(table, schema) is expected


def test_scope_include_and_exclude():
    selected = Scope(include=["orders*", "reporting.*"], exclude=["*_backup"])
    assert selected.matches("orders", "public")
    assert not selected.matches("orders_backup", "public")
    assert not selected.matches("reporting.daily_backup", "public")
    assert selected.matches("reporting.daily", "public")
    assert not selected.matches("customers", "public")
    # Without include, everything not excluded is in scope
    assert Scope(exclude=["tmp_*"]).matches("customers")
    assert not Scope(exclude=["tmp_*"]).matches("tmp_import")


def test_declared_tables_are_always_in_scope(tmp_path):
    definition = load_schema(schema_file(tmp_path, """
scope(include=["orders"])
Table("legacy", Column("id", "INTEGER"), managed=False)
"""))
    assert definition.in_scope("orders") and definition.in_scope("legacy")
    assert not definition.in_scope("customers")


@pytest.mark.parametrize('body, message', [
    ('scope(include=["a"])\nscope(include=["b"])', "only be used once"),
    ('scope(include=[1])', "list of table name patterns"),
    ('scope(include=[""])', "list of table name patterns"),
])
def test_invalid_scope(tmp_path, body, message):
    with pytest.raises(SchemaError, match=message):
        load_schema(schema_file(tmp_path, body))


def test_render_scope():
    assert render_scope(Scope(include=["orders", "hr_*"])) == 'scope(include=["orders", "hr_*"])\n'
    assert render_scope(Scope(exclude=["*_backup"])) == 'scope(exclude=["*_backup"])\n'
    long = render_scope(Scope(include=[f"table_number_{i}" for i in range(8)]))
    assert long.startswith('scope(\n    include=[\n        "table_number_0",\n')


def test_filter_is_applied_before_reading_tables(tmp_path):
    db = sqlite(tmp_path, "CREATE TABLE orders (id INTEGER)", "CREATE TABLE customers (id INTEGER)",
                "CREATE TABLE tmp_import (id INTEGER)")
    read = []
    original = db.get_columns
    db.get_columns = lambda table: read.append(table) or original(table)

    live, total = read_live_schema_counted(db, Scope(exclude=["tmp_*", "customers"]).matches)

    assert list(live) == ['orders'] and total == 3
    assert read == ['orders']


def test_pull_with_include_writes_scope(tmp_path):
    path = make_project(tmp_path)
    sqlite(tmp_path, "CREATE TABLE orders (id INTEGER)", "CREATE TABLE order_lines (id INTEGER)",
           "CREATE TABLE orders_backup (id INTEGER)", "CREATE TABLE customers (id INTEGER)")

    result = run('schema', 'pull', '--include', 'order*', '--exclude', '*_backup', '--path', path)

    assert result.exit_code == 0, result.output
    assert "(2 of 4 tables in scope)" in result.output
    definition = load_schema(str(tmp_path / 'schemas' / 'schema_default.py'))
    assert sorted(definition.tables) == ['order_lines', 'orders']
    assert definition.scope.include == ['order*'] and definition.scope.exclude == ['*_backup']

    # Later pulls follow the scope in the file, and flags are refused
    result = run('schema', 'pull', '--include', 'customers', '--path', path)
    assert result.exit_code != 0 and "Edit (or add) the scope(" in result.output
    assert "no new tables" in run('schema', 'pull', '--path', path).output


def test_status_reports_scope_and_only_in_scope_untracked(tmp_path):
    path = make_project(tmp_path)
    sqlite(tmp_path, "CREATE TABLE orders (id INTEGER)", "CREATE TABLE order_notes (id INTEGER)",
           "CREATE TABLE customers (id INTEGER)")
    write(tmp_path / 'schemas' / 'schema_default.py', 'scope(include=["order*"])\nTable("orders", Column("id", "INTEGER"))\n')

    result = run('schema', 'status', '--path', path)

    assert result.exit_code == 0, result.output
    assert "scope:       2 of 3 database table(s)" in result.output
    assert "untracked:   1 table(s)" in result.output and "order_notes" in result.output
    assert "customers" not in result.output
