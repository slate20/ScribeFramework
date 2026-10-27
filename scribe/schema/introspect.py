"""
Reading a live database's structure through the adapter introspection methods.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from scribe.database.base import ColumnInfo, DatabaseAdapter, ForeignKeyInfo, IndexInfo


@dataclass
class LiveTable:
    name: str
    columns: List[ColumnInfo] = field(default_factory=list)
    indexes: List[IndexInfo] = field(default_factory=list)
    foreign_keys: List[ForeignKeyInfo] = field(default_factory=list)


def is_internal_table(name: str) -> bool:
    """Tables Scribe or the database itself maintains, never part of a schema file."""
    bare = name.rpartition('.')[2].lower()
    return bare == '_migrations' or bare.startswith('sqlite_')


def list_live_tables(db: DatabaseAdapter) -> List[str]:
    """
    Table names as a schema file would write them.

    PostgreSQL tables in the current schema are unqualified ('users');
    tables in other schemas keep their prefix ('reporting.sales').
    """
    tables = db.get_tables()
    if db.dialect == 'postgresql':
        current = db.query("SELECT current_schema() AS schema")[0]['schema']
        prefix = f"{current}."
        tables = [t[len(prefix):] if t.startswith(prefix) else t for t in tables]
    return [t for t in tables if not is_internal_table(t)]


def read_live_table(db: DatabaseAdapter, name: str) -> LiveTable:
    return LiveTable(
        name=name,
        columns=db.get_columns(name),
        indexes=db.get_indexes(name),
        foreign_keys=db.get_foreign_keys(name),
    )


def read_live_schema(db: DatabaseAdapter) -> Dict[str, LiveTable]:
    """
    Read every user table in the database.

    Returns:
        Lowercased table name -> LiveTable, sorted by name
    """
    return {name.lower(): read_live_table(db, name) for name in sorted(list_live_tables(db))}
