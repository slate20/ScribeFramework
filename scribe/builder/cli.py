"""
Command-line interface for scribe-build.

Provides:
    scribe-build build   - Compile a Scribe project into a standalone executable
"""

import os
import shutil
import sys

import click

from scribe import __version__
from scribe.app import find_venv_python, load_config
from scribe.builder.stage import stage_project
from scribe.builder.spec_template import generate_spec, BASE_HIDDEN_IMPORTS
from scribe.builder.pyinstaller_invoke import run_pyinstaller
from scribe.builder.preflight import missing_runtime_dependencies, install_runtime_dependencies, find_missing_modules
from scribe.migrations.config import get_databases_config

ENV_EXAMPLE_TEMPLATE = """\
# Copy this file to .env in this same directory and fill in real values.
# Loaded automatically every time the compiled executable starts.
# Without a persisted SECRET_KEY, a new one is generated on every
# restart, which invalidates every existing login session.

# Generate one with:
#   python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=

# HOST=0.0.0.0
# PORT=8000
"""


def render_env_example(app_config) -> str:
    """Contents of the .env.example written next to a compiled executable,
    with a commented password line for each non-SQLite connection."""
    text = ENV_EXAMPLE_TEMPLATE
    password_lines = [
        f"# SCRIBE_DB_{name.upper()}_PASSWORD="
        for name, conn in get_databases_config(app_config).items()
        if isinstance(conn, dict) and str(conn.get('type', 'sqlite')).lower() != 'sqlite'
    ]
    if password_lines:
        text += "\n# Database passwords (stripped from the build):\n" + "\n".join(password_lines) + "\n"
    return text


def write_env_example(output_dir, app_config) -> bool:
    """Write <output_dir>/.env.example unless one already exists, so a file
    the user edited is never overwritten. Returns True if written."""
    path = os.path.join(output_dir, '.env.example')
    if os.path.exists(path):
        return False
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_env_example(app_config))
    return True


@click.group()
@click.version_option(version=__version__)
def cli():
    """
    scribe-build: compile a Scribe project into a standalone executable.

    This is a separate tool from `scribe` (the dev/serve/ide command). Its
    only job is turning a project directory of .stpl files into a single
    binary you can hand to someone without also shipping your source code,
    a Python install, or scribe itself.

    Run 'scribe-build build --help' for the build command's options,
    requirements, and examples.
    """
    pass


@cli.command()
@click.option('--path', default='.', help='Project directory containing scribe.json and your .stpl files. [default: .]')
@click.option('--name', default=None, help="Name of the output executable. [default: scribe.json build.name, or the project directory's name]")
@click.option('--output', default=None, help='Directory to write the executable to. [default: <project>/dist]')
@click.option('--venv', default=None, help='Path to the project venv to build with. [default: scribe.json "venv" key, $VIRTUAL_ENV, or ./.venv|venv|env under --path]')
@click.option('--keep-build', is_flag=True, help='Keep the _scribe_build/ staging directory after building, for inspecting routes.json/app_data or debugging a failed build.')
def build(path, name, output, venv, keep_build):
    """
    Compile the project at PATH into a standalone executable.

    \b
    What this does:
      1. Parses your .stpl routes and compiles each route's Python block
         and lib/ helpers to bytecode using your project's own venv Python
         (so the bytecode matches the interpreter that will run it).
      2. Copies static/, migrations/, base.stpl, any files your templates
         {% include %} or {% extends %}, and a sanitized scribe.json
         (secrets stripped — see "Runtime configuration" below) into a
         staging directory.
      3. Runs PyInstaller through that same venv Python to freeze everything
         into one binary. PyInstaller can't run from inside an already-frozen
         binary, which is why a real project venv is required.

    \b
    Requirements:
      Your project needs its own venv (.venv/venv/env, or point --venv at
      one). scribe-build freezes a real Flask app through that venv's own
      Python, so it needs Scribe's runtime dependencies importable there
      too (Flask, Jinja2, Werkzeug, Flask-WTF, waitress, and any database
      driver you use) — not just your app's own extra libraries. That's
      more than `scribe dev`/`scribe serve` need from a project venv, since
      those already have Flask etc. bundled inside the scribe binary.
      scribe-build checks for this automatically and installs whatever's
      missing into the venv before building (the same way it auto-installs
      PyInstaller itself), so in most cases you don't need to do anything
      beyond having a venv with your app's own dependencies:
        python -m venv .venv
        .venv/bin/pip install -r requirements.txt
      A native-library issue (e.g. a database driver needing system
      headers) can still make an automatic install fail — if that happens,
      scribe-build tells you exactly what's still missing to install by hand.

    \b
    Example:
        scribe-build build                          # Build ./ into ./dist/<dirname>
        scribe-build build --path myapp              # Build a specific project
        scribe-build build --name mytool             # Custom output binary name
        scribe-build build --output ~/builds         # Custom output directory
        scribe-build build --venv ../shared-venv      # Use a venv outside the project
        scribe-build build --keep-build              # Inspect _scribe_build/ after building

    \b
    Runtime configuration (set these when you run the built executable, not
    at build time — SECRET_KEY and database passwords are stripped from the
    binary and never embedded in it):
        HOST                          Bind address (default 0.0.0.0)
        PORT                          Bind port (default 8000)
        SECRET_KEY                    Flask session signing key
        SCRIBE_DB_<NAME>_PASSWORD     Password for the "<name>" entry in
                                      scribe.json's "databases" block, e.g.
                                      SCRIBE_DB_DEFAULT_PASSWORD

    \b
        SECRET_KEY=... PORT=8080 ./dist/myapp
    """
    project_path = os.path.abspath(path)

    if not os.path.isdir(project_path):
        click.echo(f"✗ Project directory not found: {project_path}")
        sys.exit(1)

    app_config = load_config(project_path)
    app_name = (
        name
        or app_config.get('build', {}).get('name')
        or os.path.basename(project_path.rstrip(os.sep))
        or 'app'
    )

    venv_python = find_venv_python(project_path, venv_hint=venv or app_config.get('venv'))
    if not venv_python:
        click.echo("✗ No project virtual environment found.")
        click.echo("  scribe-build runs PyInstaller through your project's own venv so the")
        click.echo("  compiled binary matches your project's Python version and installed")
        click.echo("  packages. Create one with:")
        click.echo("    python -m venv .venv")
        click.echo("    .venv/bin/pip install Flask Jinja2 Werkzeug Flask-WTF WTForms waitress pyinstaller")
        sys.exit(1)

    click.echo(f"Building '{app_name}'")
    click.echo(f"  Project: {project_path}")
    click.echo(f"  Venv:    {venv_python}")

    missing = missing_runtime_dependencies(venv_python, app_config)
    if missing:
        click.echo("\nThis venv is missing packages the compiled binary needs at runtime")
        click.echo("(scribe dev/serve don't need these in a project venv since the scribe")
        click.echo("binary has them bundled internally — scribe-build freezes a real Flask")
        click.echo("app through this venv's own Python, so they have to be installed here too):")
        click.echo(f"  {', '.join(missing)}")
        click.echo(f"Installing into {venv_python} ...")
        install_runtime_dependencies(venv_python, missing)

        still_missing = missing_runtime_dependencies(venv_python, app_config)
        if still_missing:
            click.echo("\n✗ Could not install all required runtime dependencies into this venv.")
            click.echo("  Still missing:")
            click.echo(f"    {', '.join(still_missing)}")
            click.echo("  This is usually a native-library issue (e.g. a database driver needing")
            click.echo("  system headers) rather than something scribe-build can fix automatically.")
            click.echo("  Try installing manually and rerunning:")
            click.echo(f"    {venv_python} -m pip install {' '.join(still_missing)}")
            sys.exit(1)

        click.echo("  ✓ Installed.")

    build_dir = os.path.join(project_path, '_scribe_build')
    output_dir = os.path.abspath(output) if output else os.path.join(project_path, 'dist')

    click.echo("\nStaging project (compiling routes and lib/ helpers)...")
    try:
        app_data_dir, detected_imports, template_warnings = stage_project(project_path, build_dir, venv_python)
    except Exception as e:
        click.echo(f"✗ Staging failed: {e}")
        sys.exit(1)

    if template_warnings:
        click.echo("\n⚠ Some files your templates include can't be bundled:")
        for warning in template_warnings:
            click.echo(f"    {warning}")
        click.echo("  Routes that render them will fail in the compiled binary — continuing the build.")

    # Route Python blocks and lib/*.py are shipped as precompiled bytecode,
    # invisible to PyInstaller's own static import analysis — anything they
    # import (stdlib or third-party) has to be declared explicitly or it
    # silently won't be bundled. detected_imports (from scanning that source
    # at staging time) covers that; this only checks whether those modules
    # are importable in the venv PyInstaller will run from, since a module
    # that isn't installed there can't be bundled regardless of being
    # declared.
    unresolvable = [
        name for name in find_missing_modules(venv_python, detected_imports)
        if name not in BASE_HIDDEN_IMPORTS
    ]
    if unresolvable:
        click.echo("\n⚠ Some modules imported by your routes or lib/ files aren't importable")
        click.echo("  in this venv, so they won't work in the compiled binary:")
        click.echo(f"    {', '.join(sorted(unresolvable))}")
        click.echo("  If these are your own dependencies, install them into the project venv:")
        click.echo(f"    {venv_python} -m pip install <package>")
        click.echo("  (This check is based on scanning import statements and can have false")
        click.echo("  positives for conditional/dynamic imports — continuing the build.)")

    click.echo("Generating PyInstaller spec...")
    spec_path = os.path.join(build_dir, 'project_build.spec')
    with open(spec_path, 'w', encoding='utf-8') as f:
        f.write(generate_spec(app_name, app_config, extra_hiddenimports=detected_imports))

    click.echo("Running PyInstaller (this can take a minute)...")
    try:
        run_pyinstaller(venv_python, spec_path, build_dir, output_dir)
    except Exception as e:
        click.echo(f"✗ PyInstaller build failed: {e}")
        sys.exit(1)

    if not keep_build:
        shutil.rmtree(build_dir, ignore_errors=True)

    exe_name = app_name + ('.exe' if os.name == 'nt' else '')
    exe_path = os.path.join(output_dir, exe_name)
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        click.echo(f"\n✓ Build successful: {exe_path} ({size_mb:.1f} MB)")
        click.echo(f"  Run it with: {exe_path}")
        if write_env_example(output_dir, app_config):
            click.echo(f"  Wrote {os.path.join(output_dir, '.env.example')}")
        click.echo("  Configure it with a .env file next to the executable (copy .env.example),")
        click.echo("  or with real environment variables, which take precedence:")
        click.echo("    HOST, PORT, SECRET_KEY, SCRIBE_DB_<NAME>_PASSWORD")
        click.echo("  Uploads (uploads/) and relative SQLite databases (e.g. app.db) are stored")
        click.echo(f"  next to the executable, in {output_dir}")
    else:
        click.echo(f"\n✗ Expected output not found at {exe_path}")
        sys.exit(1)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    cli()
