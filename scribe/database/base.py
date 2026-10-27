"""
Base database adapter interface and Row class.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union


@dataclass
class ColumnInfo:
    """
    Description of a table column, as reported by the database.

    type is the database's own spelling (e.g. 'INTEGER' on SQLite,
    'integer' on PostgreSQL), and default is the raw default expression.
    """
    name: str
    type: str
    nullable: bool = True
    default: Optional[str] = None
    primary_key: bool = False


class Row:
    """
    Database row that supports both dict and attribute access.

    Example:
        row['name']   # Dict access
        row.name      # Attribute access
        dict(row)     # Convert to dict
    """

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any):
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getattr__(self, key: str) -> Any:
        if key.startswith('_'):
            return object.__getattribute__(self, key)
        if key in self._data:
            return self._data[key]
        raise AttributeError(f"Row has no attribute '{key}'")

    def __setattr__(self, key: str, value: Any):
        if key.startswith('_'):
            object.__setattr__(self, key, value)
        else:
            self._data[key] = value

    def __repr__(self):
        return f"Row({self._data})"

    def __iter__(self):
        """Allow conversion to dict via dict(row)"""
        return iter(self._data.items())

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dictionary"""
        return self._data.copy()


class DatabaseAdapter(ABC):
    """
    Abstract base class for database adapters.

    All database implementations (SQLite, PostgreSQL, MSSQL)
    inherit from this class and implement its methods.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize database connection.

        Args:
            config: Database configuration
        """
        self.config = config
        self.connection = None

    @abstractmethod
    def connect(self):
        """Establish database connection"""
        pass

    @abstractmethod
    def close(self):
        """Close database connection"""
        pass

    # === Query Methods ===

    @abstractmethod
    def query(self, sql: str, params: Optional[tuple] = None) -> List[Row]:
        """
        Execute SELECT query and return results.

        Args:
            sql: SQL query with ? placeholders
            params: Parameter values

        Returns:
            List of Row objects
        """
        pass

    @abstractmethod
    def execute(self, sql: str, params: Optional[tuple] = None) -> int:
        """
        Execute INSERT/UPDATE/DELETE query.

        Args:
            sql: SQL statement
            params: Parameter values

        Returns:
            Number of affected rows or last insert ID
        """
        pass

    @abstractmethod
    def commit(self):
        """Commit current transaction"""
        pass

    @abstractmethod
    def rollback(self):
        """Rollback current transaction"""
        pass

    # === Convenience Methods ===

    @abstractmethod
    def find(self, table: str, id: Union[int, str]) -> Optional[Row]:
        """
        Find record by primary key (assumed to be 'id').

        Args:
            table: Table name
            id: Primary key value

        Returns:
            Row object or None if not found
        """
        pass

    @abstractmethod
    def where(self, table: str, **conditions) -> List[Row]:
        """
        Find records matching conditions.

        Args:
            table: Table name
            **conditions: Column=value conditions (AND-ed together)

        Returns:
            List of Row objects

        Example:
            users = db.where('users', active=True, role='admin')
        """
        pass

    @abstractmethod
    def insert(self, table: str, **values) -> int:
        """
        Insert record and return new ID.

        Args:
            table: Table name
            **values: Column=value pairs

        Returns:
            Last insert ID

        Example:
            user_id = db.insert('users', username='alice', email='alice@example.com')
        """
        pass

    @abstractmethod
    def update(self, table: str, values: Dict[str, Any], **conditions) -> int:
        """
        Update records matching conditions.

        Args:
            table: Table name
            values: Dict of column=value pairs to update
            **conditions: WHERE conditions (AND-ed together)

        Returns:
            Number of affected rows

        Example:
            db.update('users', {'active': False}, id=user_id)
        """
        pass

    @abstractmethod
    def delete(self, table: str, **conditions) -> int:
        """
        Delete records matching conditions.

        Args:
            table: Table name
            **conditions: WHERE conditions (AND-ed together)

        Returns:
            Number of deleted rows

        Example:
            db.delete('users', id=user_id)
        """
        pass

    # === Introspection ===

    @property
    def dialect(self) -> str:
        """Database type from config: 'sqlite', 'postgresql', or 'mssql'"""
        return self.config.get('type', 'sqlite').lower()

    def get_tables(self) -> List[str]:
        """
        List tables in the database, sorted by name.

        PostgreSQL names are schema-qualified ('public.users').
        """
        raise NotImplementedError(f"Introspection is not supported for '{self.dialect}' databases")

    def get_columns(self, table: str) -> List[ColumnInfo]:
        """
        List a table's columns in declaration order.

        Args:
            table: Table name (PostgreSQL also accepts 'schema.table')

        Returns:
            List of ColumnInfo, empty if the table does not exist
        """
        raise NotImplementedError(f"Introspection is not supported for '{self.dialect}' databases")

    def has_table(self, table: str) -> bool:
        """
        Check whether a table exists.

        Unqualified names on PostgreSQL are looked up in the current schema.
        """
        raise NotImplementedError(f"Introspection is not supported for '{self.dialect}' databases")

    # === Query Builder ===

    def table(self, name: str):
        """
        Get query builder for table.

        Args:
            name: Table name

        Returns:
            QueryBuilder instance

        Example:
            posts = db.table('posts')
                .where(published=True)
                .order_by('-created_at')
                .limit(10)
                .all()
        """
        from scribe.database.query_builder import QueryBuilder
        return QueryBuilder(self, name)

    # === Context Manager Support ===

    def __enter__(self):
        """Support for 'with' statement"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Automatically close connection when exiting 'with' block"""
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False
