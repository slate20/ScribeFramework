"""
Steps shared by the `scribe schema` commands and the IDE's Schema panel.

Each caller supplies a `connect(name, block)` function so failures are
reported its own way (a one-line CLI error, or a JSON error in the IDE).
"""

import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from scribe.database.base import DatabaseAdapter
from scribe.migrations import MigrationTarget, get_pending_migrations, next_migration_filename, run_migrations
from scribe.schema.diff import SchemaDiff, diff_schema
from scribe.schema.dsl import SchemaDefinition
from scribe.schema.generate import GeneratedMigration, RawChange, generate_migration, raw_sql_changes
from scribe.schema.introspect import LiveTable, read_live_schema_counted
from scribe.schema.loader import load_schema

Connect = Callable[[str, dict], DatabaseAdapter]


def implicit_migrations_refusal(target: Optional[MigrationTarget]) -> Optional[str]:
    """Why Scribe won't create migration files for a connection, or None if it may."""
    if target is None or not target.needs_explicit_migrations:
        return None
    # Only 'default' has migrations on without the key, and then the folder is always migrations/
    return (f"'{target.name}' ({target.dialect}) doesn't set \"migrations\" in scribe.json, so Scribe won't "
            f"create migrations for it. If Scribe should manage its schema, add \"migrations\": \"migrations\" "
            f"to its block (or \"migrations\": false if the schema is managed elsewhere).")


def _migrations_disabled(name: str) -> str:
    folder = 'migrations' if name == 'default' else f'migrations/{name}'
    return (f"Migrations are not enabled for '{name}'. To enable them, add\n"
            f"  \"migrations\": \"{folder}\"\nto its block in scribe.json.")


def generate_refusal(target: Optional[MigrationTarget], name: str) -> Optional[str]:
    """Why `scribe schema generate` won't write a migration for a connection, or None if it may."""
    if target is None:
        return _migrations_disabled(name)
    return implicit_migrations_refusal(target)


def apply_refusal(target: Optional[MigrationTarget], name: str) -> Optional[str]:
    """Why `scribe schema apply` won't run on a connection, or None if it may."""
    refusal = generate_refusal(target, name)
    if refusal:
        return refusal
    if not target.auto_migrate:
        return (f"'{name}' has auto_migrate off, so its migrations are applied deliberately. "
                f"Use 'scribe schema generate', review the file, then 'scribe db migrate'.")
    if target.auto_migrate_implicit and target.dialect != 'sqlite':
        return (f"'{name}' ({target.dialect}) has no explicit \"auto_migrate\" setting. "
                f"Set \"auto_migrate\": true in its scribe.json block to allow 'scribe schema apply' on it.")
    return None


def migration_slug(name: Optional[str], tables: List[str]) -> str:
    """File name part for a generated migration: the given name, or derived from the tables it touches."""
    if name:
        slug = name
    elif tables:
        slug = 'schema_' + '_'.join(t.rpartition('.')[2] for t in tables[:3])
        if len(tables) > 3:
            slug += '_etc'
    else:
        slug = 'schema_raw_sql'
    return re.sub(r'[^A-Za-z0-9_]+', '_', slug).strip('_').lower() or 'schema'


@dataclass
class SchemaCheck:
    """A connection's schema file compared with its database."""
    name: str
    block: dict
    file: str
    definition: Optional[SchemaDefinition] = None   # None when the connection has no schema file
    live: Optional[Dict[str, LiveTable]] = None
    diff: Optional[SchemaDiff] = None
    target: Optional[MigrationTarget] = None        # None when migrations are disabled
    raw: List[RawChange] = field(default_factory=list)  # raw_sql blocks not yet in a generated migration
    total_tables: int = 0                           # tables in the database, in scope or not

    @property
    def dialect(self) -> str:
        return self.block.get('type', 'sqlite').lower()

    @property
    def change_count(self) -> int:
        return len(self.diff.changes) + len(self.raw) if self.diff else 0


def read_live(connect: Connect, name: str, block: dict, table_filter=None):
    """
    Connect to a database and read its tables.

    Returns:
        (live tables accepted by table_filter, total number of tables in the database)
    """
    db = connect(name, block)
    try:
        return read_live_schema_counted(db, table_filter)
    finally:
        db.close()


def check_connection(connect: Connect, name: str, block: dict, file: str,
                     target: Optional[MigrationTarget], untracked: bool = False) -> SchemaCheck:
    """
    Load a connection's schema file and diff it with the database.

    Args:
        untracked: Also read in-scope tables the file doesn't declare, so the diff
                   can list them as untracked. Otherwise only declared tables are
                   read, which is all diff/generate/apply compare.

    Raises:
        SchemaError: If the schema file doesn't load
    """
    if not os.path.exists(file):
        return SchemaCheck(name, block, file, target=target)

    definition = load_schema(file)
    live, total = read_live(connect, name, block, definition.in_scope if untracked else definition.declares)
    check = SchemaCheck(name, block, file, definition, live, target=target, total_tables=total)
    check.diff = diff_schema(definition, live, check.dialect)
    # raw_sql blocks are tracked through generated migrations, so only connections with migrations have them
    check.raw = raw_sql_changes(definition, target.path) if target else []
    return check


def render_migration(check: SchemaCheck, project_path: str, diff: Optional[SchemaDiff] = None,
                     raw: Optional[List[RawChange]] = None) -> GeneratedMigration:
    """The migration for a check's whole diff, or for the given part of it."""
    return generate_migration(
        check.definition, check.diff if diff is None else diff, check.live, check.dialect, check.name,
        os.path.relpath(check.file, project_path), check.raw if raw is None else raw,
    )


def additive_part(check: SchemaCheck):
    """
    The changes `apply` may run: additive ones and new raw_sql blocks.

    Returns:
        (SchemaDiff of additive changes, new raw_sql changes, number of changes left out)
    """
    additive = SchemaDiff(changes=[c for c in check.diff.changes if c.additive])
    raw = [r for r in check.raw if r.status == 'new']
    left_out = len(check.diff.changes) - len(additive.changes) + len(check.raw) - len(raw)
    return additive, raw, left_out


def pending_migrations(connect: Connect, name: str, block: dict, target: MigrationTarget) -> List[str]:
    db = connect(name, block)
    try:
        return get_pending_migrations(db, target.path)
    finally:
        db.close()


def write_migration(target: MigrationTarget, migration: GeneratedMigration, name: Optional[str] = None) -> str:
    """Write a generated migration as the next file in the connection's folder. Returns its path."""
    os.makedirs(target.path, exist_ok=True)
    filename = next_migration_filename(target.path, migration_slug(name, migration.tables))
    file = os.path.join(target.path, filename)
    with open(file, 'w', encoding='utf-8') as f:
        f.write(migration.sql)
    return file


def run_pending(connect: Connect, name: str, block: dict, project_path: str, target: MigrationTarget):
    db = connect(name, block)
    try:
        run_migrations(db, project_path, target.path)
    finally:
        db.close()


def run_written_migration(connect: Connect, name: str, block: dict, project_path: str,
                          target: MigrationTarget, file: str) -> Optional[Exception]:
    """
    Run a migration file `apply` just wrote.

    Returns:
        None on success. On failure the migration was rolled back (each file runs
        in one transaction), so the file is removed rather than left pending, and
        the error is returned.
    """
    try:
        run_pending(connect, name, block, project_path, target)
    except Exception as e:
        os.remove(file)
        return e
    return None
