"""Complete, atomic Eastmoney sector snapshots (current membership, not history)."""
import json
import logging
import time
from datetime import date, datetime
from threading import Lock, Thread

import requests

from astock.live.calendar import SHANGHAI

SECTOR_KEYS = {"em_industry": "industry", "em_concept": "concept"}


class EastmoneySectors:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def fetch(self, scope):
        rows, seen = [], set()
        total = None
        for page in range(1, 201):
            response = self.session.get(
                "https://push2.eastmoney.com/webguest/api/qt/clist/get",
                params={"pn": page, "pz": 100, "np": 1, "po": 0, "fid": "f12",
                        "fs": scope, "fields": "f12,f14", "ut": "bd1d9ddb04089700cf9c27f6f7426281"},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data")
            if payload.get("rc") != 0 or not isinstance(data, dict):
                raise ValueError("东方财富未返回有效板块数据")
            count = data.get("total")
            if not isinstance(count, int) or count <= 0 or (total is not None and count != total):
                raise ValueError("东方财富列表为空或分页期间数量发生变化，请重试")
            total = count
            batch = data.get("diff")
            batch = list(batch.values()) if isinstance(batch, dict) else batch
            if not batch:
                raise ValueError("东方财富分页数据不完整")
            for row in batch:
                code, name = row.get("f12"), row.get("f14")
                if not code or not name:
                    raise ValueError("东方财富数据缺少代码或名称")
                if code in seen:
                    raise ValueError("东方财富返回重复分页，已取消更新")
                seen.add(code)
                rows.append({"code": str(code), "name": str(name)})
            if len(rows) == total:
                return rows
            if len(rows) > total:
                break
            time.sleep(.05)
        raise ValueError("东方财富分页数量不符")

    def snapshot(self, progress):
        sectors = []
        for kind, flag in (("industry", 2), ("concept", 3)):
            sectors.extend({**row, "kind": kind} for row in self.fetch(f"m:90 t:{flag} f:!50"))
        for index, sector in enumerate(sectors):
            progress(index, len(sectors), sector["name"])
            sector["members"] = [row["code"] for row in self.fetch(f"b:{sector['code']} f:!50")]
            time.sleep(.05)
        progress(len(sectors), len(sectors), "写入完整快照")
        return sectors


class SectorStore:
    def __init__(self, database):
        self.con = database.connection
        self.lock = Lock()
        self.running = False
        self.done = 0
        self.total = 0
        self.current = ""
        self.error = ""

    def replace(self, sectors, observed_on: date):
        if not sectors or any(not item.get("members") for item in sectors):
            raise ValueError("不能用空数据替换板块快照")
        self.con.execute("""insert into eastmoney_sector_snapshot(id, observed_on, sectors)
            values (1, ?, ?) on conflict(id) do update set
            observed_on=excluded.observed_on, sectors=excluded.sectors""",
                         [observed_on, json.dumps(sectors, ensure_ascii=False)])

    def snapshot(self):
        row = self.con.execute("select observed_on, sectors from eastmoney_sector_snapshot where id=1").fetchone()
        return (str(row[0]), json.loads(row[1])) if row else (None, [])

    def choices(self, key):
        _, sectors = self.snapshot()
        return [{"value": name, "label": name} for name in sorted({item["name"] for item in sectors if item["kind"] == SECTOR_KEYS[key]})]

    def values(self):
        stamp, sectors = self.snapshot()
        if stamp is None:
            return {}
        symbols = {row[0].split(".")[0]: row[0] for row in self.con.execute("select symbol from symbols where instrument_type='stock'").fetchall()}
        values = {symbol: {"em_industry": [], "em_concept": [], "sector_updated_at": stamp} for symbol in symbols.values()}
        for sector in sectors:
            key = "em_" + sector["kind"]
            for code in sector["members"]:
                if code in symbols:
                    values[symbols[code]][key].append(sector["name"])
        return values

    def status(self):
        stamp, sectors = self.snapshot()
        return {"source": "东方财富", "updated_at": stamp, "running": self.running,
                "done": self.done, "total": self.total, "current": self.current, "error": self.error,
                "industries": sum(item["kind"] == "industry" for item in sectors),
                "concepts": sum(item["kind"] == "concept" for item in sectors)}

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running, self.error, self.done, self.total = True, "", 0, 0
        def work():
            try:
                def progress(done, total, current):
                    self.done, self.total, self.current = done, total, current
                sectors = EastmoneySectors().snapshot(progress)
                self.replace(sectors, datetime.now(SHANGHAI).date())
            except Exception as error:
                logging.getLogger(__name__).exception("Eastmoney sector sync failed")
                self.error = f"同步失败，保留上次完整数据：{error}"
            finally:
                self.running = False
        Thread(target=work, daemon=True, name="eastmoney-sector-sync").start()
