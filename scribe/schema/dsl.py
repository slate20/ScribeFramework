"""
Declarative schema DSL used in schemas/schema_{name}.py files.

Every Table, Index, raw_sql and unmanaged call registers itself with the
schema file currently being loaded (see scribe.schema.loader). Calls made
outside a load (e.g. importing the DSL elsewhere) build objects but
register nothing.

Example:
    from scribe.schema import Table, Column, Index, ForeignKey, sql

    Table("orders",
        Column("id", "INTEGER", primary_key=True, autoincrement=True),
        Column("status", "TEXT", default="open"),
        Column("user_id", "INTEGER", ForeignKey("users.id")),
        Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
    )

    Index("idx_orders_status", "orders", ["status", "created_at"])
"""

import json
from typing import Any, Dict, List, Optional


class SchemaError(ValueError):
    """Raised when a schema file is invalid."""


class SqlExpression:
    """A raw SQL expression used as a column default, e.g. sql("CURRENT_TIMESTAMP")."""

    def __init__(self, text: str):
        if not isinstance(text, str) or not text.strip():
            raise SchemaError("sql() needs a non-empty SQL expression")
        self.text = text.strip()

    def __eq__(self, other):
        return isinstance(other, SqlExpression) and other.text == self.text

    def __hash__(self):
        return hash(self.text)

    def __repr__(self):
        return f"sql({json.dumps(self.text)})"


def sql(text: str) -> SqlExpression:
    """Mark a default as a SQL expression rather than a literal value."""
    return SqlExpression(text)


class ForeignKey:
    """
    Column-level foreign key.

    Args:
        target: "table.column", or "schema.table.column" on PostgreSQL
    """

    def __init__(self, target: str):
        table, _, column = target.rpartition('.')
        if not table or not column:
            raise SchemaError(f"ForeignKey({target!r}) must name a column, e.g. ForeignKey('users.id')")
        self.target = target
        self.ref_table = table
        self.ref_column = column

    def __repr__(self):
        return f"ForeignKey({json.dumps(self.target)})"


class Column:
    """
    A table column.

    Args:
        name: Column name
        type: The connection's native type, e.g. "INTEGER", "NUMERIC(12,2)", "varchar(255)"
        *constraints: Optional ForeignKey
        primary_key: Part of the primary key (set on several columns for a composite key)
        autoincrement: Database-assigned value (AUTOINCREMENT / SERIAL / IDENTITY)
        nullable: Allow NULL (ignored for primary key columns)
        unique: Single-column UNIQUE constraint
        default: Literal value (str, int, float, bool) or sql("...") expression
    """

    def __init__(self, name: str, type: str, *constraints, primary_key: bool = False,
                 autoincrement: bool = False, nullable: bool = True, unique: bool = False,
                 default: Any = None):
        if not isinstance(name, str) or not name:
            raise SchemaError("Column name must be a non-empty string")
        if not isinstance(type, str) or not type.strip():
            raise SchemaError(f"Column {name!r}: type must be a string such as \"INTEGER\" or \"TEXT\"")
        if default is not None and not isinstance(default, (str, int, float, bool, SqlExpression)):
            raise SchemaError(
                f"Column {name!r}: default must be a str, int, float, bool, or sql(\"...\") "
                f"(got {default!r})"
            )

        self.foreign_key: Optional[ForeignKey] = None
        for constraint in constraints:
            if not isinstance(constraint, ForeignKey):
                raise SchemaError(
                    f"Column {name!r}: unexpected argument {constraint!r}. "
                    f"Only ForeignKey(...) may be passed positionally after the type."
                )
            if self.foreign_key is not None:
                raise SchemaError(f"Column {name!r}: only one ForeignKey per column is supported")
            self.foreign_key = constraint

        self.name = name
        self.type = type.strip()
        self.primary_key = primary_key
        self.autoincrement = autoincrement
        self.nullable = nullable and not primary_key
        self.unique = unique
        self.default = default

    def __repr__(self):
        return f"Column({self.name!r}, {self.type!r})"


class Table:
    """
    A table in this connection.

    Args:
        name: Table name ("schema.table" for another PostgreSQL schema)
        *columns: Column definitions (optional when managed=False)
        managed: Whether Scribe generates migrations for this table.
                 Tables added by `scribe schema pull` start as managed=False.
    """

    def __init__(self, name: str, *columns: Column, managed: bool = True):
        if not isinstance(name, str) or not name:
            raise SchemaError("Table name must be a non-empty string")
        for column in columns:
            if not isinstance(column, Column):
                raise SchemaError(f"Table {name!r}: expected Column(...), got {column!r}")
        if managed and not columns:
            raise SchemaError(f"Table {name!r}: a managed table needs at least one Column")

        seen = set()
        for column in columns:
            if column.name.lower() in seen:
                raise SchemaError(f"Table {name!r}: column {column.name!r} is defined twice")
            seen.add(column.name.lower())

        self.name = name
        self.columns: List[Column] = list(columns)
        self.managed = managed
        _register('table', self)

    @property
    def primary_key(self) -> List[str]:
        return [column.name for column in self.columns if column.primary_key]

    def __repr__(self):
        return f"Table({self.name!r}, managed={self.managed})"


class Index:
    """
    An index on a table.

    Args:
        name: Index name
        table: Table name
        columns: Column names, in index order
        unique: Create a UNIQUE index
    """

    def __init__(self, name: str, table: str, columns: List[str], unique: bool = False):
        if isinstance(columns, str):
            columns = [columns]
        if not columns or not all(isinstance(c, str) and c for c in columns):
            raise SchemaError(f"Index {name!r}: columns must be a non-empty list of column names")
        self.name = name
        self.table = table
        self.columns = list(columns)
        self.unique = unique
        _register('index', self)

    def __repr__(self):
        return f"Index({self.name!r}, {self.table!r}, {self.columns!r})"


class RawSQL:
    """A named block of SQL that Scribe tracks but does not diff."""

    def __init__(self, name: str, sql_text: str):
        if not isinstance(name, str) or not name:
            raise SchemaError("raw_sql() needs a name as its first argument")
        if not isinstance(sql_text, str) or not sql_text.strip():
            raise SchemaError(f"raw_sql({name!r}) needs SQL as its second argument")
        self.name = name
        self.sql = sql_text.strip()

    def __repr__(self):
        return f"raw_sql({self.name!r})"


def raw_sql(name: str, sql_text: str) -> RawSQL:
    """
    Declare a named block of SQL (views, expression indexes, database-specific features).

    The block should be safe to run more than once (IF NOT EXISTS, CREATE OR REPLACE).
    """
    block = RawSQL(name, sql_text)
    _register('raw_sql', block)
    return block


def unmanaged(*names: str):
    """Declare tables that exist but that Scribe should never migrate or report as untracked."""
    for name in names:
        if not isinstance(name, str) or not name:
            raise SchemaError(f"unmanaged() takes table names (got {name!r})")
        _register('unmanaged', name)


class SchemaDefinition:
    """Everything one schema file declared."""

    def __init__(self, source: Optional[str] = None):
        self.source = source
        self.tables: Dict[str, Table] = {}       # lowercased name -> Table
        self.indexes: List[Index] = []
        self.raw_sql: Dict[str, RawSQL] = {}
        self.unmanaged: Dict[str, str] = {}      # lowercased name -> name

    def add(self, kind: str, obj):
        if kind == 'table':
            self._check_new_table_name(obj.name)
            self.tables[obj.name.lower()] = obj
        elif kind == 'unmanaged':
            self._check_new_table_name(obj)
            self.unmanaged[obj.lower()] = obj
        elif kind == 'index':
            if any(index.name.lower() == obj.name.lower() for index in self.indexes):
                raise SchemaError(f"Index {obj.name!r} is defined twice")
            self.indexes.append(obj)
        elif kind == 'raw_sql':
            if obj.name in self.raw_sql:
                raise SchemaError(f"raw_sql({obj.name!r}) is defined twice")
            self.raw_sql[obj.name] = obj

    def _check_new_table_name(self, name: str):
        if name.lower() in self.tables or name.lower() in self.unmanaged:
            raise SchemaError(f"Table {name!r} is declared more than once")

    def validate(self):
        """Check references between declarations once the whole file has loaded."""
        for index in self.indexes:
            table = self.tables.get(index.table.lower())
            if table is None:
                raise SchemaError(f"Index {index.name!r} refers to table {index.table!r}, which is not declared")
            if table.columns:
                known = {column.name.lower() for column in table.columns}
                for column in index.columns:
                    if column.lower() not in known:
                        raise SchemaError(
                            f"Index {index.name!r} refers to column {column!r}, "
                            f"which table {table.name!r} does not declare"
                        )

    @property
    def managed_tables(self) -> List[Table]:
        return [table for table in self.tables.values() if table.managed]

    def indexes_for(self, table_name: str) -> List[Index]:
        return [index for index in self.indexes if index.table.lower() == table_name.lower()]

    def is_declared(self, table_name: str) -> bool:
        return table_name.lower() in self.tables or table_name.lower() in self.unmanaged


# The schema file currently being loaded; see scribe.schema.loader.
_active: Optional[SchemaDefinition] = None


def _register(kind: str, obj):
    if _active is not None:
        _active.add(kind, obj)
