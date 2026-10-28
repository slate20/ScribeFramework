"""
Comparing a schema file's managed tables with the live database.

Only managed tables are compared. Each change records whether it is
additive (safe to generate as live SQL) or needs review, and whether it
would destroy data; `scribe schema generate` uses that to decide what to
emit as live SQL and what to comment out.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from scribe.schema.dsl import Column, SchemaDefinition, SqlExpression, Table
from scribe.schema.introspect import LiveTable
from scribe.schema.normalize import declared_default_sql, normalize_default, normalize_type


@dataclass
class Change:
    """
    One difference between a managed table and the database.

    kind is one of: create_table, add_column, drop_column, alter_column_type,
    alter_column_nullable, alter_column_default, alter_column_autoincrement,
    alter_primary_key, add_unique, drop_unique, add_index, drop_index,
    alter_index, add_foreign_key, drop_foreign_key.

    declared/live hold the schema-file object and the database's description
    of the same thing (either may be None). rename is (old, new) when an
    add_column/drop_column pair looks like a renamed column.
    """
    kind: str
    table: str
    description: str
    additive: bool
    destructive: bool = False
    column: Optional[str] = None
    declared: Any = None
    live: Any = None
    rename: Optional[Tuple[str, str]] = None


@dataclass
class SchemaDiff:
    changes: List[Change] = field(default_factory=list)
    in_sync: List[str] = field(default_factory=list)            # managed tables with no changes
    untracked: List[str] = field(default_factory=list)          # live tables the file doesn't mention
    unmanaged: List[str] = field(default_factory=list)          # declared but not managed

    @property
    def additive(self) -> List[Change]:
        return [c for c in self.changes if c.additive]

    @property
    def needs_review(self) -> List[Change]:
        return [c for c in self.changes if not c.additive]

    def changed_tables(self) -> List[str]:
        seen = []
        for change in self.changes:
            if change.table not in seen:
                seen.append(change.table)
        return seen


def diff_schema(definition: SchemaDefinition, live: Dict[str, LiveTable], dialect: str) -> SchemaDiff:
    """
    Compare the managed tables in a schema file with the live database.

    Args:
        definition: Loaded schema file
        live: Output of read_live_schema()
        dialect: The connection's database type
    """
    result = SchemaDiff()

    for table in definition.tables.values():
        if not table.managed:
            result.unmanaged.append(table.name)
            continue

        live_table = live.get(table.name.lower())
        if live_table is None:
            changes = _create_table_changes(table, definition, dialect)
        else:
            changes = _table_changes(table, live_table, definition, dialect)

        if changes:
            result.changes.extend(changes)
        else:
            result.in_sync.append(table.name)

    result.unmanaged.extend(definition.unmanaged.values())
    result.untracked = [t.name for key, t in live.items() if not definition.is_declared(key)]
    return result


def _create_table_changes(table: Table, definition: SchemaDefinition, dialect: str) -> List[Change]:
    changes = [Change(
        kind='create_table', table=table.name, additive=True, declared=table,
        description=f"create table ({len(table.columns)} columns)",
    )]
    for index in definition.indexes_for(table.name):
        changes.append(Change(
            kind='add_index', table=table.name, additive=True, declared=index,
            description=f"add {'unique ' if index.unique else ''}index {index.name} ({', '.join(index.columns)})",
        ))
    return changes


def _table_changes(table: Table, live: LiveTable, definition: SchemaDefinition, dialect: str) -> List[Change]:
    changes = []
    changes.extend(_column_changes(table, live, dialect))
    changes.extend(_primary_key_changes(table, live))
    changes.extend(_index_and_unique_changes(table, live, definition))
    changes.extend(_foreign_key_changes(table, live, dialect))
    return changes


# === Columns ===

def _column_changes(table: Table, live: LiveTable, dialect: str) -> List[Change]:
    changes = []
    live_columns = {c.name.lower(): c for c in live.columns}
    declared_columns = {c.name.lower(): c for c in table.columns}

    added = [c for c in table.columns if c.name.lower() not in live_columns]
    dropped = [c for c in live.columns if c.name.lower() not in declared_columns]

    # One column added and one dropped with the same type looks like a rename
    rename = None
    if len(added) == 1 and len(dropped) == 1:
        if _type_key(added[0].type, dialect) == _type_key(dropped[0].type, dialect):
            rename = (dropped[0].name, added[0].name)

    for column in added:
        reason = _add_column_blocker(column, dialect)
        description = f"add column {column.type}"
        if rename:
            description += f" (possible rename of {rename[0]} → {rename[1]})"
        elif reason:
            description += f" ({reason})"
        changes.append(Change(
            kind='add_column', table=table.name, column=column.name, additive=not rename and not reason,
            declared=column, description=description, rename=rename,
        ))

    for column in dropped:
        description = "column exists in the database but not in the schema file"
        if rename:
            description += f" (possible rename of {rename[0]} → {rename[1]})"
        changes.append(Change(
            kind='drop_column', table=table.name, column=column.name, additive=False, destructive=True,
            live=column, description=description, rename=rename,
        ))

    for column in table.columns:
        live_column = live_columns.get(column.name.lower())
        if live_column is not None:
            changes.extend(_compare_column(table, column, live_column, dialect))
    return changes


def _add_column_blocker(column: Column, dialect: str) -> Optional[str]:
    """Why a column can't safely be added to an existing table in place, or None."""
    if column.primary_key:
        return "primary key columns can't be added in place"
    if not column.nullable and column.default is None:
        return "NOT NULL without a default fails on a table with rows"
    if dialect == 'sqlite':
        if column.unique:
            return "SQLite can't add a UNIQUE column in place"
        if isinstance(column.default, SqlExpression):
            return "SQLite can't add a column with a non-constant default to a table with rows"
    return None


def _type_key(type_name: str, dialect: str) -> str:
    return normalize_type(type_name, dialect)[0]


def _compare_column(table: Table, column: Column, live, dialect: str) -> List[Change]:
    changes = []
    declared_type, type_autoincrement = normalize_type(column.type, dialect)
    live_type, _ = normalize_type(live.type, dialect)

    if declared_type != live_type:
        changes.append(Change(
            kind='alter_column_type', table=table.name, column=column.name, additive=False,
            declared=column, live=live, description=f"type {live.type} → {column.type}",
        ))

    if not column.primary_key and not live.primary_key and column.nullable != live.nullable:
        changes.append(Change(
            kind='alter_column_nullable', table=table.name, column=column.name, additive=False,
            declared=column, live=live,
            description="allow NULL" if column.nullable else "make NOT NULL",
        ))

    declared_autoincrement = column.autoincrement or type_autoincrement
    if declared_autoincrement != live.autoincrement:
        changes.append(Change(
            kind='alter_column_autoincrement', table=table.name, column=column.name, additive=False,
            declared=column, live=live,
            description="add autoincrement" if declared_autoincrement else "remove autoincrement",
        ))
    elif not declared_autoincrement:
        declared_default = normalize_default(declared_default_sql(column.default, dialect), dialect)
        live_default = normalize_default(live.default, dialect)
        if declared_default != live_default:
            changes.append(Change(
                kind='alter_column_default', table=table.name, column=column.name, additive=False,
                declared=column, live=live,
                description=f"default {live_default or 'none'} → {declared_default or 'none'}",
            ))
    return changes


def _primary_key_changes(table: Table, live: LiveTable) -> List[Change]:
    declared = [name.lower() for name in table.primary_key]
    actual = [c.name.lower() for c in live.columns if c.primary_key]
    if sorted(declared) == sorted(actual):
        return []
    return [Change(
        kind='alter_primary_key', table=table.name, additive=False,
        declared=table.primary_key, live=[c.name for c in live.columns if c.primary_key],
        description=f"primary key ({', '.join(c.name for c in live.columns if c.primary_key) or 'none'}) "
                    f"→ ({', '.join(table.primary_key) or 'none'})",
    )]


# === Indexes and UNIQUE ===

def _index_and_unique_changes(table: Table, live: LiveTable, definition: SchemaDefinition) -> List[Change]:
    changes = []
    # Expression indexes can only be tracked with raw_sql(); primary key indexes via primary_key=True
    candidates = {
        index.name.lower(): index for index in live.indexes
        if index.origin != 'primary_key' and None not in index.columns
    }

    for index in definition.indexes_for(table.name):
        live_index = candidates.pop(index.name.lower(), None)
        if live_index is None:
            changes.append(Change(
                kind='add_index', table=table.name, additive=True, declared=index,
                description=f"add {'unique ' if index.unique else ''}index {index.name} ({', '.join(index.columns)})",
            ))
        elif ([c.lower() for c in index.columns] != [c.lower() for c in live_index.columns]
              or index.unique != live_index.unique):
            changes.append(Change(
                kind='alter_index', table=table.name, additive=False, declared=index, live=live_index,
                description=f"index {index.name}: ({', '.join(live_index.columns)})"
                            f"{' unique' if live_index.unique else ''} → ({', '.join(index.columns)})"
                            f"{' unique' if index.unique else ''}",
            ))

    # Remaining single-column unique indexes correspond to Column(unique=True)
    live_unique = {}
    for key, index in list(candidates.items()):
        if index.unique and len(index.columns) == 1:
            live_unique[index.columns[0].lower()] = candidates.pop(key)

    for column in table.columns:
        if column.unique and not column.primary_key and column.name.lower() not in live_unique:
            changes.append(Change(
                kind='add_unique', table=table.name, column=column.name, additive=True, declared=column,
                description="add UNIQUE",
            ))
    declared_unique = {c.name.lower() for c in table.columns if c.unique}
    for column_name, index in live_unique.items():
        if column_name not in declared_unique:
            changes.append(Change(
                kind='drop_unique', table=table.name, column=index.columns[0], additive=False, live=index,
                description=f"UNIQUE ({index.name}) exists in the database but not in the schema file",
            ))

    for index in candidates.values():
        changes.append(Change(
            kind='drop_index', table=table.name, additive=False, live=index,
            description=f"index {index.name} ({', '.join(index.columns)}) exists in the database "
                        f"but not in the schema file",
        ))
    return changes


# === Foreign keys ===

def _foreign_key_changes(table: Table, live: LiveTable, dialect: str) -> List[Change]:
    changes = []
    # Composite foreign keys can't be declared in the DSL, so they aren't compared
    live_keys = {
        (fk.columns[0].lower(), fk.ref_table.lower(), (fk.ref_columns[0] or '').lower()): fk
        for fk in live.foreign_keys if len(fk.columns) == 1
    }
    live_column_names = {c.name.lower() for c in live.columns}

    for column in table.columns:
        fk = column.foreign_key
        # A column being added carries its foreign key in the add_column change
        if fk is None or column.name.lower() not in live_column_names:
            continue
        key = (column.name.lower(), fk.ref_table.lower(), fk.ref_column.lower())
        if live_keys.pop(key, None) is not None:
            continue
        # Adding a constraint to an existing SQLite column requires rebuilding the table
        changes.append(Change(
            kind='add_foreign_key', table=table.name, column=column.name,
            additive=dialect != 'sqlite', declared=column,
            description=f"add foreign key → {fk.target}"
                        + (" (SQLite needs a table rebuild)" if dialect == 'sqlite' else ""),
        ))

    for fk in live_keys.values():
        changes.append(Change(
            kind='drop_foreign_key', table=table.name, column=fk.columns[0], additive=False, live=fk,
            description=f"foreign key → {fk.ref_table}.{fk.ref_columns[0]} exists in the database "
                        f"but not in the schema file",
        ))
    return changes
