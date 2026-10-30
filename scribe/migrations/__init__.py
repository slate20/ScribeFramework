"""
Database migration system for ScribeEngine.

Applies SQL migration files from each connection's migrations folder.
"""

from scribe.migrations.runner import (
    run_migrations,
    create_migration,
    next_migration_filename,
    get_pending_migrations,
    get_applied_migrations,
)
from scribe.migrations.config import (
    MigrationTarget,
    MigrationConfigError,
    get_databases_config,
    get_migration_targets,
)

__all__ = [
    "run_migrations",
    "create_migration",
    "next_migration_filename",
    "get_pending_migrations",
    "get_applied_migrations",
    "MigrationTarget",
    "MigrationConfigError",
    "get_databases_config",
    "get_migration_targets",
]
