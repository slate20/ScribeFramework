#!/usr/bin/env python3
"""
Build script for creating standalone ScribeEngine executables.

This script uses PyInstaller to create platform-specific binaries.
"""

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path


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


def prepare_runtime_bundle():
    """
    Copy the scribe runtime package (minus gui/cli.py/builder) into
    scribe_runtime_src/ at the repo root, so scribe_build_tool.spec can
    bundle it as plain data. scribe-build (frozen) copies this into a
    project's _scribe_build/ during staging — it can't introspect its own
    frozen modules for that, since they live inside a PYZ archive rather
    than as files on disk.
    """
    from scribe.builder.runtime_source import copy_runtime_package

    print("\nPreparing scribe_runtime_src/ ...")
    copy_runtime_package('scribe_runtime_src')


def _build_one(spec_file, exe_base_name, platform_name):
    """Run PyInstaller for one spec file and copy the result into release/."""
    print(f"\nRunning PyInstaller ({spec_file})...")
    result = subprocess.run(
        ['pyinstaller', spec_file, '--clean'],
        check=True
    )

    if result.returncode != 0:
        print(f"ERROR: Build failed for {spec_file}")
        sys.exit(1)

    exe_name = f'{exe_base_name}.exe' if platform_name == 'windows' else exe_base_name
    exe_path = Path('dist') / exe_name
    if not exe_path.exists():
        print(f"ERROR: Executable not found at {exe_path}")
        sys.exit(1)

    release_dir = Path('release')
    release_dir.mkdir(exist_ok=True)

    release_name = f'{exe_base_name}-{platform_name}'
    if platform_name == 'windows':
        release_name += '.exe'

    release_path = release_dir / release_name
    shutil.copy2(exe_path, release_path)

    size_mb = os.path.getsize(release_path) / (1024 * 1024)
    print(f"  {release_path} ({size_mb:.1f} MB)")
    return release_path


def build_executable():
    """Build the standalone scribe and scribe-build executables using PyInstaller."""
    print("=" * 60)
    print("Building ScribeEngine Standalone Executables")
    print("=" * 60)

    # Check if PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("ERROR: PyInstaller not installed")
        print("Install it with: pip install pyinstaller")
        sys.exit(1)

    # Clean old builds
    clean_build_dirs()
    if os.path.exists('scribe_runtime_src'):
        shutil.rmtree('scribe_runtime_src')

    prepare_runtime_bundle()

    platform_name = get_platform_name()
    results = [
        _build_one('scribe.spec', 'scribe', platform_name),
        _build_one('scribe_build_tool.spec', 'scribe-build', platform_name),
    ]

    print("\n" + "=" * 60)
    print("✓ Build Successful!")
    print("=" * 60)
    print(f"Platform: {platform_name}")
    for path in results:
        print(f"Executable: {path}")
    print("\nTest with:")
    print(f"  {results[0]} --version")
    print(f"  {results[1]} build --path <project>")
    print("=" * 60)


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

    args = parser.parse_args()

    if args.clean_only:
        clean_build_dirs()
        print("✓ Cleaned build directories")
    else:
        build_executable()

        if args.test:
            test_executable()
