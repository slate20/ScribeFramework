"""
Tests for per-connection migrations, auto_migrate, and the db CLI commands.
"""

import json
import os

import pytest
from click.testing import CliRunner

from scribe.cli import cli, _run_startup_migrations
from scribe.database import create_adapter, DatabaseManager, SQLiteAdapter
from scribe.migrations import (
    run_migrations,
    get_pending_migrations,
    get_applied_migrations,
    get_databases_config,
    get_migration_targets,
    MigrationConfigError,
)
from scribe.migrations.runner import _MIGRATIONS_TABLE_DDL, _create_migrations_table


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def sqlite(path):
    return create_adapter({'type': 'sqlite', 'database': str(path)})


# === Config resolution ===

def test_default_connection_keeps_legacy_behavior(tmp_path):
    targets = get_migration_targets({'default': {'type': 'sqlite'}}, str(tmp_path))

    assert len(targets) == 1
    assert targets[0].path == os.path.join(str(tmp_path), 'migrations')
    assert targets[0].auto_migrate is True
    assert targets[0].auto_migrate_implicit is True


def test_other_connections_are_disabled_unless_configured(tmp_path):
    targets = get_migration_targets({
        'default': {'type': 'sqlite'},
        'analytics': {'type': 'postgresql'},
    }, str(tmp_path))

    assert [t.name for t in targets] == ['default']


def test_opted_in_connection_does_not_auto_migrate_by_default(tmp_path):
    targets = get_migration_targets({
        'analytics': {'type': 'postgresql', 'migrations': 'migrations/analytics'},
    }, str(tmp_path))

    assert targets[0].path == os.path.join(str(tmp_path), 'migrations', 'analytics')
    assert targets[0].auto_migrate is False
    assert targets[0].auto_migrate_implicit is True


def test_explicit_settings(tmp_path):
    targets = get_migration_targets({
        'default': {'type': 'postgresql', 'migrations': False},
        'analytics': {'type': 'postgresql', 'migrations': True, 'auto_migrate': True},
    }, str(tmp_path))

    assert [t.name for t in targets] == ['analytics']
    assert targets[0].path == os.path.join(str(tmp_path), 'migrations', 'analytics')
    assert targets[0].auto_migrate is True
    assert targets[0].auto_migrate_implicit is False
    assert targets[0].dialect == 'postgresql'


def test_shared_migrations_folder_is_an_error(tmp_path):
    with pytest.raises(MigrationConfigError, match="both use migrations folder"):
        get_migration_targets({
            'default': {'type': 'sqlite'},
            'other': {'type': 'sqlite', 'migrations': './migrations/'},
        }, str(tmp_path))


@pytest.mark.parametrize('block', [
    {'migrations': 5},
    {'migrations': ''},
    {'auto_migrate': 'yes'},
])
def test_invalid_settings_are_errors(tmp_path, block):
    with pytest.raises(MigrationConfigError):
        get_migration_targets({'default': {'type': 'sqlite', **block}}, str(tmp_path))


def test_databases_config_handles_legacy_key():
    assert get_databases_config({'database': {'type': 'sqlite'}}) == {'default': {'type': 'sqlite'}}
    assert get_databases_config({'databases': {'a': {}}, 'database': {}}) == {'a': {}}


# === Runner ===

def test_run_and_track_migrations(tmp_path):
    folder = tmp_path / 'migrations'
    write(str(folder / '001_a.sql'), "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    write(str(folder / '002_b.sql'), "CREATE TABLE b (id INTEGER PRIMARY KEY); INSERT INTO b (id) VALUES (1);")
    db = sqlite(tmp_path / 'app.db')

    assert get_pending_migrations(db, str(folder)) == ['001_a.sql', '002_b.sql']
    assert run_migrations(db, str(tmp_path)) == 2
    assert get_applied_migrations(db) == ['001_a.sql', '002_b.sql']
    assert get_pending_migrations(db, str(folder)) == []
    assert run_migrations(db, str(tmp_path)) == 0


def test_pending_check_is_read_only(tmp_path):
    folder = tmp_path / 'migrations'
    write(str(folder / '001_a.sql'), "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    db = sqlite(tmp_path / 'app.db')

    assert get_pending_migrations(db, str(folder)) == ['001_a.sql']
    assert db.get_tables() == []


def test_empty_folder_creates_nothing(tmp_path):
    os.makedirs(tmp_path / 'migrations')
    db = sqlite(tmp_path / 'app.db')

    assert run_migrations(db, str(tmp_path)) == 0
    assert not db.has_table('_migrations')


def test_failed_migration_is_not_recorded(tmp_path):
    folder = tmp_path / 'migrations'
    write(str(folder / '001_bad.sql'), "CREATE TABLE oops (;")
    db = sqlite(tmp_path / 'app.db')

    with pytest.raises(Exception):
        run_migrations(db, str(tmp_path))
    assert get_applied_migrations(db) == []


class RecordingAdapter:
    """Stands in for a PostgreSQL/MSSQL adapter to capture the DDL sent to it."""

    def __init__(self, dialect):
        self.dialect = dialect
        self.statements = []

    def has_table(self, name):
        return False

    def execute(self, sql, params=None):
        self.statements.append(sql)

    def commit(self):
        pass


@pytest.mark.parametrize('dialect', ['postgresql', 'mssql'])
def test_migrations_table_ddl_is_dialect_specific(dialect):
    db = RecordingAdapter(dialect)
    _create_migrations_table(db)

    assert len(db.statements) == 1
    ddl = db.statements[0]
    assert 'AUTOINCREMENT' not in ddl
    assert 'IF NOT EXISTS' not in ddl
    assert ddl == _MIGRATIONS_TABLE_DDL[dialect]


def test_unsupported_dialect_is_an_error():
    with pytest.raises(ValueError, match="not supported"):
        _create_migrations_table(RecordingAdapter('oracle'))


def test_mysql_gives_a_clear_error():
    with pytest.raises(ValueError, match="MySQL is not supported yet"):
        create_adapter({'type': 'mysql'})


# === Introspection ===

def test_sqlite_introspection(tmp_path):
    db = sqlite(tmp_path / 'app.db')
    db.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            status TEXT DEFAULT 'open'
        )
    """)

    assert 'users' in db.get_tables()
    assert db.has_table('users')
    assert not db.has_table('missing')

    columns = db.get_columns('users')
    assert [c.name for c in columns] == ['id', 'username', 'status']
    assert columns[0].primary_key and columns[0].type == 'INTEGER'
    assert columns[1].nullable is False
    assert columns[2].default == "'open'"
    assert db.get_columns('missing') == []


# === Startup behavior ===

def make_project(tmp_path, databases):
    write(str(tmp_path / 'scribe.json'), json.dumps({'databases': databases}))
    write(str(tmp_path / 'migrations' / '001_a.sql'), "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    return str(tmp_path)


def test_startup_applies_when_auto_migrate_on(tmp_path, capsys):
    path = make_project(tmp_path, {})
    manager = DatabaseManager({'databases': {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db'), 'auto_migrate': True},
    }})

    watched = _run_startup_migrations(manager, path, None)

    assert manager['default'].has_table('a')
    assert watched == [os.path.join(path, 'migrations')]


def test_startup_reports_when_auto_migrate_off(tmp_path, capsys):
    path = make_project(tmp_path, {})
    manager = DatabaseManager({'databases': {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db'), 'auto_migrate': False},
    }})

    watched = _run_startup_migrations(manager, path, None)

    assert not manager['default'].has_table('a')
    assert not manager['default'].has_table('_migrations')
    assert watched == []
    assert "1 pending migration(s) for 'default'" in capsys.readouterr().out


def test_cli_flag_overrides_auto_migrate(tmp_path):
    path = make_project(tmp_path, {})
    manager = DatabaseManager({'databases': {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db'), 'auto_migrate': False},
    }})

    _run_startup_migrations(manager, path, True)

    assert manager['default'].has_table('a')


class PretendPostgres(SQLiteAdapter):
    """SQLite underneath, but configured as postgresql (to exercise the implicit-default warning)."""

    @property
    def dialect(self):
        return 'sqlite'


class FakeManager(dict):
    pass


def pretend_postgres(tmp_path, **settings):
    adapter = PretendPostgres({'type': 'sqlite', 'database': str(tmp_path / 'app.db'), **settings})
    adapter.config['type'] = 'postgresql'
    return adapter


def test_implicit_migrations_on_non_sqlite_default_warns(tmp_path, capsys):
    path = make_project(tmp_path, {})
    adapter = pretend_postgres(tmp_path)

    _run_startup_migrations(FakeManager(default=adapter), path, None)

    out = capsys.readouterr().out
    assert "'default' (postgresql) doesn't set \"migrations\"" in out
    assert "Its 1 pending migration(s) there will run now." in out
    assert '"migrations": false' in out
    assert adapter.has_table('a')


def test_implicit_migrations_warning_without_a_folder(tmp_path, capsys):
    path = make_project(tmp_path, {})
    import shutil
    shutil.rmtree(tmp_path / 'migrations')
    adapter = pretend_postgres(tmp_path)

    _run_startup_migrations(FakeManager(default=adapter), path, None)

    out = capsys.readouterr().out
    assert "That folder doesn't exist, so nothing runs today" in out
    assert not adapter.has_table('_migrations')


def test_explicit_migrations_setting_silences_the_warning(tmp_path, capsys):
    path = make_project(tmp_path, {})
    for settings in ({'migrations': False}, {'migrations': 'migrations', 'auto_migrate': True}):
        _run_startup_migrations(FakeManager(default=pretend_postgres(tmp_path, **settings)), path, None)
        assert "doesn't set" not in capsys.readouterr().out


def test_implicit_auto_migrate_on_non_sqlite_warns(tmp_path, capsys):
    path = make_project(tmp_path, {})
    adapter = pretend_postgres(tmp_path, migrations='migrations')

    _run_startup_migrations(FakeManager(default=adapter), path, None)

    out = capsys.readouterr().out
    assert "has no 'auto_migrate' setting" in out
    assert adapter.has_table('a')


def test_sqlite_default_without_settings_does_not_warn(tmp_path, capsys):
    path = make_project(tmp_path, {})
    manager = DatabaseManager({'databases': {'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')}}})

    _run_startup_migrations(manager, path, None)

    out = capsys.readouterr().out
    assert "doesn't set" not in out and "no 'auto_migrate'" not in out


def test_commands_wont_create_migrations_for_implicit_non_sqlite_default(tmp_path):
    from scribe.cli import _implicit_migrations_refusal, _apply_refusal

    [target] = get_migration_targets({'default': {'type': 'postgresql'}}, str(tmp_path))
    assert target.needs_explicit_migrations
    assert '"migrations": "migrations"' in _implicit_migrations_refusal(target)
    assert _apply_refusal(target, 'default') == _implicit_migrations_refusal(target)

    [explicit] = get_migration_targets({'default': {'type': 'postgresql', 'migrations': True}}, str(tmp_path))
    assert not explicit.needs_explicit_migrations
    [sqlite_target] = get_migration_targets({'default': {'type': 'sqlite'}}, str(tmp_path))
    assert not sqlite_target.needs_explicit_migrations


def test_explicit_auto_migrate_on_non_sqlite_does_not_warn(tmp_path, capsys):
    path = make_project(tmp_path, {})
    adapter = PretendPostgres({'type': 'sqlite', 'database': str(tmp_path / 'app.db'), 'auto_migrate': True})
    adapter.config['type'] = 'postgresql'

    _run_startup_migrations(FakeManager(default=adapter), path, None)

    assert "has no 'auto_migrate' setting" not in capsys.readouterr().out


# === CLI ===

def test_db_migrate_uses_configured_connections(tmp_path):
    path = make_project(tmp_path, {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')},
        'analytics': {'type': 'sqlite', 'database': str(tmp_path / 'analytics.db'),
                      'migrations': 'migrations/analytics'},
        'legacy': {'type': 'sqlite', 'database': str(tmp_path / 'legacy.db')},
    })
    write(str(tmp_path / 'migrations' / 'analytics' / '001_views.sql'), "CREATE TABLE views (id INTEGER);")
    # A subfolder named after a connection that hasn't opted in must be ignored
    write(str(tmp_path / 'migrations' / 'legacy' / '001_manual.sql'), "CREATE TABLE manual (id INTEGER);")

    result = CliRunner().invoke(cli, ['db', 'migrate', '--path', path])

    assert result.exit_code == 0, result.output
    assert sqlite(tmp_path / 'app.db').has_table('a')
    assert sqlite(tmp_path / 'analytics.db').has_table('views')
    assert not sqlite(tmp_path / 'legacy.db').has_table('manual')
    assert not sqlite(tmp_path / 'legacy.db').has_table('_migrations')


def test_db_migrate_single_database(tmp_path):
    path = make_project(tmp_path, {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')},
        'analytics': {'type': 'sqlite', 'database': str(tmp_path / 'analytics.db'),
                      'migrations': 'migrations/analytics'},
    })
    write(str(tmp_path / 'migrations' / 'analytics' / '001_views.sql'), "CREATE TABLE views (id INTEGER);")

    result = CliRunner().invoke(cli, ['db', 'migrate', '--database', 'analytics', '--path', path])

    assert result.exit_code == 0, result.output
    assert sqlite(tmp_path / 'analytics.db').has_table('views')
    assert not sqlite(tmp_path / 'app.db').has_table('a')


def test_db_migrate_rejects_disabled_connection(tmp_path):
    path = make_project(tmp_path, {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')},
        'legacy': {'type': 'sqlite', 'database': str(tmp_path / 'legacy.db')},
    })

    result = CliRunner().invoke(cli, ['db', 'migrate', '--database', 'legacy', '--path', path])

    assert result.exit_code != 0
    assert "Migrations are not enabled for 'legacy'" in result.output
    assert '"migrations": "migrations/legacy"' in result.output


def test_db_migrate_failure_exits_nonzero(tmp_path):
    path = make_project(tmp_path, {'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')}})
    write(str(tmp_path / 'migrations' / '002_bad.sql'), "CREATE TABLE oops (;")

    result = CliRunner().invoke(cli, ['db', 'migrate', '--path', path])

    assert result.exit_code == 1
    assert "Error applying 002_bad.sql" in result.output


def test_db_status(tmp_path):
    path = make_project(tmp_path, {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')},
        'legacy': {'type': 'sqlite', 'database': str(tmp_path / 'legacy.db'), 'migrations': False},
    })
    write(str(tmp_path / 'migrations' / '002_b.sql'), "CREATE TABLE b (id INTEGER);")
    run_migrations(sqlite(tmp_path / 'app.db'), path)
    write(str(tmp_path / 'migrations' / '003_c.sql'), "CREATE TABLE c (id INTEGER);")

    result = CliRunner().invoke(cli, ['db', 'status', '--path', path])

    assert result.exit_code == 0, result.output
    assert "default: migrations/  auto_migrate: on (default)" in result.output
    assert "✓ 001_a.sql" in result.output
    assert "• 003_c.sql  (pending)" in result.output
    assert "legacy: migrations disabled" in result.output
    assert not sqlite(tmp_path / 'legacy.db').has_table('_migrations')


def test_new_migration_for_named_connection(tmp_path):
    path = make_project(tmp_path, {
        'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db')},
        'analytics': {'type': 'sqlite', 'database': str(tmp_path / 'analytics.db'),
                      'migrations': 'migrations/analytics'},
    })

    result = CliRunner().invoke(cli, ['db', 'new-migration', 'add_views', '--database', 'analytics', '--path', path])

    assert result.exit_code == 0, result.output
    assert os.path.exists(tmp_path / 'migrations' / 'analytics' / '001_add_views.sql')
    assert "scribe db migrate --database analytics" in result.output


def test_new_project_scaffold_has_explicit_migration_settings(tmp_path):
    result = CliRunner().invoke(cli, ['new', 'myapp', '--path', str(tmp_path)])
    assert result.exit_code == 0, result.output

    with open(tmp_path / 'myapp' / 'scribe.json') as f:
        default = json.load(f)['databases']['default']
    assert default['migrations'] == 'migrations'
    assert default['auto_migrate'] is True
