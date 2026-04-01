# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for building standalone ScribeEngine executable.

Usage:
    pyinstaller scribe.spec

This creates a standalone executable that includes:
- Python runtime
- All ScribeEngine dependencies
- CLI interface
"""

block_cipher = None

a = Analysis(
    ['scribe/cli.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include project template files
        ('scribe/templates', 'scribe/templates'),
        # Include GUI IDE templates and static files
        ('scribe/gui/templates', 'scribe/gui/templates'),
        ('scribe/gui/static', 'scribe/gui/static'),
    ],
    hiddenimports=[
        'scribe.app',
        'scribe.parser',
        'scribe.database',
        'scribe.database.sqlite',
        'scribe.database.postgresql',
        'scribe.database.mssql',
        'scribe.database.manager',
        'scribe.database.query_builder',
        'scribe.execution',
        'scribe.helpers',
        'scribe.loader',
        'scribe.migrations',
        'scribe.gui',
        'scribe.gui.routes',
        'flask',
        'jinja2',
        'werkzeug',
        'click',
        'flask_wtf',
        'wtforms',
        'waitress',
        'psycopg2',
        'pymssql',
        'ldap3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
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
    name='scribe',
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
