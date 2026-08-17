import unittest
from unittest.mock import patch

import psycopg2

from app.db.postgres_db import PostgresDatabase


class _FakeConnection:
    def __init__(self, fail_rollback=False, fail_commit=False):
        self.fail_rollback = fail_rollback
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0
        self.cursor_factory = None

    def rollback(self):
        self.rollbacks += 1
        if self.fail_rollback:
            raise psycopg2.OperationalError("connection is dead")

    def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise psycopg2.OperationalError("broken pipe")

    def cursor(self, cursor_factory=None):
        self.cursor_factory = cursor_factory
        return self


class _FakePool:
    def __init__(self, connections):
        self._connections = list(connections)
        self.put_back = []
        self.closed_back = []

    def getconn(self):
        if not self._connections:
            raise psycopg2.pool.PoolError("connection pool exhausted")
        return self._connections.pop(0)

    def putconn(self, conn, key=None, close=False):
        if close:
            self.closed_back.append(conn)
        else:
            self.put_back.append(conn)

    def closeall(self):
        self.put_back.extend(self._connections)
        self._connections = []


class PostgresConnectionPoolTests(unittest.TestCase):
    def _database_with_pool(self, connections):
        database = PostgresDatabase(database_url="postgresql://unit:test@127.0.0.1:1/unit")
        database._pool = _FakePool(connections)
        return database

    def test_with_block_commits_and_returns_connection_once(self):
        conn = _FakeConnection()
        database = self._database_with_pool([conn])

        with database.get_connection() as proxy:
            proxy.cursor(cursor_factory=dict)

        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 1)  # checkout liveness probe
        self.assertEqual(database._pool.put_back, [conn])
        self.assertEqual(database._pool.closed_back, [])
        self.assertEqual(database._pool_slots._value, PostgresDatabase._POOL_MAX_CONN)

    def test_exception_inside_with_rolls_back_and_returns_connection(self):
        conn = _FakeConnection()
        database = self._database_with_pool([conn])

        with self.assertRaises(ValueError):
            with database.get_connection():
                raise ValueError("boom")

        self.assertEqual(conn.commits, 0)
        self.assertEqual(database._pool.put_back, [conn])

    def test_manual_close_returns_connection_to_pool(self):
        conn = _FakeConnection()
        database = self._database_with_pool([conn])

        proxy = database.get_connection()
        proxy.close()
        proxy.close()  # idempotent

        self.assertEqual(conn.commits, 1)
        self.assertEqual(database._pool.put_back, [conn])
        self.assertEqual(database._pool_slots._value, PostgresDatabase._POOL_MAX_CONN)

    def test_dead_connection_on_checkout_is_discarded_and_replaced(self):
        dead = _FakeConnection(fail_rollback=True)
        healthy = _FakeConnection()
        database = self._database_with_pool([dead, healthy])

        with database.get_connection() as proxy:
            proxy.commit()

        self.assertEqual(database._pool.closed_back, [dead])
        self.assertEqual(database._pool.put_back, [healthy])
        self.assertEqual(healthy.commits, 2)  # proxy.commit() + release commit

    def test_broken_connection_on_release_is_closed_not_pooled(self):
        conn = _FakeConnection(fail_commit=True)
        database = self._database_with_pool([conn])

        with database.get_connection():
            pass

        self.assertEqual(database._pool.put_back, [])
        self.assertEqual(database._pool.closed_back, [conn])
        self.assertEqual(database._pool_slots._value, PostgresDatabase._POOL_MAX_CONN)

    def test_getattr_delegates_to_underlying_connection(self):
        conn = _FakeConnection()
        database = self._database_with_pool([conn])

        with database.get_connection() as proxy:
            self.assertTrue(hasattr(proxy, "commits"))

        self.assertEqual(database._pool.put_back, [conn])

    def test_close_pool_releases_pool_reference(self):
        database = self._database_with_pool([_FakeConnection()])
        sentinel = database._pool

        with patch.object(sentinel, "closeall") as closeall:
            database.close_pool()
            closeall.assert_called_once()

        self.assertIsNone(database._pool)


if __name__ == "__main__":
    unittest.main()
