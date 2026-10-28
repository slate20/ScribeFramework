#!/usr/bin/env python3
"""
Build script for creating standalone ScribeEngine executables.

This script uses PyInstaller to create platform-specific binaries. The
binary bundles the Python that runs this script, so build releases with a
standalone Python 3.14:

    uv venv --python 3.14 --managed-python buildvenv
    uv pip install --python buildvenv/bin/python -r requirements.txt
    buildvenv/bin/python build.py --test

A distribution's system Python (e.g. Ubuntu's /usr/bin/python3) is compiled
against that distribution's glibc, which the binary then requires, so it
would not run on older Linux systems. The build checks for this.
"""

import os
import re
import sys
import shutil
import platform
import subprocess
from pathlib import Path

# Releases bundle this Python. Project virtualenvs must use the same minor
# version for compiled packages to load (see inject_project_venv in scribe/app.py).
RELEASE_PYTHON = (3, 14)

# Newest glibc the Linux binary may require (2.28: Debian 10, RHEL 8, Ubuntu 20.04).
MAX_GLIBC = (2, 28)


def get_platform_name():
    """Get a normalized platform name."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == 'darwin':
        return 'macos'
    elif system == 'windows':
        return 'windows'
    else:
        return 'linux'


def clean_build_dirs():
    """Remove old build artifacts."""
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"Cleaning {dir_name}/")
            shutil.rmtree(dir_name)


def build_executable():
    """Build the standalone executable using PyInstaller."""
    print("=" * 60)
    print("Building ScribeEngine Standalone Executable")
    print("=" * 60)

    if sys.version_info[:2] != RELEASE_PYTHON:
        want = '.'.join(map(str, RELEASE_PYTHON))
        print(f"ERROR: Releases bundle Python {want}, but this is Python {platform.python_version()}")
        print(f"Build with a standalone Python {want}; see the instructions at the top of build.py")
        sys.exit(1)

    # Check if PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("ERROR: PyInstaller not installed")
        print("Install it with: pip install pyinstaller")
        sys.exit(1)

    # Clean old builds
    clean_build_dirs()

    # Run PyInstaller with this Python, so the binary bundles the Python checked above
    print(f"\nRunning PyInstaller (Python {platform.python_version()}, {sys.executable})...")
    result = subprocess.run(
        [sys.executable, '-m', 'PyInstaller', 'scribe.spec', '--clean'],
        check=True
    )

    if result.returncode != 0:
        print("ERROR: Build failed")
        sys.exit(1)

    # Get platform info
    platform_name = get_platform_name()
    exe_name = 'scribe.exe' if platform_name == 'windows' else 'scribe'

    # Check if build succeeded
    exe_path = Path('dist') / exe_name
    if not exe_path.exists():
        print(f"ERROR: Executable not found at {exe_path}")
        sys.exit(1)

    # Create release directory
    release_dir = Path('release')
    release_dir.mkdir(exist_ok=True)

    # Copy executable to release with platform name
    release_name = f'scribe-{platform_name}'
    if platform_name == 'windows':
        release_name += '.exe'

    release_path = release_dir / release_name
    shutil.copy2(exe_path, release_path)

    # Get file size
    size_mb = os.path.getsize(release_path) / (1024 * 1024)

    glibc = None
    if platform_name == 'linux':
        glibc, library = required_glibc(release_path)

    print("\n" + "=" * 60)
    print("✓ Build Successful!")
    print("=" * 60)
    print(f"Platform: {platform_name}")
    print(f"Python: {platform.python_version()}")
    print(f"Executable: {release_path}")
    print(f"Size: {size_mb:.1f} MB")
    if glibc:
        print(f"Requires glibc: {glibc[0]}.{glibc[1]} or newer")
    print("\nTest it with:")
    print(f"  {release_path} --version")
    print(f"  {release_path} --help")
    print("=" * 60)


def required_glibc(executable):
    """
    The newest glibc version any library bundled in the executable needs.

    Returns:
        ((major, minor), library name), or (None, None) if nothing references glibc
    """
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    newest, library = None, None
    for name in archive.toc:
        if not re.search(r'\.so(\.|$)', name):
            continue
        versions = [tuple(map(int, v.decode().split('.')))
                    for v in re.findall(rb'GLIBC_(2\.\d+)', archive.extract(name) or b'')]
        if versions and (newest is None or max(versions) > newest):
            newest, library = max(versions), name
    return newest, library


def check_glibc(executable):
    """Fail the build if the binary needs a newer glibc than MAX_GLIBC."""
    glibc, library = required_glibc(executable)
    if glibc and glibc > MAX_GLIBC:
        print(f"\nERROR: The binary requires glibc {glibc[0]}.{glibc[1]} (because of {library}),")
        print(f"newer than the {MAX_GLIBC[0]}.{MAX_GLIBC[1]} releases support, so it won't run on older Linux systems.")
        print("This usually means it was built with a distribution's system Python.")
        print("Rebuild with a standalone Python; see the instructions at the top of build.py.")
        print("(Pass --skip-glibc-check for a local test build.)")
        os.remove(executable)
        print(f"Removed {executable} so it isn't released by mistake.")
        sys.exit(1)


def test_executable():
    """Test the built executable."""
    platform_name = get_platform_name()
    exe_name = f'scribe-{platform_name}'
    if platform_name == 'windows':
        exe_name += '.exe'

    exe_path = Path('release') / exe_name

    if not exe_path.exists():
        print(f"ERROR: Executable not found at {exe_path}")
        sys.exit(1)

    print("\nTesting executable...")
    result = subprocess.run([str(exe_path), '--version'], capture_output=True, text=True)
    print(result.stdout)

    result = subprocess.run([str(exe_path), '--help'], capture_output=True, text=True)
    print(result.stdout)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Build ScribeEngine executable')
    parser.add_argument('--test', action='store_true', help='Test the executable after building')
    parser.add_argument('--clean-only', action='store_true', help='Only clean build directories')
    parser.add_argument('--skip-glibc-check', action='store_true',
                        help="Don't fail when the Linux binary needs a newer glibc than releases support")

    args = parser.parse_args()

    if args.clean_only:
        clean_build_dirs()
        print("✓ Cleaned build directories")
    else:
        build_executable()

        if get_platform_name() == 'linux' and not args.skip_glibc_check:
            check_glibc(Path('release') / 'scribe-linux')

        if args.test:
            test_executable()
