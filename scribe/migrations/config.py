"""
Per-connection migration settings.

Each connection block in scribe.json may set:

    "migrations":   "path/to/folder" | true | false
    "auto_migrate": true | false

Defaults keep existing projects working unchanged:
    - 'default' uses the top-level migrations/ folder and auto-migrates on startup
    - every other connection has migrations disabled, and does not auto-migrate
      even once a path is set
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List

DEFAULT_CONNECTION = 'default'


class MigrationConfigError(ValueError):
    """Raised when migration settings in scribe.json are invalid."""


@dataclass
class MigrationTarget:
    """A connection that has migrations enabled."""
    name: str
    path: str                 # Absolute path to the migrations folder
    auto_migrate: bool        # Apply pending migrations on dev/ide/serve startup
    auto_migrate_implicit: bool  # auto_migrate came from the default, not scribe.json
    dialect: str
    migrations_implicit: bool = False  # 'migrations' came from the default (only possible on 'default')

    @property
    def needs_explicit_migrations(self) -> bool:
        """
        A non-SQLite connection whose migrations are on only by default.

        Usually an app pointed at a database whose schema is managed elsewhere,
        upgraded from before migrations were configurable. Scribe warns about it
        and won't create migration files for it until scribe.json says so.
        """
        return self.migrations_implicit and self.dialect != 'sqlite'


def get_databases_config(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Get the named connection blocks from a loaded scribe.json config.

    Handles the deprecated single 'database' key the same way DatabaseManager does.
    """
    if 'databases' in config:
        return config['databases']
    if 'database' in config:
        return {DEFAULT_CONNECTION: config['database']}
    return {DEFAULT_CONNECTION: {'type': 'sqlite', 'database': 'app.db'}}


def get_migration_targets(databases: Dict[str, Dict[str, Any]], project_path: str) -> List[MigrationTarget]:
    """
    Resolve which connections have migrations enabled, and where their files live.

    Args:
        databases: Connection name -> connection block (as in scribe.json 'databases')
        project_path: Project directory; relative migration paths resolve against it

    Returns:
        List of MigrationTarget, in scribe.json order

    Raises:
        MigrationConfigError: If a setting has the wrong type or two connections share a folder
    """
    targets = []
    seen_paths = {}

    for name, block in databases.items():
        is_default = name == DEFAULT_CONNECTION
        migrations_implicit = 'migrations' not in block
        migrations = block.get('migrations', 'migrations' if is_default else False)

        if migrations is False or migrations is None:
            continue
        if migrations is True:
            migrations = 'migrations' if is_default else os.path.join('migrations', name)
        if not isinstance(migrations, str) or not migrations.strip():
            raise MigrationConfigError(
                f"Database '{name}': 'migrations' must be a folder path, true, or false "
                f"(got {migrations!r})"
            )

        auto_migrate = block.get('auto_migrate')
        auto_migrate_implicit = auto_migrate is None
        if auto_migrate_implicit:
            auto_migrate = is_default
        elif not isinstance(auto_migrate, bool):
            raise MigrationConfigError(
                f"Database '{name}': 'auto_migrate' must be true or false (got {auto_migrate!r})"
            )

        path = os.path.normpath(os.path.join(os.path.abspath(project_path), migrations))
        if path in seen_paths:
            raise MigrationConfigError(
                f"Databases '{seen_paths[path]}' and '{name}' both use migrations folder "
                f"'{migrations}'. Each connection needs its own folder."
            )
        seen_paths[path] = name

        targets.append(MigrationTarget(
            name=name,
            path=path,
            auto_migrate=auto_migrate,
            auto_migrate_implicit=auto_migrate_implicit,
            dialect=block.get('type', 'sqlite').lower(),
            migrations_implicit=migrations_implicit,
        ))

    return targets
