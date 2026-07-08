"""
Stages a Scribe project into a self-contained `_scribe_build/` directory
ready for PyInstaller: precompiled route bytecode, precompiled lib/
helpers, verbatim static/migrations/base.stpl, a sanitized config, the
scribe runtime package, and a generated __main__.py entry point.
"""

import json
import os
import shutil
import subprocess

from scribe.app import parse_template_files, load_config
from scribe.builder.runtime_source import copy_runtime_package, get_compile_routes_script_path
from scribe.builder.import_scan import scan_imports

MAIN_PY_TEMPLATE = '''\
import os
import sys


def _base_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def main():
    from scribe.app import create_compiled_app
    from waitress import serve as waitress_serve

    app = create_compiled_app(_base_dir())
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving on http://{host}:{port}")
    waitress_serve(app, host=host, port=port)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
'''


def stage_project(project_path: str, build_dir: str, venv_python: str):
    """
    Build the `_scribe_build/` staging directory for `project_path`.

    Returns (app_data_dir, detected_imports) — detected_imports is the set
    of top-level module names imported anywhere in route Python blocks or
    lib/*.py, for the caller to feed into the generated spec's
    hiddenimports (see scan_imports()'s docstring for why this is needed).
    """
    project_path = os.path.abspath(project_path)

    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)

    app_data_dir = os.path.join(build_dir, 'app_data')
    code_dir = os.path.join(app_data_dir, 'code')
    lib_out_dir = os.path.join(app_data_dir, 'lib')
    os.makedirs(code_dir, exist_ok=True)

    # 1. Copy the scribe runtime package (execution/database/helpers/
    #    loader/migrations/app.py — everything create_compiled_app needs).
    copy_runtime_package(os.path.join(build_dir, 'scribe'))

    # 2. Parse .stpl routes with the builder's own parser. Parsing the
    #    .stpl markup format doesn't depend on the target Python version,
    #    so this runs directly in scribe-build's own interpreter.
    routes = parse_template_files(project_path)

    detected_imports = set()

    manifest_routes = []
    routes_json = []
    for i, route in enumerate(routes):
        code_file = None
        if route.python_code:
            code_file = f'route_{i}.mar'
            manifest_routes.append({'source': route.python_code, 'code_file': code_file})
            detected_imports |= scan_imports(route.python_code)
        routes_json.append({
            'path': route.path,
            'methods': route.methods,
            'decorators': route.decorators,
            'template': route.template,
            'no_layout': route.no_layout,
            'is_sse': route.is_sse,
            'csrf_exempt': route.csrf_exempt,
            'code_file': code_file,
        })

    with open(os.path.join(app_data_dir, 'routes.json'), 'w', encoding='utf-8') as f:
        json.dump(routes_json, f)

    # 3/4. Delegate bytecode compilation (routes + lib/) to the target
    #    venv's own Python — see compile_routes.py for why this can't run
    #    in scribe-build's own interpreter.
    lib_src_dir = os.path.join(project_path, 'lib')
    if os.path.isdir(lib_src_dir):
        for filename in os.listdir(lib_src_dir):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue
            with open(os.path.join(lib_src_dir, filename), 'r', encoding='utf-8') as f:
                detected_imports |= scan_imports(f.read())
    compile_script_dst = os.path.join(build_dir, '_compile_routes.py')
    shutil.copy2(get_compile_routes_script_path(), compile_script_dst)

    manifest = {
        'code_dir': code_dir,
        'routes': manifest_routes,
        'lib_src_dir': lib_src_dir if os.path.isdir(lib_src_dir) else None,
        'lib_out_dir': lib_out_dir,
    }
    manifest_path = os.path.join(build_dir, '_compile_manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f)

    subprocess.run(
        [venv_python, compile_script_dst, manifest_path],
        cwd=build_dir,
        check=True,
    )
    os.remove(compile_script_dst)
    os.remove(manifest_path)

    # 5. Static assets, migrations, and base.stpl copied verbatim.
    static_src = os.path.join(project_path, 'static')
    if os.path.isdir(static_src):
        shutil.copytree(static_src, os.path.join(app_data_dir, 'static'))

    migrations_src = os.path.join(project_path, 'migrations')
    if os.path.isdir(migrations_src):
        shutil.copytree(migrations_src, os.path.join(app_data_dir, 'migrations'))

    base_stpl_src = os.path.join(project_path, 'base.stpl')
    if os.path.isfile(base_stpl_src):
        shutil.copy2(base_stpl_src, os.path.join(app_data_dir, 'base.stpl'))

    # 6. Sanitize scribe.json: never embed a real secret key or database
    #    password in the shipped binary. create_compiled_app() reads these
    #    back from the environment (SECRET_KEY, SCRIBE_DB_<NAME>_PASSWORD).
    config = load_config(project_path)
    config.pop('SECRET_KEY', None)
    config.pop('secret_key', None)
    if 'databases' in config:
        # load_config() always fills in a 'database' (singular) default
        # containing an absolute path on the *build* machine, even when
        # unused — drop it so it isn't leaked into the shipped binary.
        config.pop('database', None)
        for conn in config['databases'].values():
            if isinstance(conn, dict):
                conn.pop('password', None)
    elif isinstance(config.get('database'), dict):
        config['database'].pop('password', None)

    with open(os.path.join(app_data_dir, 'scribe.json'), 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)

    # 7. Entry point.
    with open(os.path.join(build_dir, '__main__.py'), 'w', encoding='utf-8') as f:
        f.write(MAIN_PY_TEMPLATE)

    return app_data_dir, detected_imports
