"""
Microsoft SQL Server database adapter implementation.
"""

import logging
import pymssql
from typing import List, Optional, Dict, Any, Union
from scribe.database.base import DatabaseAdapter, Row, ColumnInfo, IndexInfo, ForeignKeyInfo

logger = logging.getLogger(__name__)


class MSSQLAdapter(DatabaseAdapter):
    """
    Microsoft SQL Server implementation of DatabaseAdapter.

    Configuration:
        {
            'type': 'mssql',
            'host': 'localhost',
            'port': 1433,
            'user': 'username',
            'password': 'password',
            'database': 'dbname'
        }

    Example:
        config = {
            'type': 'mssql',
            'host': 'localhost',
            'port': 1433,
            'user': 'sa',
            'password': 'MyPassword123',
            'database': 'mydb'
        }
        db = MSSQLAdapter(config)
        users = db.query("SELECT * FROM users")
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.connect()

    def connect(self):
        """Establish MSSQL connection"""
        # Extract connection parameters
        host = self.config.get('host', 'localhost')
        port = self.config.get('port', 1433)
        user = self.config.get('user')
        password = self.config.get('password')
        database = self.config.get('database')

        if not user or not database:
            raise ValueError("MSSQL requires 'user' and 'database' in config")

        # Connect using pymssql
        self.connection = pymssql.connect(
            server=host,
            port=port,
            user=user,
            password=password,
            database=database,
            as_dict=True  # Return rows as dictionaries
        )
        self.connection.autocommit(False)  # Manual transaction control

    def close(self):
        """Close MSSQL connection"""
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

    def _reconnect(self):
        """Close and re-establish the connection."""
        logger.warning("MSSQL connection lost, attempting reconnect...")
        self.close()
        self.connect()
        logger.info("MSSQL reconnected successfully.")

    def _execute_with_reconnect(self, fn):
        """Run fn(), reconnecting once if a connection-level error is raised."""
        try:
            return fn()
        except pymssql.OperationalError as exc:
            logger.warning("MSSQL connection error: %s. Reconnecting...", exc)
            self._reconnect()
            return fn()

    def _convert_placeholders(self, sql: str) -> str:
        """
        Convert SQLite-style ? placeholders to MSSQL %s placeholders.

        Args:
            sql: SQL query with ? placeholders

        Returns:
            SQL query with %s placeholders
        """
        return sql.replace('?', '%s')

    def query(self, sql: str, params: Optional[tuple] = None) -> List[Row]:
        """
        Execute SELECT query and return results.

        Args:
            sql: SQL query with ? placeholders (will be converted to %s)
            params: Parameter values

        Returns:
            List of Row objects
        """
        sql = self._convert_placeholders(sql)

        def _run():
            cursor = self.connection.cursor(as_dict=True)
            try:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                rows = []
                for row_data in cursor.fetchall():
                    rows.append(Row(dict(row_data)))
                return rows
            finally:
                cursor.close()

        return self._execute_with_reconnect(_run)

    def execute(self, sql: str, params: Optional[tuple] = None) -> int:
        """
        Execute INSERT/UPDATE/DELETE query.

        Args:
            sql: SQL statement with ? placeholders (will be converted to %s)
            params: Parameter values

        Returns:
            Number of affected rows or last insert ID (for INSERT)
        """
        sql = self._convert_placeholders(sql)

        def _run():
            cursor = self.connection.cursor()
            try:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)

                if sql.strip().upper().startswith('INSERT'):
                    cursor.execute("SELECT SCOPE_IDENTITY() as id")
                    result = cursor.fetchone()
                    if result and result.get('id'):
                        return int(result['id'])
                    return cursor.rowcount
                else:
                    return cursor.rowcount
            finally:
                cursor.close()

        return self._execute_with_reconnect(_run)

    def commit(self):
        """Commit current transaction"""
        if self.connection:
            self.connection.commit()

    def rollback(self):
        """Rollback current transaction"""
        if self.connection:
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
        sql = f"SELECT * FROM {table} WHERE id = %s"

        cursor = self.connection.cursor(as_dict=True)

        try:
            cursor.execute(sql, (id,))
            row_data = cursor.fetchone()

            if row_data:
                return Row(dict(row_data))
            return None
        finally:
            cursor.close()

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
            where_parts.append(f"{column} = %s")
            params.append(value)

        where_clause = " AND ".join(where_parts)
        sql = f"SELECT * FROM {table} WHERE {where_clause}"

        cursor = self.connection.cursor(as_dict=True)

        try:
            cursor.execute(sql, tuple(params))

            rows = []
            for row_data in cursor.fetchall():
                rows.append(Row(dict(row_data)))

            return rows
        finally:
            cursor.close()

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
        placeholders = ['%s' for _ in columns]
        params = [values[col] for col in columns]

        columns_str = ', '.join(columns)
        placeholders_str = ', '.join(placeholders)

        # Insert and get ID using OUTPUT clause (MSSQL-specific)
        sql = f"INSERT INTO {table} ({columns_str}) OUTPUT INSERTED.id VALUES ({placeholders_str})"

        cursor = self.connection.cursor()

        try:
            cursor.execute(sql, tuple(params))
            result = cursor.fetchone()
            if result:
                # OUTPUT INSERTED.id returns a dict with 'id' key
                return result.get('id', 0) if isinstance(result, dict) else result[0]
            return 0
        except Exception as e:
            # Fallback: try without OUTPUT clause and use SCOPE_IDENTITY()
            sql_fallback = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders_str})"
            cursor.execute(sql_fallback, tuple(params))
            cursor.execute("SELECT SCOPE_IDENTITY() as id")
            result = cursor.fetchone()
            if result:
                return int(result.get('id', 0))
            return 0
        finally:
            cursor.close()

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
            set_parts.append(f"{column} = %s")
            params.append(value)

        set_clause = ", ".join(set_parts)

        # Build WHERE clause
        if conditions:
            where_parts = []
            for column, value in conditions.items():
                where_parts.append(f"{column} = %s")
                params.append(value)
            where_clause = " WHERE " + " AND ".join(where_parts)
        else:
            where_clause = ""

        sql = f"UPDATE {table} SET {set_clause}{where_clause}"

        cursor = self.connection.cursor()

        try:
            cursor.execute(sql, tuple(params))
            return cursor.rowcount
        finally:
            cursor.close()

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
            where_parts.append(f"{column} = %s")
            params.append(value)

        where_clause = " AND ".join(where_parts)
        sql = f"DELETE FROM {table} WHERE {where_clause}"

        cursor = self.connection.cursor()

        try:
            cursor.execute(sql, tuple(params))
            return cursor.rowcount
        finally:
            cursor.close()

    # === Introspection ===

    def get_tables(self, include_views: bool = False) -> List[str]:
        """List base tables (and optionally views) in the database, sorted by name."""
        types = "('BASE TABLE', 'VIEW')" if include_views else "('BASE TABLE')"
        rows = self.query(f"""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE IN {types}
            ORDER BY TABLE_NAME
        """)
        return [row['TABLE_NAME'] for row in rows]

    def get_columns(self, table: str) -> List[ColumnInfo]:
        """
        List a table's columns in declaration order.

        Types include length/precision ('nvarchar(255)', 'nvarchar(max)', 'decimal(12,2)').
        IDENTITY columns are reported as autoincrement. Unqualified names match
        any schema, since get_tables() lists tables from every schema without
        qualifying them.
        """
        schema, _, name = table.rpartition('.')
        schema_filter = "TABLE_SCHEMA = ?" if schema else "1 = 1"
        schema_params = (schema,) if schema else ()

        pk_rows = self.query(f"""
            SELECT kcu.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
              ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
             AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
             AND tc.TABLE_NAME = kcu.TABLE_NAME
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
              AND tc.{schema_filter} AND tc.TABLE_NAME = ?
        """, schema_params + (name,))
        primary_keys = {row['COLUMN_NAME'] for row in pk_rows}

        rows = self.query(f"""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
                   CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE,
                   COLUMNPROPERTY(
                       OBJECT_ID(QUOTENAME(TABLE_SCHEMA) + '.' + QUOTENAME(TABLE_NAME)),
                       COLUMN_NAME, 'IsIdentity'
                   ) AS IS_IDENTITY
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE {schema_filter} AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, schema_params + (name,))
        return [
            ColumnInfo(
                name=row['COLUMN_NAME'],
                type=self._format_type(row),
                nullable=row['IS_NULLABLE'] == 'YES',
                default=row['COLUMN_DEFAULT'],
                primary_key=row['COLUMN_NAME'] in primary_keys,
                autoincrement=bool(row['IS_IDENTITY']),
            )
            for row in rows
        ]

    @staticmethod
    def _format_type(row) -> str:
        """Build a type name with its length or precision from INFORMATION_SCHEMA.COLUMNS fields."""
        data_type = row['DATA_TYPE']
        if data_type in ('char', 'varchar', 'nchar', 'nvarchar', 'binary', 'varbinary'):
            length = row['CHARACTER_MAXIMUM_LENGTH']
            return f"{data_type}({'max' if length == -1 else length})"
        if data_type in ('decimal', 'numeric'):
            return f"{data_type}({row['NUMERIC_PRECISION']},{row['NUMERIC_SCALE']})"
        return data_type

    def has_table(self, table: str) -> bool:
        """Check whether a table exists (unqualified names use the default schema)."""
        schema, _, name = table.rpartition('.')
        if schema:
            sql = "SELECT 1 AS found FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?"
            params = (schema, name)
        else:
            sql = "SELECT 1 AS found FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = SCHEMA_NAME() AND TABLE_NAME = ?"
            params = (name,)
        return bool(self.query(sql, params))

    def get_indexes(self, table: str) -> List[IndexInfo]:
        """List a table's indexes, including those backing PRIMARY KEY and UNIQUE constraints."""
        rows = self.query("""
            SELECT i.name AS index_name, i.is_unique, i.is_primary_key, i.is_unique_constraint,
                   c.name AS column_name
            FROM sys.indexes i
            JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE i.object_id = OBJECT_ID(?) AND i.name IS NOT NULL AND ic.is_included_column = 0
            ORDER BY i.name, ic.key_ordinal
        """, (table,))

        indexes = {}
        for row in rows:
            if row['index_name'] not in indexes:
                if row['is_primary_key']:
                    origin = 'primary_key'
                elif row['is_unique_constraint']:
                    origin = 'unique'
                else:
                    origin = 'index'
                indexes[row['index_name']] = IndexInfo(
                    name=row['index_name'], columns=[], unique=bool(row['is_unique']), origin=origin
                )
            indexes[row['index_name']].columns.append(row['column_name'])
        return list(indexes.values())

    def get_foreign_keys(self, table: str) -> List[ForeignKeyInfo]:
        """List a table's foreign keys."""
        rows = self.query("""
            SELECT fk.name AS fk_name,
                   pc.name AS column_name,
                   OBJECT_SCHEMA_NAME(fk.parent_object_id) AS table_schema,
                   OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS ref_schema,
                   OBJECT_NAME(fk.referenced_object_id) AS ref_table,
                   rc.name AS ref_column
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
            JOIN sys.columns pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
            JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
            WHERE fk.parent_object_id = OBJECT_ID(?)
            ORDER BY fk.name, fkc.constraint_column_id
        """, (table,))

        foreign_keys = {}
        for row in rows:
            if row['fk_name'] not in foreign_keys:
                ref_table = row['ref_table']
                if row['ref_schema'] != row['table_schema']:
                    ref_table = f"{row['ref_schema']}.{ref_table}"
                foreign_keys[row['fk_name']] = ForeignKeyInfo(
                    columns=[], ref_table=ref_table, name=row['fk_name']
                )
            foreign_keys[row['fk_name']].columns.append(row['column_name'])
            foreign_keys[row['fk_name']].ref_columns.append(row['ref_column'])
        return list(foreign_keys.values())
