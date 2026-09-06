from datetime import date

import pytest

from astock.data.sectors import EastmoneySectors, SectorStore
from astock.storage.database import Database


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"rc": 0, "data": self.data}


class Session:
    def __init__(self, repeat=False):
        self.repeat = repeat

    def get(self, url, params, **kwargs):
        page = 1 if self.repeat else params["pn"]
        rows = [{"f12": f"BK{i:04d}", "f14": str(i)} for i in range((page-1)*100, min(page*100, 105))]
        return Response({"total":105,"diff":rows})


def test_sector_pagination_checks_completeness():
    assert len(EastmoneySectors(Session()).fetch("m:90 t:3")) == 105
    with pytest.raises(ValueError, match="重复"):
        EastmoneySectors(Session(True)).fetch("m:90 t:3")


def test_sector_snapshot_is_atomic_and_maps_existing_symbols(tmp_path):
    db=Database(tmp_path / "test.duckdb")
    db.migrate()
    db.connection.execute("insert into symbols(symbol,name,exchange,board) values ('001309.SZ','德明利','SZ','main')")
    store=SectorStore(db)
    store.replace([{"kind":"concept","code":"BK1","name":"存储芯片","members":["001309"]}],date(2026,9,6))
    assert store.values()["001309.SZ"]["em_concept"] == ["存储芯片"]
    assert store.choices("em_concept") == [{"value":"存储芯片","label":"存储芯片"}]
    with pytest.raises(ValueError):
        store.replace([],date(2026,9,7))
    assert store.status()["updated_at"] == "2026-09-06"
