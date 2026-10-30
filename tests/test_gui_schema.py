"""
Tests for the IDE's Schema panel API and the managed toggle it uses.
"""

import glob
import json
import os

import pytest

from scribe.app import create_standalone_gui_app
from scribe.database import create_adapter
from scribe.schema import SchemaError
from scribe.schema.loader import load_schema
from scribe.schema.writer import set_table_managed, table_lines

HEADER = "from scribe.schema import Table, Column, Index, ForeignKey, sql, raw_sql, unmanaged\n\n"


def write(path, content):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


@pytest.fixture
def project(tmp_path):
    def make(body=None, auto_migrate=True, setup=(), migrations=True):
        block = {'type': 'sqlite', 'database': str(tmp_path / 'app.db'), 'auto_migrate': auto_migrate}
        if not migrations:
            block['migrations'] = False
        write(tmp_path / 'scribe.json', json.dumps({'databases': {'default': block}, 'SECRET_KEY': 'x'}))
        if body is not None:
            write(tmp_path / 'schemas' / 'schema_default.py', HEADER + body)
        os.makedirs(tmp_path / 'migrations', exist_ok=True)
        db = create_adapter({'type': 'sqlite', 'database': str(tmp_path / 'app.db')})
        for statement in setup:
            db.execute(statement)
        db.close()
        app = create_standalone_gui_app(str(tmp_path))
        app.config['TESTING'] = True
        return app.test_client()
    return make


def migration_names(tmp_path):
    return [os.path.basename(p) for p in sorted(glob.glob(str(tmp_path / 'migrations' / '*.sql')))]


TASKS = '''Table("tasks",
    Column("id", "INTEGER", primary_key=True, autoincrement=True),
    Column("title", "TEXT", nullable=False),
)
'''


# === Reading ===

def test_list_connections(project):
    client = project(TASKS)
    data = client.get('/api/schema').get_json()
    assert data['schemas_dir'] is True
    [conn] = data['connections']
    assert conn['name'] == 'default'
    assert conn['exists'] is True
    assert conn['file'] == 'schemas/schema_default.py'
    assert conn['apply_refusal'] is None


def test_schema_shows_missing_table(project):
    data = project(TASKS).get('/api/schema/default').get_json()
    [table] = data['tables']
    assert table['status'] == 'missing'
    assert table['line'] == 3
    assert table['in_database'] is False
    assert [c['name'] for c in table['columns']] == ['id', 'title']
    assert table['changes'][0]['kind'] == 'create_table'
    assert data['counts'] == {'additive': 1, 'review': 0, 'destructive': 0}


def test_schema_shows_drift_and_untracked(project):
    client = project(TASKS, setup=[
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, extra TEXT)",
        "CREATE TABLE notes (id INTEGER)",
    ])
    data = client.get('/api/schema/default').get_json()
    [table] = data['tables']
    assert table['status'] == 'changed'
    assert table['changes'][0]['symbol'] == '-'
    assert data['untracked'] == ['notes']
    assert data['counts']['destructive'] == 1


def test_schema_reports_broken_file(project):
    client = project('Table("x", Column("id"))\n')
    data = client.get('/api/schema/default').get_json()
    assert data['error'].startswith('schemas/schema_default.py:3: ')


def test_unknown_connection(project):
    response = project(TASKS).get('/api/schema/nope')
    assert response.status_code == 404


# === Init and pull ===

def test_init_then_pull(project, tmp_path):
    client = project(setup=["CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)"])
    assert client.get('/api/schema/default').get_json()['exists'] is False

    assert client.post('/api/schema/default/init').status_code == 200
    assert client.post('/api/schema/default/init').status_code == 409

    data = client.post('/api/schema/default/pull').get_json()
    assert data['added'] == ['notes']
    assert not load_schema(str(tmp_path / 'schemas' / 'schema_default.py')).tables['notes'].managed


# === Managed toggle ===

def test_toggle_managed_through_api(project, tmp_path):
    client = project(TASKS, setup=["CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL)"])
    file = tmp_path / 'schemas' / 'schema_default.py'

    data = client.post('/api/schema/default/managed', json={'table': 'tasks', 'managed': False}).get_json()
    assert data['changed'] is True
    assert not load_schema(str(file)).tables['tasks'].managed
    assert client.get('/api/schema/default').get_json()['tables'][0]['status'] == 'unmanaged'

    client.post('/api/schema/default/managed', json={'table': 'tasks', 'managed': True})
    assert load_schema(str(file)).tables['tasks'].managed


@pytest.mark.parametrize('source, expected', [
    # Multi-line with trailing comma
    ('Table("t",\n    Column("id", "INTEGER"),\n)\n',
     'Table("t",\n    Column("id", "INTEGER"),\n    managed=False,\n)\n'),
    # Multi-line without trailing comma
    ('Table("t",\n    Column("id", "INTEGER")\n)\n',
     'Table("t",\n    Column("id", "INTEGER"),\n    managed=False\n)\n'),
    # Single line
    ('Table("t", Column("id", "INTEGER"))\n',
     'Table("t", Column("id", "INTEGER"), managed=False)\n'),
    # Existing keyword is replaced in place
    ('Table("t", Column("id", "INTEGER"), managed=True)  # keep\n',
     'Table("t", Column("id", "INTEGER"), managed=False)  # keep\n'),
])
def test_set_table_managed_layouts(tmp_path, source, expected):
    file = tmp_path / 'schema_default.py'
    write(file, HEADER + source)
    assert set_table_managed(str(file), 't', False) is True
    assert read(file) == HEADER + expected


def test_set_table_managed_handles_non_ascii(tmp_path):
    file = tmp_path / 'schema_default.py'
    write(file, HEADER + 'Table("t", Column("naïve", "TEXT", default="é"))\n')
    set_table_managed(str(file), 't', False)
    assert read(file).endswith('default="é"), managed=False)\n')


def test_set_table_managed_no_change(tmp_path):
    file = tmp_path / 'schema_default.py'
    write(file, HEADER + 'Table("t", Column("id", "INTEGER"))\n')
    assert set_table_managed(str(file), 't', True) is False


def test_set_table_managed_refusals(tmp_path):
    file = tmp_path / 'schema_default.py'
    original = HEADER + 'Table("t", managed=False)\nunmanaged("legacy")\n'
    write(file, original)

    with pytest.raises(SchemaError, match="needs at least one Column"):
        set_table_managed(str(file), 't', True)
    assert read(file) == original

    with pytest.raises(SchemaError, match="unmanaged"):
        set_table_managed(str(file), 'legacy', True)
    with pytest.raises(SchemaError, match="isn't declared"):
        set_table_managed(str(file), 'nope', True)


def test_table_lines(tmp_path):
    file = tmp_path / 'schema_default.py'
    write(file, HEADER + 'Table("A", Column("id", "INTEGER"))\n\nTable("b", managed=False)\n')
    assert table_lines(str(file)) == {'a': 3, 'b': 5}


# === Generate and apply ===

def test_generate_preview_and_write(project, tmp_path):
    client = project(TASKS)
    preview = client.post('/api/schema/default/generate', json={'dry_run': True}).get_json()
    assert 'CREATE TABLE' in preview['sql']
    assert migration_names(tmp_path) == []

    data = client.post('/api/schema/default/generate', json={'name': 'add tasks'}).get_json()
    assert data['file'] == 'migrations/001_add_tasks.sql'
    assert 'auto_migrate is on' in data['message']

    # The new file is pending, so the diff would generate it again
    response = client.post('/api/schema/default/generate', json={})
    assert response.status_code == 409
    assert 'pending' in response.get_json()['error']


def test_generate_refused_without_migrations(project):
    response = project(TASKS, migrations=False).post('/api/schema/default/generate', json={})
    assert response.status_code == 409
    assert 'Migrations are not enabled' in response.get_json()['error']


def test_generate_review_only_needs_force(project, tmp_path):
    client = project(TASKS, setup=[
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, extra TEXT)",
    ])
    response = client.post('/api/schema/default/generate', json={})
    assert response.status_code == 409
    assert migration_names(tmp_path) == []
    assert client.post('/api/schema/default/generate', json={'force': True}).status_code == 200
    assert len(migration_names(tmp_path)) == 1


def test_apply_runs_additive_changes(project, tmp_path):
    client = project(TASKS)
    preview = client.post('/api/schema/default/apply', json={'dry_run': True}).get_json()
    assert 'CREATE TABLE' in preview['sql']
    assert migration_names(tmp_path) == []

    data = client.post('/api/schema/default/apply', json={}).get_json()
    assert data['file'].startswith('migrations/001_')
    db = create_adapter({'type': 'sqlite', 'database': str(tmp_path / 'app.db')})
    assert db.has_table('tasks')
    db.close()
    assert client.get('/api/schema/default').get_json()['tables'][0]['status'] == 'in_sync'

    assert client.post('/api/schema/default/apply', json={}).get_json()['message'] == 'Nothing to apply'


def test_apply_refused_when_auto_migrate_off(project):
    response = project(TASKS, auto_migrate=False).post('/api/schema/default/apply', json={})
    assert response.status_code == 409
    assert 'auto_migrate off' in response.get_json()['error']


def test_apply_failure_removes_file(project, tmp_path):
    client = project(TASKS + 'raw_sql("broken", "CREATE NONSENSE")\n')
    response = client.post('/api/schema/default/apply', json={})
    assert response.status_code == 500
    assert 'rolled back' in response.get_json()['error']
    assert migration_names(tmp_path) == []


def test_run_pending_migrations(project, tmp_path):
    client = project(TASKS)
    client.post('/api/schema/default/generate', json={})
    assert client.get('/api/schema/default').get_json()['pending'] == ['001_schema_tasks.sql']

    data = client.post('/api/schema/default/migrate', json={}).get_json()
    assert data['ran'] == ['001_schema_tasks.sql']
    schema = client.get('/api/schema/default').get_json()
    assert schema['pending'] == []
    assert schema['tables'][0]['status'] == 'in_sync'
    assert client.post('/api/schema/default/migrate', json={}).get_json()['ran'] == []
