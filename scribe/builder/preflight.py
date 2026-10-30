"""
Preflight checks for the target project venv.

scribe-build freezes a real Flask app by running PyInstaller through the
project's own venv Python. That means the venv needs to have the framework's
own runtime dependencies installed (Flask, Jinja2, Werkzeug, Flask-WTF,
Waitress, and any configured database driver) — not just the project's own
extra libraries.

This is a different, larger requirement than what a project venv needs for
`scribe dev`/`scribe serve`: those run inside the already-frozen `scribe`
binary, which has Flask etc. bundled internally, so inject_project_venv()
only ever needed the project's *own* dependencies on the venv's sys.path.
PyInstaller has no equivalent shortcut — whatever ends up in the output
binary has to be importable in the venv PyInstaller runs from.

PyInstaller itself won't fail loudly if a hidden import is missing from the
venv: it prints a warning and still produces an executable, which then
crashes with ModuleNotFoundError the moment someone runs it. Checking here
lets scribe-build install what's missing before any time is spent staging
or freezing — the same way it already auto-installs PyInstaller itself (see
scribe.builder.pyinstaller_invoke.ensure_pyinstaller).
"""

import json
import subprocess

from scribe.builder.db_config import DB_DRIVER_MODULES, configured_db_types

REQUIRED_RUNTIME_MODULES = {
    'flask': 'Flask>=3.0.0,<4.0.0',
    'jinja2': 'Jinja2>=3.1.0,<4.0.0',
    'werkzeug': 'Werkzeug>=3.0.0,<4.0.0',
    'flask_wtf': 'Flask-WTF>=1.2.0,<2.0.0',
    'wtforms': 'WTForms',
    'waitress': 'waitress>=3.0.0',
}

_CHECK_SCRIPT = """\
import importlib.util, json, sys
names = json.loads(sys.argv[1])
missing = []
for n in names:
    try:
        found = importlib.util.find_spec(n) is not None
    except Exception:
        found = False
    if not found:
        missing.append(n)
print(json.dumps(missing))
"""


def find_missing_modules(venv_python: str, names) -> list:
    """
    Return the subset of `names` that are not importable in venv_python.

    Returns an empty list if everything is importable, or if the check
    itself couldn't be run (in which case the failure will surface later,
    from PyInstaller or the frozen binary, instead).
    """
    names = list(names)
    if not names:
        return []

    try:
        result = subprocess.run(
            [venv_python, '-c', _CHECK_SCRIPT, json.dumps(names)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout.strip())
    except Exception:
        return []


def missing_runtime_dependencies(venv_python: str, app_config: dict):
    """
    Return a list of pip package specifiers that are importable by
    `scribe dev`/`scribe serve` (because they're bundled in the scribe
    binary) but missing from venv_python, and therefore missing from
    whatever scribe-build would freeze into the output executable.

    Returns an empty list if everything required is present, or if the
    check itself couldn't be run (in which case the failure will surface
    later, from PyInstaller or the frozen binary, instead).
    """
    modules_to_check = dict(REQUIRED_RUNTIME_MODULES)

    for db_type in configured_db_types(app_config):
        if db_type in DB_DRIVER_MODULES:
            mod, pip_spec = DB_DRIVER_MODULES[db_type]
            modules_to_check[mod] = pip_spec

    missing_modules = find_missing_modules(venv_python, modules_to_check.keys())
    return [modules_to_check[m] for m in missing_modules]


def install_runtime_dependencies(venv_python: str, specs) -> bool:
    """
    pip install the given package specifiers into venv_python.

    Returns True if pip reported success. Doesn't guarantee every package is
    now importable (a package can install but still fail to import, e.g. a
    missing native library) — callers should re-check with
    missing_runtime_dependencies() rather than trust this return value alone.
    """
    result = subprocess.run(
        [venv_python, '-m', 'pip', 'install'] + list(specs),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if result.stdout.strip():
            print(result.stdout)
        if result.stderr.strip():
            print(result.stderr)
    return result.returncode == 0
