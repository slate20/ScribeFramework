"""
Tests for scribe-build staging: files that templates include have to be
copied into the build, since the compiled app resolves templates against
app_data/ instead of the project root.
"""

import json
import sys

from scribe.builder.stage import find_referenced_templates, stage_project

APP_STPL = '''@route('/')
{$
items = [1, 2]
$}
{% include 'partials/_list.html' %}
'''


def make_project(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / 'scribe.json').write_text(json.dumps({
        'databases': {'default': {'type': 'sqlite', 'database': 'app.db', 'migrations': False}},
        'SECRET_KEY': 'test',
    }))
    (tmp_path / 'app.stpl').write_text(APP_STPL)
    (tmp_path / 'base.stpl').write_text("{% include 'partials/_nav.html' %}{% block content %}{% endblock %}")
    partials = tmp_path / 'partials'
    partials.mkdir()
    (partials / '_list.html').write_text("{% for i in items %}{% include 'partials/_item.html' %}{% endfor %}")
    (partials / '_item.html').write_text("<li>{{ i }}</li>")
    (partials / '_nav.html').write_text("<nav></nav>")
    (partials / '_unused.html').write_text("not referenced")
    return tmp_path


def test_finds_includes_of_includes(tmp_path):
    make_project(tmp_path)
    found, warnings = find_referenced_templates(str(tmp_path), [APP_STPL])
    assert found == ['partials/_item.html', 'partials/_list.html']
    assert warnings == []


def test_extends_import_and_from_are_found(tmp_path):
    make_project(tmp_path)
    (tmp_path / 'macros.html').write_text("{% macro m() %}{% endmacro %}")
    (tmp_path / 'layout.html').write_text("{% block body %}{% endblock %}")
    source = ("{% extends 'layout.html' %}{% import 'macros.html' as macros %}"
              "{% from 'macros.html' import m %}")
    found, _ = find_referenced_templates(str(tmp_path), [source])
    assert found == ['layout.html', 'macros.html']


def test_warns_about_unshippable_references(tmp_path):
    make_project(tmp_path)
    source = ("{% include 'missing.html' %}{% include '../outside.html' %}"
              "{% include partial_name %}")
    found, warnings = find_referenced_templates(str(tmp_path), [source])
    assert found == []
    assert len(warnings) == 3
    assert any("missing.html" in w and "doesn't exist" in w for w in warnings)
    assert any("outside the project" in w for w in warnings)
    assert any("variable name" in w for w in warnings)


def test_syntax_errors_are_skipped(tmp_path):
    found, warnings = find_referenced_templates(str(tmp_path), ["{% if %}"])
    assert found == [] and warnings == []


def test_stage_copies_included_templates(tmp_path):
    project = make_project(tmp_path / 'project')
    build_dir = tmp_path / 'build'

    app_data_dir, _, warnings = stage_project(str(project), str(build_dir), sys.executable)

    app_data = build_dir / 'app_data'
    assert app_data_dir == str(app_data)
    assert warnings == []
    for name in ('_list.html', '_item.html', '_nav.html'):
        assert (app_data / 'partials' / name).is_file()
    assert not (app_data / 'partials' / '_unused.html').exists()
