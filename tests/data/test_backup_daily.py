from datetime import date

import pytest

from astock.data.backup_daily import EastmoneyDaily, ResilientDailySync
from astock.domain.market import Adjustment


def test_eastmoney_parses_units_and_excludes_records_after_target():
    payload = {
        "rc": 0,
        "data": {
            "code": "001309",
            "klines": [
                "2026-09-11,405.00,402.73,407.61,391.33,137822,5517779993.09,3.89,-3.70,-15.49,8.34",
                "2026-09-14,393,387.9,395.7,387.01,89047,3474449618.50,2.16,-3.68,-14.83,5.39",
            ],
        },
    }
    bars = EastmoneyDaily.parse(
        "001309.SZ", payload, date(2026, 9, 1), date(2026, 9, 11), Adjustment.QFQ
    )
    assert len(bars) == 1
    assert bars[0].volume_shares == 13782200
    assert bars[0].amount_cny == 5517779993.09
    assert bars[0].close == 402.73
    assert bars[0].is_final


def test_empty_or_wrong_symbol_is_not_success():
    for data in [None, {"code": "600000", "klines": []}, {"code": "001309", "klines": []}]:
        with pytest.raises(ValueError):
            EastmoneyDaily.parse(
                "001309.SZ",
                {"rc": 0, "data": data},
                date(2026, 9, 1),
                date(2026, 9, 11),
                Adjustment.QFQ,
            )


def test_primary_failure_runs_backup_but_success_does_not():
    class Primary:
        failed = True

        def start(self, end, years):
            if self.failed:
                raise RuntimeError("offline")
            return "primary"

    class Backup:
        def __init__(self):
            self.calls = []

        def start(self, end, years):
            self.calls.append(end)
            return "backup"

    primary, backup = Primary(), Backup()
    sync = ResilientDailySync(primary, backup)
    assert sync.start(date(2026, 9, 11)) == "backup"
    primary.failed = False
    assert sync.start(date(2026, 9, 11)) == "primary"
    assert backup.calls == [date(2026, 9, 11)]


def test_backup_persists_prices_prioritizes_watchlist_and_does_not_complete_stale_stock(tmp_path):
    from astock.data.backup_daily import BackupDailySync
    from astock.data.updates import MarketUpdates
    from astock.domain.market import Timeframe
    from astock.storage.bars import BarStore
    from astock.storage.database import Database
    from astock.storage.jobs import SyncJobRepository

    db = Database(tmp_path / "daily.duckdb")
    db.migrate()
    con = db.connection
    for symbol in ["600001.SH", "001309.SZ"]:
        con.execute("insert into symbols(symbol,name,exchange) values (?,?,'SH')", [symbol, symbol])
    con.execute("insert into watchlist(symbol,name) values ('001309.SZ','德明利')")

    class Provider:
        def history(self, symbol, start, end, adjustment=Adjustment.QFQ):
            day = "2026-09-10" if symbol == "600001.SH" else "2026-09-11"
            return EastmoneyDaily.parse(
                symbol,
                {
                    "rc": 0,
                    "data": {
                        "code": symbol.split(".")[0],
                        "klines": [f"{day},10,11,12,9,100,100000,0,0,0,0"],
                    },
                },
                start,
                end,
                adjustment,
            )

    class Builder:
        def __init__(self):
            self.calls = []

        def build_symbol(self, symbol, target, **kwargs):
            self.calls.append(symbol)

    bars = BarStore(tmp_path / "bars")
    jobs = SyncJobRepository(con)
    builder = Builder()
    backup = BackupDailySync(db, bars, jobs, builder, MarketUpdates(), Provider())
    result = backup.start(date(2026, 9, 11))
    assert result.status == "completed_with_errors"
    assert (result.succeeded, result.failed) == (1, 1)
    assert builder.calls[0] == "001309.SZ"
    assert bars.read("001309.SZ", Timeframe.DAY, Adjustment.QFQ)[-1].timestamp.date() == date(
        2026, 9, 11
    )
    assert jobs.latest_completed_end_date() is None
    repeated = backup.start(date(2026, 9, 11))
    assert repeated.job_id == result.job_id
    assert builder.calls.count("001309.SZ") == 1
    db.connection.close()


def test_tencent_units_for_main_board_and_star_and_missing_amount():
    from astock.data.backup_daily import TencentDaily

    for symbol, volume, expected in [
        ("000001.SZ", "832461", 83246100),
        ("688001.SH", "17323290", 17323290),
    ]:
        key = symbol.split(".")[1].lower() + symbol.split(".")[0]
        row = ["2026-09-11", "10", "11", "12", "9", volume, {}, "1", "1000", ""]
        payload = {"code": 0, "data": {key: {"qfqday": [row]}}}
        result = TencentDaily.parse(
            symbol, payload, date(2026, 9, 1), date(2026, 9, 11), Adjustment.QFQ
        )
        assert result[0].volume_shares == expected
        assert result[0].amount_cny == 10000000
        payload["data"][key]["qfqday"] = [row[:6]]
        with pytest.raises(ValueError, match="缺少成交额"):
            TencentDaily.parse(symbol, payload, date(2026, 9, 1), date(2026, 9, 11), Adjustment.QFQ)


def test_pending_backup_job_is_not_resumed_with_primary_universe():
    class Primary:
        def start(self, *args):
            return "wrong primary universe"

    class Backup:
        def pending(self, end):
            return True

        def start(self, end, years):
            return "resumed backup"

    assert ResilientDailySync(Primary(), Backup()).start(date(2026, 9, 14)) == "resumed backup"


def test_failed_secondary_does_not_replace_the_preferred_provider():
    import requests

    from astock.data.backup_daily import DailyHTTPProvider

    class Offline:
        def history(self, *args):
            raise requests.ConnectionError("offline")

    provider = DailyHTTPProvider()
    provider.source = "tencent-daily"
    provider.tencent = Offline()
    provider.eastmoney = Offline()
    with pytest.raises(requests.ConnectionError):
        provider.history("600000.SH", date(2026, 9, 1), date(2026, 9, 14))
    assert provider.source == "tencent-daily"


def test_backup_stops_before_disk_reserved_for_database(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import astock.data.backup_daily as backup_module
    from astock.data.backup_daily import BackupDailySync
    from astock.data.updates import MarketUpdates
    from astock.storage.bars import BarStore
    from astock.storage.database import Database
    from astock.storage.jobs import SyncJobRepository

    db = Database(tmp_path / "daily.duckdb")
    db.migrate()
    db.connection.execute(
        "insert into symbols(symbol,name,exchange) values ('600001.SH','股票','SH')"
    )

    class Provider:
        def history(self, symbol, start, end, adjustment=Adjustment.QFQ):
            return EastmoneyDaily.parse(
                symbol,
                {
                    "rc": 0,
                    "data": {
                        "code": symbol.split(".")[0],
                        "klines": ["2026-09-15,10,11,12,9,100,100000,0,0,0,0"],
                    },
                },
                start,
                end,
                adjustment,
            )

    class Builder:
        def build_symbol(self, *args, **kwargs):
            raise AssertionError("must stop before writing")

    monkeypatch.setattr(
        backup_module.shutil, "disk_usage", lambda path: SimpleNamespace(free=2 * 1024**3)
    )
    sync = BackupDailySync(
        db,
        BarStore(tmp_path / "bars"),
        SyncJobRepository(db.connection),
        Builder(),
        MarketUpdates(),
        Provider(),
    )
    with pytest.raises(RuntimeError, match="磁盘"):
        sync.start(date(2026, 9, 15))
    db.connection.close()


def test_tencent_requests_only_needed_calendar_window(monkeypatch):
    import astock.data.backup_daily as module
    from astock.data.backup_daily import TencentDaily
    requested=[]
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'code':0,'data':{'sz001309':{'qfqday':[
                ['2026-09-15','10','11','12','9','100',{},'1','10']
            ]}}}
    def get(url,params,timeout):
        requested.append(params['param'])
        return Response()
    monkeypatch.setattr(module.requests,'get',get)
    TencentDaily().history('001309.SZ',date(2026,8,11),date(2026,9,15))
    assert int(requested[0].split(',')[4]) == 36


def test_slow_unwatched_stock_does_not_block_ready_stock(tmp_path):
    from threading import Event

    from astock.data.backup_daily import BackupDailySync
    from astock.data.updates import MarketUpdates
    from astock.storage.bars import BarStore
    from astock.storage.database import Database
    from astock.storage.jobs import SyncJobRepository
    db = Database(tmp_path/'queue.duckdb')
    db.migrate()
    db.connection.execute("insert into symbols(symbol,name,exchange) values ('600001.SH','慢','SH'),('600002.SH','快','SH')")
    fast_written = Event()
    class Provider:
        def history(self,symbol,start,end,adjustment=Adjustment.QFQ):
            if symbol=='600001.SH' and not fast_written.wait(2):
                raise RuntimeError('ready stock was blocked behind a slow request')
            return EastmoneyDaily.parse(symbol,{'rc':0,'data':{'code':symbol.split('.')[0],
                'klines':['2026-09-15,10,11,12,9,100,100000,0,0,0,0']}},start,end,adjustment)
    class Builder:
        def build_symbol(self,symbol,*args,**kwargs):
            if symbol=='600002.SH':fast_written.set()
    sync=BackupDailySync(db,BarStore(tmp_path/'bars'),SyncJobRepository(db.connection),Builder(),MarketUpdates(),Provider())
    result=sync.start(date(2026,9,15))
    assert (result.succeeded,result.failed)==(2,0)
    db.connection.close()
