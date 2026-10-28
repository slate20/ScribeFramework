"""
Migration runner for applying database schema changes.

Migrations are SQL files in the migrations/ directory, executed in order.
"""

import os
import glob
import re
from typing import List, Optional, Union
from scribe.database.base import DatabaseAdapter


# Tracking table DDL per dialect. Existence is checked with has_table() first,
# since MSSQL has no CREATE TABLE IF NOT EXISTS.
_MIGRATIONS_TABLE_DDL = {
    'sqlite': """
        CREATE TABLE _migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    'postgresql': """
        CREATE TABLE _migrations (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    'mssql': """
        CREATE TABLE _migrations (
            id INT IDENTITY(1,1) PRIMARY KEY,
            filename NVARCHAR(255) UNIQUE NOT NULL,
            applied_at DATETIME2 DEFAULT CURRENT_TIMESTAMP
        )
    """,
}


def run_migrations(db: Union[DatabaseAdapter, 'DatabaseManager'], project_path: str,
                   migrations_path: Optional[str] = None) -> int:
    """
    Run all pending database migrations.

    Args:
        db: DatabaseAdapter or DatabaseManager instance
        project_path: Path to the project directory
        migrations_path: Folder holding the .sql files (default: <project_path>/migrations)

    Returns:
        Number of migrations applied

    Note:
        If a DatabaseManager is passed, migrations run on the 'default' connection.

    Migration files:
        migrations/
        ├── 001_create_users.sql
        ├── 002_create_posts.sql
        └── 003_add_user_roles.sql

    Files are executed in alphabetical order. Already-applied migrations
    are tracked in the _migrations table.

    Example migration file (001_create_users.sql):
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """
    # If DatabaseManager is passed, use the 'default' connection
    from scribe.database.manager import DatabaseManager
    if isinstance(db, DatabaseManager):
        if 'default' not in db:
            print("Warning: No 'default' database connection found. Skipping migrations.")
            return 0
        db = db['default']

    if migrations_path is None:
        migrations_path = os.path.join(project_path, 'migrations')

    # If the migrations folder doesn't exist, nothing to do
    if not os.path.isdir(migrations_path):
        print(f"No migrations folder found at {os.path.relpath(migrations_path, project_path)}/")
        return 0

    migration_files = _list_migration_files(migrations_path)
    if not migration_files:
        print("No migration files found")
        return 0

    # Create migrations tracking table if it doesn't exist
    _create_migrations_table(db)

    # Get list of already-applied migrations
    applied_migrations = set(get_applied_migrations(db))

    # Run each migration
    applied_count = 0
    for filepath in migration_files:
        filename = os.path.basename(filepath)

        # Skip if already applied
        if filename in applied_migrations:
            continue

        print(f"  Running migration: {filename}")

        try:
            # Read migration SQL
            with open(filepath, 'r', encoding='utf-8') as f:
                sql = f.read()

            # Split into individual statements (separated by semicolons)
            statements = _split_sql_statements(sql)

            # Execute each statement
            for statement in statements:
                statement = statement.strip()
                if statement:
                    db.execute(statement)

            # Record that this migration was applied
            _record_migration(db, filename)

            db.commit()
            applied_count += 1

            print(f"    ✓ Applied {filename}")

        except Exception as e:
            db.rollback()
            print(f"    ✗ Error applying {filename}: {e}")
            raise

    if applied_count > 0:
        print(f"\n✓ Applied {applied_count} migration(s)")
    else:
        print("\n✓ All migrations up to date")

    return applied_count


def get_pending_migrations(db: DatabaseAdapter, migrations_path: str) -> List[str]:
    """
    List migration filenames that have not been applied yet.

    Read-only: if the _migrations table doesn't exist, every file is pending
    and the table is not created.

    Args:
        db: DatabaseAdapter for the connection
        migrations_path: Folder holding the .sql files

    Returns:
        Pending filenames in the order they would run
    """
    if not os.path.isdir(migrations_path):
        return []

    applied = set(get_applied_migrations(db))
    return [
        os.path.basename(filepath)
        for filepath in _list_migration_files(migrations_path)
        if os.path.basename(filepath) not in applied
    ]


def get_applied_migrations(db: DatabaseAdapter) -> List[str]:
    """
    Get applied migration filenames, oldest first.

    Returns an empty list if the _migrations table doesn't exist yet.
    """
    if not db.has_table('_migrations'):
        return []
    results = db.query("SELECT filename FROM _migrations ORDER BY applied_at, id")
    return [row['filename'] for row in results]


def _list_migration_files(migrations_path: str) -> List[str]:
    """Get .sql files directly inside the folder, in execution (alphabetical) order."""
    return sorted(glob.glob(os.path.join(migrations_path, '*.sql')))


def _create_migrations_table(db: DatabaseAdapter):
    """Create the _migrations table to track applied migrations."""
    if db.has_table('_migrations'):
        return

    ddl = _MIGRATIONS_TABLE_DDL.get(db.dialect)
    if ddl is None:
        raise ValueError(f"Migrations are not supported for '{db.dialect}' databases")

    db.execute(ddl)
    db.commit()


def _record_migration(db: DatabaseAdapter, filename: str):
    """Record that a migration has been applied."""
    db.execute("INSERT INTO _migrations (filename) VALUES (?)", (filename,))


def _split_sql_statements(sql: str) -> List[str]:
    """
    Split SQL file into individual statements.

    Handles:
        - Semicolon-separated statements
        - Comments (-- and /* */)
        - Multi-line statements

    Args:
        sql: SQL file content

    Returns:
        List of SQL statements
    """
    # Remove single-line comments
    lines = []
    for line in sql.split('\n'):
        # Remove -- comments
        if '--' in line:
            line = line[:line.index('--')]
        lines.append(line)

    sql = '\n'.join(lines)

    # Remove multi-line comments /* ... */
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)

    # Split by semicolons
    statements = sql.split(';')

    # Filter out empty statements
    statements = [s.strip() for s in statements if s.strip()]

    return statements


def next_migration_filename(migrations_path: str, name: str) -> str:
    """
    Filename for the next migration in a folder, numbered after the existing files.

    Example:
        next_migration_filename('migrations', 'add_posts')  # '003_add_posts.sql'
    """
    numbers = []
    for filepath in glob.glob(os.path.join(migrations_path, '*.sql')):
        match = re.match(r'^(\d+)', os.path.basename(filepath))
        if match:
            numbers.append(int(match.group(1)))

    next_num = max(numbers) + 1 if numbers else 1
    return f"{next_num:03d}_{name}.sql"


def create_migration(project_path: str, name: str, migrations_path: Optional[str] = None) -> str:
    """
    Create a new migration file.

    Args:
        project_path: Project directory path
        name: Migration name (e.g., "create_users")
        migrations_path: Folder to create it in (default: <project_path>/migrations)

    Returns:
        Path to the created migration file

    Example:
        create_migration('/path/to/project', 'create_users')
        # Creates: migrations/001_create_users.sql
    """
    import datetime

    if migrations_path is None:
        migrations_path = os.path.join(project_path, 'migrations')

    # Create the migrations folder if it doesn't exist
    os.makedirs(migrations_path, exist_ok=True)

    filepath = os.path.join(migrations_path, next_migration_filename(migrations_path, name))

    # Create file with template
    template = f"""-- Migration: {name}
-- Created: {datetime.datetime.now().isoformat()}

-- Add your SQL statements here

"""

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(template)

    print(f"Created migration: {os.path.basename(filepath)}")
    return filepath
