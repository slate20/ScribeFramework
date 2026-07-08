# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for building the standalone scribe-build tool.

Usage:
    pyinstaller scribe_build_tool.spec

scribe-build compiles a Scribe project directory into its own standalone,
distributable executable. It is a separate binary from `scribe` (the
dev/serve/ide tool): it doesn't run a Flask app itself, so it doesn't need
the GUI IDE's Monaco editor assets bundled, and can evolve independently of
the dev server.

It still imports scribe.app for find_venv_python()/load_config()/
parse_template_files(), so Flask/Jinja2/Werkzeug are still required at
import time even though scribe-build never serves a request itself.

It bundles a copy of the scribe runtime package as a plain data directory
(scribe_runtime_src/, prepared by build.py before this spec runs) rather
than relying on its own frozen imports for staging, because staging needs
to physically copy that source into a project's _scribe_build/ directory —
a frozen binary's own modules live inside a PYZ archive, not as ordinary
files on disk.
"""

block_cipher = None

a = Analysis(
    ['scribe/builder/cli.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('scribe_runtime_src', 'scribe_runtime_src'),
        ('scribe/builder/compile_routes.py', 'scribe_build_data'),
    ],
    hiddenimports=[
        'scribe.app',
        'scribe.parser',
        'scribe.parser.parser',
        'scribe.parser.lexer',
        'scribe.parser.ast_nodes',
        'scribe.execution',
        'scribe.execution.context',
        'scribe.execution.builtins',
        'scribe.database',
        'scribe.helpers',
        'scribe.helpers.auth',
        'scribe.loader',
        'scribe.migrations',
        'scribe.builder',
        'scribe.builder.stage',
        'scribe.builder.compile_routes',
        'scribe.builder.spec_template',
        'scribe.builder.pyinstaller_invoke',
        'scribe.builder.runtime_source',
        'scribe.builder.preflight',
        'scribe.builder.db_config',
        'scribe.builder.import_scan',
        'click',
        'flask',
        'flask_wtf',
        'jinja2',
        'werkzeug',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'scribe.gui',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'tkinter',
        'PyQt5',
        'PySide2',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='scribe-build',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
