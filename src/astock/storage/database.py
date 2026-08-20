from importlib.resources import files
from pathlib import Path

import duckdb


class Database:
    def __init__(self, path: Path) -> None:
        self.connection = duckdb.connect(str(path))

    def migrate(self) -> None:
        sql = files("astock.storage").joinpath("schema.sql").read_text(encoding="utf-8")
        self.connection.execute(sql)
