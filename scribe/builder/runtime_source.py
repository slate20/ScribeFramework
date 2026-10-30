"""
Locates and copies the `scribe` runtime package into a build's staging
directory.
"""

import os
import shutil
import sys

# Subpackages/files not needed by a compiled app at runtime: the dev IDE,
# the dev/serve CLI, and this build tool itself.
RUNTIME_EXCLUDE_DIRS = {'gui', 'builder', '__pycache__'}
RUNTIME_EXCLUDE_FILES = {'cli.py'}


def get_runtime_source_dir() -> str:
    """
    Locate the source directory of the `scribe` package to stage into a
    build's `_scribe_build/scribe/` runtime bundle.

    When running as a frozen scribe-build executable, this is a plain copy
    of the `scribe` package bundled as PyInstaller `datas` under
    `scribe_runtime_src/` (see scribe_build_tool.spec / build.py) — a
    frozen binary's own bundled modules live inside a PYZ archive, not as
    ordinary files, so the source has to be shipped separately as a data
    directory to be copied from.

    When running unfrozen (from a source checkout or a pip install), it's
    simply the installed `scribe` package's own directory.
    """
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        bundled = os.path.join(meipass, 'scribe_runtime_src')
        if os.path.isdir(bundled):
            return bundled
        raise RuntimeError(
            "scribe-build is running frozen but scribe_runtime_src/ was not "
            "bundled with it — rebuild scribe-build with scribe_build_tool.spec"
        )

    import scribe
    return os.path.dirname(os.path.abspath(scribe.__file__))


def get_compile_routes_script_path() -> str:
    """
    Locate compile_routes.py, the script staging copies alongside a
    project's _scribe_build/ to run via the target venv's Python.

    When scribe-build runs frozen, this module's own __file__ points at a
    synthetic in-archive path — compile_routes.py doesn't exist there as a
    real file on disk (it's bundled inside the PYZ), so it's shipped as an
    explicit `datas` entry instead (see scribe_build_tool.spec) and located
    under sys._MEIPASS.
    """
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        bundled = os.path.join(meipass, 'scribe_build_data', 'compile_routes.py')
        if os.path.isfile(bundled):
            return bundled
        raise RuntimeError(
            "scribe-build is running frozen but compile_routes.py was not "
            "bundled with it — rebuild scribe-build with scribe_build_tool.spec"
        )

    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'compile_routes.py')


def copy_runtime_package(dest_dir: str):
    """Copy the scribe runtime package (minus gui/cli/builder) into dest_dir."""
    src = get_runtime_source_dir()

    def ignore(_dir_path, names):
        ignored = set()
        for name in names:
            if name in RUNTIME_EXCLUDE_DIRS or name in RUNTIME_EXCLUDE_FILES:
                ignored.add(name)
            elif name.endswith(('.pyc', '.pyo')) or name == '__pycache__':
                ignored.add(name)
        return ignored

    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    shutil.copytree(src, dest_dir, ignore=ignore)
