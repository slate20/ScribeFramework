"""
Invokes PyInstaller through the target project's venv Python.

PyInstaller cannot be run from within an already-frozen binary — the
frozen runtime is a stripped bootstrapped environment, not a callable
`python` interpreter. scribe-build sidesteps this by shelling out to the
project's own venv Python (a real interpreter) to do the actual freezing,
whether scribe-build itself is running frozen or from source.
"""

import os
import subprocess


def ensure_pyinstaller(venv_python: str):
    check = subprocess.run(
        [venv_python, '-c', 'import PyInstaller'],
        capture_output=True,
    )
    if check.returncode != 0:
        print("  PyInstaller not found in project venv, installing...")
        subprocess.run([venv_python, '-m', 'pip', 'install', 'pyinstaller'], check=True)


def run_pyinstaller(venv_python: str, spec_path: str, build_dir: str, dist_dir: str):
    ensure_pyinstaller(venv_python)
    os.makedirs(dist_dir, exist_ok=True)
    subprocess.run(
        [
            venv_python, '-m', 'PyInstaller', spec_path,
            '--clean', '--noconfirm',
            '--distpath', dist_dir,
            '--workpath', os.path.join(build_dir, 'pyi_build'),
        ],
        cwd=build_dir,
        check=True,
    )
