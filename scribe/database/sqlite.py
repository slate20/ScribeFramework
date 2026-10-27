"""
SQLite database adapter implementation.
"""

import re
import sqlite3
from typing import List, Optional, Dict, Any, Union
from scribe.database.base import DatabaseAdapter, Row, ColumnInfo, IndexInfo, ForeignKeyInfo


class SQLiteAdapter(DatabaseAdapter):
    """
    SQLite implementation of DatabaseAdapter.

    Configuration:
        {
            'type': 'sqlite',
            'database': 'path/to/database.db'  # Relative or absolute path
        }

    Example:
        config = {'type': 'sqlite', 'database': 'app.db'}
        db = SQLiteAdapter(config)
        users = db.query("SELECT * FROM users")
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.connect()

    def connect(self):
        """Establish SQLite connection"""
        database_path = self.config.get('database', 'app.db')

        # Enable Row factory for dict-like access
        self.connection = sqlite3.connect(
            database_path,
            check_same_thread=False,  # Allow multi-threaded access
            isolation_level=None  # Autocommit mode (we'll handle transactions manually)
        )

        # Enable foreign key support
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self):
        """Close SQLite connection"""
        if self.connection:
            self.connection.close()
            self.connection = None

    def query(self, sql: str, params: Optional[tuple] = None) -> List[Row]:
        """
        Execute SELECT query and return results.

        Args:
            sql: SQL query with ? placeholders
            params: Parameter values

        Returns:
            List of Row objects
        """
        cursor = self.connection.cursor()

        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        # Get column names
        columns = [desc[0] for desc in cursor.description] if cursor.description else []

        # Fetch all rows and convert to Row objects
        rows = []
        for row_data in cursor.fetchall():
            row_dict = dict(zip(columns, row_data))
            rows.append(Row(row_dict))

        cursor.close()
        return rows

    def execute(self, sql: str, params: Optional[tuple] = None) -> int:
        """
        Execute INSERT/UPDATE/DELETE query.

        Args:
            sql: SQL statement
            params: Parameter values

        Returns:
            Number of affected rows or last insert ID (for INSERT)
        """
        cursor = self.connection.cursor()

        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        # For INSERT, return the last row ID
        if sql.strip().upper().startswith('INSERT'):
            result = cursor.lastrowid
        else:
            # For UPDATE/DELETE, return number of affected rows
            result = cursor.rowcount

        cursor.close()
        return result

    def commit(self):
        """Commit current transaction"""
        # In autocommit mode, but we can still explicitly commit
        self.connection.commit()

    def rollback(self):
        """Rollback current transaction"""
        self.connection.rollback()

    def find(self, table: str, id: Union[int, str]) -> Optional[Row]:
        """
        Find record by primary key (assumed to be 'id').

        Args:
            table: Table name
            id: Primary key value

        Returns:
            Row object or None if not found
        """
        sql = f"SELECT * FROM {table} WHERE id = ?"
        results = self.query(sql, (id,))
        return results[0] if results else None

    def where(self, table: str, **conditions) -> List[Row]:
        """
        Find records matching conditions.

        Args:
            table: Table name
            **conditions: Column=value conditions (AND-ed together)

        Returns:
            List of Row objects
        """
        if not conditions:
            # No conditions, return all rows
            return self.query(f"SELECT * FROM {table}")

        # Build WHERE clause
        where_parts = []
        params = []
        for column, value in conditions.items():
            where_parts.append(f"{column} = ?")
            params.append(value)

        where_clause = " AND ".join(where_parts)
        sql = f"SELECT * FROM {table} WHERE {where_clause}"

        return self.query(sql, tuple(params))

    def insert(self, table: str, **values) -> int:
        """
        Insert record and return new ID.

        Args:
            table: Table name
            **values: Column=value pairs

        Returns:
            Last insert ID
        """
        if not values:
            raise ValueError("Cannot insert empty record")

        columns = list(values.keys())
        placeholders = ['?' for _ in columns]
        params = [values[col] for col in columns]

        columns_str = ', '.join(columns)
        placeholders_str = ', '.join(placeholders)

        sql = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders_str})"

        return self.execute(sql, tuple(params))

    def update(self, table: str, values: Dict[str, Any], **conditions) -> int:
        """
        Update records matching conditions.

        Args:
            table: Table name
            values: Dict of column=value pairs to update
            **conditions: WHERE conditions (AND-ed together)

        Returns:
            Number of affected rows
        """
        if not values:
            raise ValueError("Cannot update with empty values")

        # Build SET clause
        set_parts = []
        params = []
        for column, value in values.items():
            set_parts.append(f"{column} = ?")
            params.append(value)

        set_clause = ", ".join(set_parts)

        # Build WHERE clause
        if conditions:
            where_parts = []
            for column, value in conditions.items():
                where_parts.append(f"{column} = ?")
                params.append(value)
            where_clause = " WHERE " + " AND ".join(where_parts)
        else:
            where_clause = ""

        sql = f"UPDATE {table} SET {set_clause}{where_clause}"

        return self.execute(sql, tuple(params))

    def delete(self, table: str, **conditions) -> int:
        """
        Delete records matching conditions.

        Args:
            table: Table name
            **conditions: WHERE conditions (AND-ed together)

        Returns:
            Number of deleted rows
        """
        if not conditions:
            raise ValueError("Delete requires at least one condition (use 'DELETE FROM table' directly if you really want to delete all rows)")

        # Build WHERE clause
        where_parts = []
        params = []
        for column, value in conditions.items():
            where_parts.append(f"{column} = ?")
            params.append(value)

        where_clause = " AND ".join(where_parts)
        sql = f"DELETE FROM {table} WHERE {where_clause}"

        return self.execute(sql, tuple(params))

    # === Introspection ===

    def get_tables(self) -> List[str]:
        """List tables in the database, sorted by name."""
        rows = self.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [row['name'] for row in rows]

    def get_columns(self, table: str) -> List[ColumnInfo]:
        """List a table's columns in declaration order."""
        rows = self.query("SELECT * FROM pragma_table_info(?)", (table,))

        # AUTOINCREMENT only appears in the CREATE TABLE statement
        table_sql = self.query("SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (table,))
        has_autoincrement = bool(table_sql) and bool(
            re.search(r'\bAUTOINCREMENT\b', table_sql[0]['sql'] or '', re.IGNORECASE)
        )

        return [
            ColumnInfo(
                name=row['name'],
                type=row['type'],
                nullable=not row['notnull'],
                default=row['dflt_value'],
                primary_key=bool(row['pk']),
                autoincrement=has_autoincrement and bool(row['pk']),
            )
            for row in rows
        ]

    def has_table(self, table: str) -> bool:
        """Check whether a table exists."""
        rows = self.query("SELECT 1 AS found FROM sqlite_master WHERE type='table' AND name = ?", (table,))
        return bool(rows)

    def get_indexes(self, table: str) -> List[IndexInfo]:
        """List a table's indexes, including those backing PRIMARY KEY and UNIQUE constraints."""
        origins = {'c': 'index', 'u': 'unique', 'pk': 'primary_key'}
        indexes = []
        for row in self.query("SELECT * FROM pragma_index_list(?) ORDER BY name", (table,)):
            columns = self.query("SELECT name FROM pragma_index_info(?) ORDER BY seqno", (row['name'],))
            indexes.append(IndexInfo(
                name=row['name'],
                columns=[column['name'] for column in columns],
                unique=bool(row['unique']),
                origin=origins.get(row['origin'], 'index'),
            ))
        return indexes

    def get_foreign_keys(self, table: str) -> List[ForeignKeyInfo]:
        """List a table's foreign keys."""
        foreign_keys = {}
        for row in self.query("SELECT * FROM pragma_foreign_key_list(?) ORDER BY id, seq", (table,)):
            fk = foreign_keys.setdefault(row['id'], ForeignKeyInfo(columns=[], ref_table=row['table']))
            fk.columns.append(row['from'])
            fk.ref_columns.append(row['to'])

        # "REFERENCES users" without a column list points at the referenced primary key
        for fk in foreign_keys.values():
            if any(column is None for column in fk.ref_columns):
                fk.ref_columns = [c.name for c in self.get_columns(fk.ref_table) if c.primary_key]
        return list(foreign_keys.values())
