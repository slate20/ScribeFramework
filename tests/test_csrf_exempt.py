"""
Tests for the @csrf_exempt route decorator.
"""

import json

from scribe.app import create_app

APP_STPL = '''@route('/api/hook', methods=['POST'])
@csrf_exempt
{$
return {'ok': True}
$}

@route('/form', methods=['POST'])
{$
return {'ok': True}
$}
'''


def make_app(tmp_path):
    (tmp_path / 'scribe.json').write_text(json.dumps({
        'databases': {'default': {'type': 'sqlite', 'database': str(tmp_path / 'app.db'), 'migrations': False}},
        'SECRET_KEY': 'test',
    }))
    (tmp_path / 'app.stpl').write_text(APP_STPL)
    return create_app(str(tmp_path))


def test_csrf_exempt_route_accepts_post_without_token(tmp_path):
    response = make_app(tmp_path).test_client().post('/api/hook')
    assert response.status_code == 200


def test_csrf_exempt_only_exempts_its_own_route(tmp_path):
    # Every route handler used to share one name, so exempting one exempted all of them
    response = make_app(tmp_path).test_client().post('/form')
    assert response.status_code == 400
