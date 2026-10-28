"""
Reading a live database's structure through the adapter introspection methods.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

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


def default_schema(db: DatabaseAdapter) -> Optional[str]:
    """The schema unqualified names refer to (PostgreSQL only; None elsewhere)."""
    if db.dialect == 'postgresql':
        return db.query("SELECT current_schema() AS schema")[0]['schema']
    return None


def list_live_tables(db: DatabaseAdapter) -> List[str]:
    """
    Table names as a schema file would write them.

    PostgreSQL tables in the current schema are unqualified ('users');
    tables in other schemas keep their prefix ('reporting.sales').
    """
    tables = db.get_tables()
    current = default_schema(db)
    if current:
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


TableFilter = Callable[[str, Optional[str]], bool]


def read_live_schema(db: DatabaseAdapter, table_filter: Optional[TableFilter] = None) -> Dict[str, LiveTable]:
    """
    Read the user tables in the database.

    Args:
        table_filter: Called with (table name, default schema); only tables it
                      accepts are read. Filtering happens before columns and
                      indexes are read, which matters on large databases.

    Returns:
        Lowercased table name -> LiveTable, sorted by name
    """
    return read_live_schema_counted(db, table_filter)[0]


def read_live_schema_counted(db: DatabaseAdapter, table_filter: Optional[TableFilter] = None):
    """read_live_schema(), plus how many user tables the database has in total."""
    names = list_live_tables(db)
    schema = default_schema(db) if table_filter else None
    selected = [name for name in names if table_filter is None or table_filter(name, schema)]
    live = {name.lower(): read_live_table(db, name) for name in sorted(selected)}
    return live, len(names)
