"""
Declarative schema files for ScribeEngine.

schemas/schema_{name}.py describes the tables a connection cares about.
`scribe schema diff` compares managed tables with the live database;
.sql migrations remain the only way the database changes.

See schema_system_proposal.md for the full design.
"""

from scribe.schema.dsl import (
    Table,
    Column,
    Index,
    ForeignKey,
    raw_sql,
    unmanaged,
    scope,
    sql,
    SchemaError,
    SchemaDefinition,
)

__all__ = [
    "Table",
    "Column",
    "Index",
    "ForeignKey",
    "raw_sql",
    "unmanaged",
    "scope",
    "sql",
    "SchemaError",
    "SchemaDefinition",
]
