"""
Shared database-config helpers for scribe-build.

Both the preflight dependency check and the generated PyInstaller spec need
to know which database driver(s) a project actually uses, so they stay in
sync: scribe-build should only require (and only freeze into the output
binary) the drivers a project's scribe.json actually configures, not every
driver scribe supports.
"""

DB_DRIVER_MODULES = {
    'postgresql': ('psycopg2', 'psycopg2-binary>=2.9.0'),
    'mssql': ('pymssql', 'pymssql>=2.2.0'),
    'mysql': ('pymysql', 'pymysql>=1.1.0'),
}


def configured_db_types(app_config: dict) -> set:
    """Return the set of database 'type' values configured in scribe.json."""
    databases = app_config.get('databases') or {}
    if not databases and isinstance(app_config.get('database'), dict):
        databases = {'default': app_config['database']}

    types = set()
    for conn in databases.values():
        if isinstance(conn, dict):
            types.add(conn.get('type', 'sqlite').lower())
    return types
