from importlib.resources import files
from pathlib import Path
from threading import Lock, local
from typing import Any

import duckdb


class _ThreadLocalConnection:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = local()
        self._connections: list[duckdb.DuckDBPyConnection] = []
        self._connections_lock = Lock()

    def _current(self) -> duckdb.DuckDBPyConnection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = duckdb.connect(str(self.path))
            self._local.connection = connection
            with self._connections_lock:
                self._connections.append(connection)
        return connection

    def execute(self, *args: Any, **kwargs: Any) -> duckdb.DuckDBPyConnection:
        return self._current().execute(*args, **kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> duckdb.DuckDBPyConnection:
        return self._current().executemany(*args, **kwargs)

    def register(self, *args: Any, **kwargs: Any) -> duckdb.DuckDBPyConnection:
        return self._current().register(*args, **kwargs)

    def unregister(self, *args: Any, **kwargs: Any) -> duckdb.DuckDBPyConnection:
        return self._current().unregister(*args, **kwargs)

    def close(self) -> None:
        with self._connections_lock:
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            connection.close()


class Database:
    def __init__(self, path: Path) -> None:
        self.connection = _ThreadLocalConnection(path)

    def migrate(self) -> None:
        sql = files("astock.storage").joinpath("schema.sql").read_text(encoding="utf-8")
        self.connection.execute(sql)
        # Persist DDL now: DuckDB can fail to replay ALTER defaults after a forced stop.
        self.connection.execute("checkpoint")
