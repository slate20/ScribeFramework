"""
Tests for the persistent data directory (DATA_DIR): `data_dir` in route
code, the built-in /uploads/ route, SQLite path anchoring and .env loading
in compiled apps, and abort() keeping its status code.
"""

import io
import json
import os
import sys

import pytest

from scribe.app import create_app, create_compiled_app, resolve_data_dir
from scribe.builder.cli import render_env_example, write_env_example
from scribe.builder.stage import MAIN_PY_TEMPLATE, stage_project

APP_STPL = '''@route('/where')
{$
return {'data_dir': data_dir}
$}

@route('/upload', methods=['POST'])
@csrf_exempt
{$
import os
save_dir = os.path.join(data_dir, 'uploads', 'receipts')
os.makedirs(save_dir, exist_ok=True)
request.files['file'].save(os.path.join(save_dir, 'r.txt'))
return {'path': 'receipts/r.txt'}
$}

@route('/vars')
{$
x = 1
$}
{{ 'leaked' if data_dir is defined else 'clean' }}

@route('/gone')
{$
abort(404)
$}

@route('/forbidden')
{$
abort(403)
$}
'''


def make_project(path, database='app.db'):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'scribe.json').write_text(json.dumps({
        'databases': {'default': {'type': 'sqlite', 'database': database, 'migrations': False}},
        'SECRET_KEY': 'test',
    }))
    (path / 'app.stpl').write_text(APP_STPL)
    return path


@pytest.fixture
def dev_client(tmp_path):
    project = make_project(tmp_path / 'project', database=str(tmp_path / 'project' / 'app.db'))
    return project, create_app(str(project)).test_client()


# --- dev mode ---------------------------------------------------------------

def test_data_dir_is_project_root_in_dev(dev_client):
    project, client = dev_client
    assert client.get('/where').get_json() == {'data_dir': str(project)}


def test_upload_saved_under_data_dir_and_served(dev_client):
    project, client = dev_client
    response = client.post('/upload', data={'file': (io.BytesIO(b'receipt'), 'r.txt')})
    assert response.get_json() == {'path': 'receipts/r.txt'}
    assert (project / 'uploads' / 'receipts' / 'r.txt').read_bytes() == b'receipt'

    served = client.get('/uploads/receipts/r.txt')
    assert served.status_code == 200
    assert served.data == b'receipt'


def test_uploads_missing_and_traversal_are_404(dev_client):
    project, client = dev_client
    (project / 'uploads').mkdir()
    assert client.get('/uploads/missing.png').status_code == 404
    assert client.get('/uploads/../scribe.json').status_code == 404
    assert client.get('/uploads/%2e%2e/scribe.json').status_code == 404


def test_data_dir_not_leaked_to_jinja(dev_client):
    _, client = dev_client
    assert client.get('/vars').data.strip().endswith(b'clean')


def test_abort_keeps_its_status_code(dev_client):
    _, client = dev_client
    assert client.get('/gone').status_code == 404
    assert client.get('/forbidden').status_code == 403


def test_project_uploads_route_takes_precedence(tmp_path):
    project = make_project(tmp_path / 'project', database=str(tmp_path / 'app.db'))
    (project / 'files.stpl').write_text(
        "@route('/uploads/<path:filename>')\n{$\nreturn {'mine': filename}\n$}\n"
    )
    client = create_app(str(project)).test_client()
    assert client.get('/uploads/a/b.png').get_json() == {'mine': 'a/b.png'}


# --- compiled mode ----------------------------------------------------------

def build(tmp_path, database='app.db'):
    project = make_project(tmp_path / 'project', database=database)
    build_dir = tmp_path / 'build'
    stage_project(str(project), str(build_dir), sys.executable)
    return build_dir


def test_resolve_data_dir_frozen_uses_executable_dir(tmp_path, monkeypatch):
    assert resolve_data_dir(str(tmp_path)) == str(tmp_path)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'dist' / 'myapp'))
    assert resolve_data_dir('/some/_MEI123') == str(tmp_path / 'dist')


def test_compiled_frozen_app_stores_db_and_uploads_next_to_executable(tmp_path, monkeypatch):
    build_dir = build(tmp_path)
    dist = tmp_path / 'dist'
    dist.mkdir()
    elsewhere = tmp_path / 'cwd'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(dist / 'myapp'))

    app = create_compiled_app(str(build_dir))
    client = app.test_client()

    assert app.config['DATA_DIR'] == str(dist)
    assert app.config['databases']['default']['database'] == str(dist / 'app.db')
    assert (dist / 'app.db').exists()
    assert not (elsewhere / 'app.db').exists()

    client.post('/upload', data={'file': (io.BytesIO(b'x'), 'r.txt')})
    assert (dist / 'uploads' / 'receipts' / 'r.txt').exists()
    assert client.get('/uploads/receipts/r.txt').status_code == 200


def test_compiled_unfrozen_app_uses_base_dir(tmp_path):
    build_dir = build(tmp_path)
    app = create_compiled_app(str(build_dir))
    assert app.config['DATA_DIR'] == str(build_dir)
    assert app.config['databases']['default']['database'] == str(build_dir / 'app.db')


def test_in_memory_sqlite_is_not_anchored(tmp_path):
    build_dir = build(tmp_path, database=':memory:')
    app = create_compiled_app(str(build_dir))
    assert app.config['databases']['default']['database'] == ':memory:'


# --- launcher .env loading ----------------------------------------------------

def load_launcher():
    namespace = {'__name__': 'scribe_launcher'}
    exec(MAIN_PY_TEMPLATE, namespace)  # noqa: S102 - our own generated code
    return namespace


def test_launcher_loads_env_file_without_overriding_real_env(tmp_path, monkeypatch):
    (tmp_path / '.env').write_text(
        '# comment\n'
        'SECRET_KEY="from-file"\n'
        'SCRIBE_TEST_A=a\n'
        "SCRIBE_TEST_B='quoted'\n"
        'not a pair\n'
        '=novalue\n'
    )
    monkeypatch.setenv('SCRIBE_TEST_A', 'real')
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('SCRIBE_TEST_B', raising=False)

    load_launcher()['_load_env_file'](str(tmp_path))

    assert os.environ['SECRET_KEY'] == 'from-file'
    assert os.environ['SCRIBE_TEST_A'] == 'real'
    assert os.environ['SCRIBE_TEST_B'] == 'quoted'
    monkeypatch.delenv('SECRET_KEY')
    monkeypatch.delenv('SCRIBE_TEST_B')


def test_launcher_without_env_file_is_a_no_op(tmp_path):
    load_launcher()['_load_env_file'](str(tmp_path))


# --- scribe-build .env.example ------------------------------------------------

def test_env_example_lists_non_sqlite_passwords():
    text = render_env_example({'databases': {
        'default': {'type': 'sqlite', 'database': 'app.db'},
        'analytics': {'type': 'postgresql', 'host': 'db'},
    }})
    assert 'SECRET_KEY=\n' in text
    assert '# SCRIBE_DB_ANALYTICS_PASSWORD=' in text
    assert 'SCRIBE_DB_DEFAULT_PASSWORD' not in text


def test_env_example_is_not_overwritten(tmp_path):
    config = {'databases': {'default': {'type': 'sqlite', 'database': 'app.db'}}}
    assert write_env_example(str(tmp_path), config) is True
    (tmp_path / '.env.example').write_text('edited')
    assert write_env_example(str(tmp_path), config) is False
    assert (tmp_path / '.env.example').read_text() == 'edited'
