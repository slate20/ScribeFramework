"""
Scans route and lib/ Python source for import statements.

Route Python blocks and lib/ helpers are shipped as precompiled bytecode
(app_data/code/*.mar, app_data/lib/*.pyc) rather than as source PyInstaller
can analyze — see scribe.builder.stage. That means PyInstaller's own static
import scanner never sees whatever a route or lib file imports, and quietly
fails to bundle it: not a build error, just a "Hidden import not found"
warning and a binary that crashes with ModuleNotFoundError the first time
that code path runs.

Scanning the source ourselves at staging time and feeding the results into
the generated spec's hiddenimports (see spec_template.py) closes that gap
for the common case: real import statements at any nesting level. It can't
see imports performed dynamically (importlib.import_module with a computed
name, __import__, etc.) — neither would PyInstaller's own static analysis.
"""

import ast


def scan_imports(source: str) -> set:
    """
    Return the set of module names imported by `source`, as full dotted
    paths (e.g. 'email.mime.text', not just 'email').

    A submodule needs its own hiddenimport entry — PyInstaller doesn't
    bundle a package's submodules just because the top-level package name
    is listed, since stdlib packages like `email` don't import their own
    submodules (email.mime.text, etc.) in __init__.py. Listing the full
    path someone actually imports (`from email.mime.text import MIMEText`
    -> 'email.mime.text') is what makes PyInstaller pull it in; the parent
    packages along the way get bundled automatically as a side effect of
    resolving that path.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # node.level > 0 is a relative import (from . import x) — not
            # meaningful outside a real package, nothing to bundle for it.
            if node.module and node.level == 0:
                modules.add(node.module)

    return modules
