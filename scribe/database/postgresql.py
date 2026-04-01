"""
PostgreSQL database adapter implementation with automatic reconnection.

Handles dropped connections transparently by detecting stale connections and
retrying the failed operation once after re-establishing the connection.
"""

import logging
import time
import psycopg2
import psycopg2.extras
import psycopg2.extensions
from typing import List, Optional, Dict, Any, Union
from scribe.database.base import DatabaseAdapter, Row

logger = logging.getLogger(__name__)


class PostgreSQLAdapter(DatabaseAdapter):
    """
    PostgreSQL implementation of DatabaseAdapter.

    Includes automatic reconnection: if a query fails due to a dropped
    connection (e.g. the database service restarted), the adapter will
    attempt to reconnect and retry the operation once before raising.

    Configuration:
        {
            'type': 'postgresql',
            'host': 'localhost',
            'port': 5432,
            'user': 'username',
            'password': 'password',
            'database': 'dbname',

            # Optional reconnection settings:
            'reconnect_attempts': 5,       # Max retries before giving up (default: 5)
            'reconnect_delay': 2.0,        # Seconds between retries (default: 2.0)
            'reconnect_backoff': 2.0       # Exponential backoff multiplier (default: 2.0)
        }

    Example:
        config = {
            'type': 'postgresql',
            'host': 'localhost',
            'port': 5432,
            'user': 'myuser',
            'password': 'mypassword',
            'database': 'mydb'
        }
        db = PostgreSQLAdapter(config)
        users = db.query("SELECT * FROM users")
    """

    # psycopg2 error codes that indicate a lost/broken connection
    # rather than a logic error (bad SQL, constraint violation, etc.)
    _RECOVERABLE_ERROR_CODES = frozenset({
        psycopg2.OperationalError,
        psycopg2.InterfaceError,
    })

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Reconnection settings
        self._reconnect_attempts: int = config.get('reconnect_attempts', 5)
        self._reconnect_delay: float = float(config.get('reconnect_delay', 2.0))
        self._reconnect_backoff: float = float(config.get('reconnect_backoff', 2.0))
        self.connect()

    # ------------------------------------------------------------------ #
    #  Connection management                                               #
    # ------------------------------------------------------------------ #

    def connect(self):
        """Establish (or re-establish) the PostgreSQL connection."""
        host = self.config.get('host', 'localhost')
        port = self.config.get('port', 5432)
        user = self.config.get('user')
        password = self.config.get('password')
        database = self.config.get('database')

        if not user or not database:
            raise ValueError("PostgreSQL requires 'user' and 'database' in config")

        conn_params = {
            'host': host,
            'port': port,
            'user': user,
            'database': database,
        }
        if password:
            conn_params['password'] = password

        self.connection = psycopg2.connect(**conn_params)
        self.connection.autocommit = False

    def close(self):
        """Close PostgreSQL connection."""
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

    def _is_connection_alive(self) -> bool:
        """
        Check whether the current connection is still usable.

        Uses psycopg2's closed attribute:
          0 = open, 1 = closed, 2 = broken
        """
        if self.connection is None:
            return False
        if self.connection.closed != 0:
            return False
        # Also verify the connection is in a usable transaction state
        if self.connection.get_transaction_status() == psycopg2.extensions.TRANSACTION_STATUS_INERROR:
            return False
        return True

    def _reconnect_with_retry(self):
        """
        Attempt to reconnect, retrying up to `_reconnect_attempts` times
        with exponential back-off between attempts.

        Raises:
            psycopg2.OperationalError: if all attempts are exhausted.
        """
        delay = self._reconnect_delay

        for attempt in range(1, self._reconnect_attempts + 1):
            try:
                logger.warning(
                    "PostgreSQL connection lost. Reconnection attempt %d/%d …",
                    attempt, self._reconnect_attempts,
                )
                self.close()
                self.connect()
                logger.info("PostgreSQL reconnected successfully.")
                return
            except Exception as exc:
                logger.warning("Reconnect attempt %d failed: %s", attempt, exc)
                if attempt < self._reconnect_attempts:
                    time.sleep(delay)
                    delay *= self._reconnect_backoff

        raise psycopg2.OperationalError(
            f"Could not reconnect to PostgreSQL after {self._reconnect_attempts} attempts."
        )

    def _is_recoverable(self, exc: Exception) -> bool:
        """Return True if the exception looks like a dropped-connection error."""
        return isinstance(exc, tuple(self._RECOVERABLE_ERROR_CODES))

    def _ensure_connection(self):
        """
        Verify the connection is alive, reconnecting if necessary.
        Called as a lightweight pre-flight before every operation.
        """
        if not self._is_connection_alive():
            logger.warning("Connection found dead before operation; attempting reconnect.")
            self._reconnect_with_retry()

    # ------------------------------------------------------------------ #
    #  Internal retry wrapper                                              #
    # ------------------------------------------------------------------ #

    def _execute_with_retry(self, fn, *args, **kwargs):
        """
        Execute `fn(*args, **kwargs)`, retrying once after reconnection if
        the connection was dropped mid-flight.

        This covers two failure modes:
          1. Connection is already dead  →  caught by _ensure_connection()
          2. Connection dies during the call  →  caught here, then retried

        Args:
            fn: Callable that performs the actual DB work
            *args, **kwargs: Forwarded to fn

        Returns:
            Whatever fn returns.

        Raises:
            Exception: Re-raises if the error is not connection-related, or
                       if the retry itself also fails.
        """
        self._ensure_connection()
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if not self._is_recoverable(exc):
                raise
            # Mid-flight connection drop — roll back any partial work,
            # reconnect, then try once more.
            logger.warning("Connection dropped mid-operation: %s. Reconnecting…", exc)
            try:
                self.rollback()
            except Exception:
                pass
            self._reconnect_with_retry()
            # Second attempt — let any exception propagate naturally
            return fn(*args, **kwargs)

    # ------------------------------------------------------------------ #
    #  Placeholder conversion                                             #
    # ------------------------------------------------------------------ #

    def _convert_placeholders(self, sql: str) -> str:
        """Convert SQLite-style ? placeholders to PostgreSQL %s placeholders."""
        return sql.replace('?', '%s')

    # ------------------------------------------------------------------ #
    #  Public query methods (each delegates to _execute_with_retry)       #
    # ------------------------------------------------------------------ #

    def query(self, sql: str, params: Optional[tuple] = None) -> List[Row]:
        """Execute SELECT query and return results."""
        def _run():
            pg_sql = self._convert_placeholders(sql)
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cursor.execute(pg_sql, params or None)
                return [Row(dict(row)) for row in cursor.fetchall()]
            finally:
                cursor.close()

        return self._execute_with_retry(_run)

    def execute(self, sql: str, params: Optional[tuple] = None) -> int:
        """Execute INSERT/UPDATE/DELETE query and return affected rows or new ID."""
        def _run():
            pg_sql = self._convert_placeholders(sql)
            cursor = self.connection.cursor()
            try:
                cursor.execute(pg_sql, params or None)
                if pg_sql.strip().upper().startswith('INSERT'):
                    if 'RETURNING' in pg_sql.upper():
                        result = cursor.fetchone()
                        return result[0] if result else cursor.rowcount
                    return cursor.rowcount
                return cursor.rowcount
            finally:
                cursor.close()

        return self._execute_with_retry(_run)

    def commit(self):
        """Commit current transaction."""
        if self.connection:
            self.connection.commit()

    def rollback(self):
        """Rollback current transaction."""
        if self.connection and not self.connection.closed:
            try:
                self.connection.rollback()
            except Exception:
                pass

    def find(self, table: str, id: Union[int, str]) -> Optional[Row]:
        """Find record by primary key."""
        def _run():
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (id,))
                row_data = cursor.fetchone()
                return Row(dict(row_data)) if row_data else None
            finally:
                cursor.close()

        return self._execute_with_retry(_run)

    def where(self, table: str, **conditions) -> List[Row]:
        """Find records matching conditions."""
        if not conditions:
            return self.query(f"SELECT * FROM {table}")

        def _run():
            where_parts = [f"{col} = %s" for col in conditions]
            params = list(conditions.values())
            sql = f"SELECT * FROM {table} WHERE {' AND '.join(where_parts)}"
            cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                cursor.execute(sql, tuple(params))
                return [Row(dict(row)) for row in cursor.fetchall()]
            finally:
                cursor.close()

        return self._execute_with_retry(_run)

    def insert(self, table: str, **values) -> int:
        """Insert record and return new ID."""
        if not values:
            raise ValueError("Cannot insert empty record")

        def _run():
            columns = list(values.keys())
            placeholders = ['%s'] * len(columns)
            params = [values[col] for col in columns]
            sql = (
                f"INSERT INTO {table} ({', '.join(columns)}) "
                f"VALUES ({', '.join(placeholders)}) RETURNING id"
            )
            cursor = self.connection.cursor()
            try:
                cursor.execute(sql, tuple(params))
                result = cursor.fetchone()
                return result[0] if result else 0
            finally:
                cursor.close()

        return self._execute_with_retry(_run)

    def update(self, table: str, values: Dict[str, Any], **conditions) -> int:
        """Update records matching conditions."""
        if not values:
            raise ValueError("Cannot update with empty values")

        def _run():
            set_parts = [f"{col} = %s" for col in values]
            params = list(values.values())

            where_clause = ""
            if conditions:
                where_parts = [f"{col} = %s" for col in conditions]
                params += list(conditions.values())
                where_clause = " WHERE " + " AND ".join(where_parts)

            sql = f"UPDATE {table} SET {', '.join(set_parts)}{where_clause}"
            cursor = self.connection.cursor()
            try:
                cursor.execute(sql, tuple(params))
                return cursor.rowcount
            finally:
                cursor.close()

        return self._execute_with_retry(_run)

    def delete(self, table: str, **conditions) -> int:
        """Delete records matching conditions."""
        if not conditions:
            raise ValueError(
                "Delete requires at least one condition "
                "(use 'DELETE FROM table' directly if you really want to delete all rows)"
            )

        def _run():
            where_parts = [f"{col} = %s" for col in conditions]
            params = list(conditions.values())
            sql = f"DELETE FROM {table} WHERE {' AND '.join(where_parts)}"
            cursor = self.connection.cursor()
            try:
                cursor.execute(sql, tuple(params))
                return cursor.rowcount
            finally:
                cursor.close()

        return self._execute_with_retry(_run)
