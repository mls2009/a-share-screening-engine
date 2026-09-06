from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from astock.api.app import ApiContext, create_app, create_default_app
from astock.config import Settings
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.features.benchmark import BenchmarkService
from astock.features.store import MarketFeatureStore
from astock.features.zones import ZONE_RULE_VERSION, PriceZone, replace_auto_zones
from astock.screening.service import ScreeningService
from astock.storage.bars import BarStore
from astock.storage.database import Database


class FakeSync:
    def latest_completed_end_date(self) -> date:
        return date.max

    def start(self, end: date, years: int = 3):
        raise AssertionError("daily sync should be skipped in API tests")

    def status(self, job_id: UUID):
        return SimpleNamespace(
            job_id=job_id,
            status="running",
            total=5000,
            succeeded=100,
            failed=2,
        )


def _client(tmp_path: Path, benchmark_factory=None) -> tuple[TestClient, Database]:
    database = Database(tmp_path / "api.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "bars")
    database.connection.execute(
        """
        insert into symbols (symbol, name, exchange, board, is_listed)
        values ('600001.SH', '股票一', 'SH', 'main', true)
        """
    )
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close, return_20)
        values ('600001.SH', '1d', '2026-08-20', 'v1', 12, 35)
        """
    )
    bar_store.upsert(
        [
            Bar(
                symbol="600001.SH",
                timestamp=datetime(2026, 8, 20, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
                timeframe=Timeframe.DAY,
                open=10,
                high=12.5,
                low=9.8,
                close=12,
                volume_shares=1000,
                amount_cny=12000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
        ]
    )
    replace_auto_zones(
        database.connection,
        "600001.SH",
        Timeframe.DAY,
        date(2026, 8, 20),
        [
            PriceZone(
                as_of_date=date(2026, 8, 20),
                zone_kind="support",
                geometry="horizontal",
                lower_price=9.8,
                center_price=10,
                upper_price=10.2,
                slope=None,
                intercept=None,
                anchors=((date(2026, 8, 1), 10), (date(2026, 8, 10), 10.1)),
                strength=0.8,
                touches=2,
            )
        ],
        latest_bar_at=datetime(
            2026, 8, 20, 15, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        source_revision=bar_store.revision(
            "600001.SH", Timeframe.DAY, date(2026, 8, 20)
        ),
    )
    benchmark = (
        benchmark_factory(database, bar_store)
        if benchmark_factory is not None
        else BenchmarkService(database, bar_store)
    )
    context = ApiContext(
        database=database,
        bar_store=bar_store,
        screening=ScreeningService(database, MarketFeatureStore(database)),
        market_sync=FakeSync(),
        benchmark=benchmark,
    )
    return TestClient(create_app(context)), database


def test_app_keeps_daily_market_update_scheduler_running(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    scheduler = client.app.state.data_update_scheduler

    with client:
        assert scheduler.running is True

    assert scheduler.running is False


def _fifteen_minute_trend_source_bars() -> list[Bar]:
    bucket_ends = [
        (date(2026, 8, 19), time(9, 45)),
        (date(2026, 8, 19), time(10, 0)),
        (date(2026, 8, 19), time(10, 15)),
        (date(2026, 8, 19), time(10, 30)),
        (date(2026, 8, 19), time(13, 15)),
        (date(2026, 8, 19), time(13, 30)),
        (date(2026, 8, 19), time(13, 45)),
        (date(2026, 8, 19), time(14, 0)),
        (date(2026, 8, 20), time(9, 45)),
        (date(2026, 8, 20), time(10, 0)),
        (date(2026, 8, 20), time(10, 15)),
        (date(2026, 8, 20), time(10, 30)),
        (date(2026, 8, 20), time(13, 15)),
        (date(2026, 8, 20), time(13, 30)),
    ]
    lows = {1: 8.0, 4: 9.0, 7: 10.0, 10: 11.0}
    highs = {2: 16.0, 5: 15.0, 8: 14.0, 11: 13.0}
    bars = []
    for index, (trade_date, bucket_end) in enumerate(bucket_ends):
        end = datetime.combine(trade_date, bucket_end, tzinfo=ZoneInfo("Asia/Shanghai"))
        for minutes_before in (10, 5, 0):
            bars.append(
                Bar(
                    symbol="600001.SH",
                    timestamp=end - timedelta(minutes=minutes_before),
                    timeframe=Timeframe.MIN_5,
                    open=12,
                    high=highs.get(index, 12.4),
                    low=lows.get(index, 11.6),
                    close=12,
                    volume_shares=100,
                    amount_cny=1_000,
                    adjustment=Adjustment.QFQ,
                    source="test",
                )
            )
    return bars


CONDITION = {
    "kind": "condition",
    "metric": "return_20",
    "timeframe": "1d",
    "operator": "gte",
    "right": {"kind": "constant", "value": 30, "unit": "percent"},
}


def test_catalog_validate_and_run_screen_endpoints(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    catalog = client.get("/api/catalog")
    validation = client.post("/api/screens/validate", json=CONDITION)
    run = client.post(
        "/api/screens/run",
        json={"tree": CONDITION, "mode": "close", "as_of": "2026-08-20"},
    )

    assert catalog.status_code == 200
    assert any(metric["key"] == "return_20" for metric in catalog.json())
    assert validation.json() == {"valid": True, "errors": []}
    assert run.status_code == 200
    assert run.json()["matches"][0]["symbol"] == "600001.SH"


def test_screen_templates_can_be_saved_replaced_listed_and_deleted(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    created = client.post(
        "/api/screens/templates",
        json={"name": "月线强势", "tree": CONDITION},
    )
    replaced_tree = {**CONDITION, "right": {"kind": "constant", "value": 40, "unit": "percent"}}
    replaced = client.post(
        "/api/screens/templates",
        json={"name": "月线强势", "tree": replaced_tree},
    )
    templates = client.get("/api/screens/templates")

    assert created.status_code == 201
    assert replaced.status_code == 201
    assert replaced.json()["template_id"] == created.json()["template_id"]
    assert replaced.json()["version"] == 2
    assert templates.json()[0]["name"] == "月线强势"
    assert templates.json()[0]["tree"]["right"]["value"] == 40

    deleted = client.delete(f"/api/screens/templates/{created.json()['template_id']}")
    assert deleted.status_code == 204
    assert client.get("/api/screens/templates").json() == []


def test_screen_template_rejects_unknown_metric(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    invalid = {**CONDITION, "metric": "not_a_metric"}

    response = client.post(
        "/api/screens/templates",
        json={"name": "错误模板", "tree": invalid},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "unknown_metric"


def test_watchlist_preserves_screen_source_and_deduplicates(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    run = client.post("/api/screens/run", json={"tree": CONDITION, "mode": "close", "as_of": "2026-08-20"}).json()
    payload = {"symbol": "600001.SH", "run_id": run["run_id"]}
    assert client.post("/api/watchlist", json=payload).status_code == 200
    assert client.post("/api/watchlist", json=payload).status_code == 200
    items = client.get("/api/watchlist").json()
    assert len(items) == 1
    assert len(items[0]["sources"]) == 1
    assert items[0]["sources"][0]["tree"]["metric"] == CONDITION["metric"]
    invalid = client.post("/api/watchlist", json={"symbol": "missing"})
    assert invalid.status_code == 404
    assert client.delete("/api/watchlist/600001.SH").status_code == 204
    assert client.get("/api/watchlist").json() == []


def test_workbench_details_comparison_scope_and_export(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    run = client.post("/api/screens/run", json={"tree": CONDITION, "as_of": "2026-08-20"}).json()
    run_id = run["run_id"]
    assert run["matches"][0]["features"]["metric_values"]["1d:return_20"] == 35
    detail = client.get(f"/api/workbench/runs/{run_id}/detail/600001.SH").json()
    assert detail["source"]["explanation"]["result"] == "true"
    assert detail["recent"][0]["date"] == "2026-08-20"
    assert detail["recent"][0]["evaluation"]["result"] == "true"
    export = client.get(f"/api/workbench/runs/{run_id}/export?columns=1d:return_20")
    assert "600001.SH" in export.text and "35" in export.text
    assert "text/csv" in export.headers["content-type"]
    batch = client.post(f"/api/workbench/runs/{run_id}/watchlist", json={"all_matches": True})
    assert batch.json() == {"added": 1}
    selected = client.post("/api/screens/run", json={"tree": CONDITION, "as_of": "2026-08-20", "scope": "watchlist"}).json()
    assert selected["universe_size"] == 1
    assert client.post("/api/screens/run", json={"tree": CONDITION, "as_of": "2026-08-20", "scope": "run"}).status_code == 422
    stricter = {**CONDITION, "right": {"kind": "constant", "value": 40, "unit": "percent"}}
    empty = client.post("/api/screens/run", json={"tree": stricter, "as_of": "2026-08-20", "scope": "run", "source_run_id": run_id}).json()
    assert empty["match_count"] == 0
    diff = client.get(f"/api/workbench/runs/{empty['run_id']}/compare/{run_id}").json()
    assert diff["same_definition"] is False
    assert diff["same_scope"] is False
    assert diff["exited"][0]["symbol"] == "600001.SH"
    assert len(client.get("/api/workbench/runs").json()) == 3


def test_workbench_support_condition_uses_same_values_as_screen(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    zone = client.post("/api/symbols/600001.SH/zones/manual", json={
        "timeframe": "1d", "as_of_date": "2026-08-20", "zone_kind": "support",
        "geometry": "horizontal", "lower_price": 11, "center_price": 11,
        "upper_price": 11, "anchors": [["2026-08-20", 11]],
    })
    assert zone.status_code == 201
    tree = {**CONDITION, "metric": "support_distance", "operator": "lte", "right": {"kind": "constant", "value": 10, "unit": "percent"}}
    run = client.post("/api/screens/run", json={"tree": tree, "as_of": "2026-08-20"}).json()
    assert run["match_count"] == 1
    detail = client.get(f"/api/workbench/runs/{run['run_id']}/detail/600001.SH").json()
    assert detail["recent"][-1]["evaluation"]["result"] == "true"


def test_extra_result_columns_include_enriched_metrics(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    database.connection.execute("insert into security_status(symbol,trade_date,board,is_st,is_suspended) values ('600001.SH','2026-08-20','main',true,false)")
    run = client.post("/api/screens/run", json={"tree": CONDITION, "as_of": "2026-08-20", "extra_columns": ["1d:is_st"]}).json()
    assert run["matches"][0]["features"]["metric_values"].get("1d:is_st") is True


def test_eastmoney_sector_filter_labels_and_current_membership_warning(tmp_path: Path) -> None:
    from astock.data.sectors import SectorStore
    client, database = _client(tmp_path)
    store = SectorStore(database)
    store.replace([{"kind":"concept","code":"BK1","name":"存储芯片","members":["600001"]},
                   {"kind":"industry","code":"BK2","name":"半导体","members":["600001"]}], date(2026,9,6))
    catalog = client.get("/api/catalog").json()
    assert next(item for item in catalog if item["key"] == "em_concept")["choices"][0]["value"] == "存储芯片"
    tree = {**CONDITION,"metric":"em_concept","operator":"in","right":{"kind":"constant","value":["存储芯片"],"unit":"category"}}
    run = client.post("/api/screens/run", json={"tree":tree,"as_of":"2026-08-20"}).json()
    assert run["match_count"] == 1
    assert run["matches"][0]["features"]["em_industry"] == ["半导体"]
    assert any("当前成分" in warning for warning in run["diagnostics"]["warnings"])
    assert client.get("/api/sectors/status").json()["concepts"] == 1
    detail = client.get(f"/api/workbench/runs/{run['run_id']}/detail/600001.SH").json()
    assert detail["recent"][-1]["evaluation"]["result"] == "unknown"
    latest = client.get(f"/api/workbench/runs/{run['run_id']}/detail/600001.SH?latest=true").json()
    assert latest["source"]["explanation"]["result"] == "true"


def test_live_detail_marks_keep_the_entry_snapshot_date(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    run = client.post("/api/screens/run", json={"tree": CONDITION, "as_of": "2026-08-20"}).json()
    database.connection.execute("update screen_runs set mode='live',as_of_date='2026-08-21' where run_id=?", [run["run_id"]])
    detail = client.get(f"/api/workbench/runs/{run['run_id']}/detail/600001.SH").json()
    assert detail["source"]["marks"][0]["date"] == "2026-08-21"
    assert detail["recent"][-1]["date"] == "2026-08-20"


def test_dynamic_column_sort_happens_before_paging(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    database.connection.execute("insert into symbols(symbol,name,exchange,board,is_listed) values ('600002.SH','股票二','SH','main',true)")
    database.connection.execute("insert into market_features(symbol,timeframe,feature_date,feature_version,return_20) values ('600002.SH','1d','2026-08-20','v1',60)")
    run = client.post("/api/screens/run", json={"tree": CONDITION, "as_of": "2026-08-20", "limit": 1}).json()
    page = client.get(f"/api/screens/runs/{run['run_id']}?limit=1&sort_by=1d:return_20&sort_direction=desc").json()
    assert page["matches"][0]["symbol"] == "600002.SH"
    second = client.get(f"/api/screens/runs/{run['run_id']}?limit=1&offset=1&sort_by=1d:return_20&sort_direction=desc").json()
    assert second["matches"][0]["symbol"] == "600001.SH"


def test_screen_schedule_runs_only_after_close_and_once(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    template = client.post("/api/screens/templates", json={"name": "每日筛选", "tree": CONDITION}).json()
    identifier = template["template_id"]
    assert client.put(f"/api/workbench/schedules/{identifier}", json={"enabled": True, "notify": True}).status_code == 422
    assert client.put(f"/api/workbench/schedules/{identifier}", json={"enabled": True}).status_code == 200
    runner = client.app.state.screen_scheduler
    assert runner.run_due(datetime(2026, 8, 20, 15, tzinfo=ZoneInfo("Asia/Shanghai"))) == 0
    assert runner.run_due(datetime(2026, 8, 20, 17, tzinfo=ZoneInfo("Asia/Shanghai"))) == 1
    assert runner.run_due(datetime(2026, 8, 20, 18, tzinfo=ZoneInfo("Asia/Shanghai"))) == 0
    assert client.get("/api/workbench/schedules").json()[0]["last_date"] == "2026-08-20"


def test_symbol_search_matches_etf_code_and_chinese_name(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    database.connection.executemany(
        """
        insert into symbols
          (symbol, name, exchange, board, instrument_type, is_listed)
        values (?, ?, ?, 'main', ?, ?)
        """,
        [
            ["159558.SZ", "创业板中盘ETF", "SZ", "etf", True],
            ["159559.SZ", "创业板精选ETF", "SZ", "etf", True],
            ["159557.SZ", "已退市ETF", "SZ", "etf", False],
        ],
    )

    by_code = client.get("/api/symbols/search", params={"q": "159558"})
    by_full_code = client.get(
        "/api/symbols/search", params={"q": "159558.sz"}
    )
    by_name = client.get(
        "/api/symbols/search", params={"q": "创业板", "limit": 1}
    )

    expected = {
        "symbol": "159558.SZ",
        "name": "创业板中盘ETF",
        "exchange": "SZ",
        "instrument_type": "etf",
    }
    assert by_code.status_code == 200
    assert by_code.json()[0] == expected
    assert by_full_code.json() == [expected]
    assert by_name.status_code == 200
    assert len(by_name.json()) == 1
    assert by_name.json()[0] == expected
    assert all(item["symbol"] != "159557.SZ" for item in by_code.json())


def test_symbol_search_treats_wildcards_literally_and_blank_as_empty(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)

    assert client.get("/api/symbols/search", params={"q": " "}).json() == []
    assert client.get("/api/symbols/search", params={"q": "%"}).json() == []


def test_benchmark_comparison_endpoint_normalizes_common_dates(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    store = client.app.state.context.bar_store
    store.upsert([
        Bar(
            symbol="600001.SH",
            timestamp=datetime(2026, 8, 19, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
            timeframe=Timeframe.DAY,
            open=10,
            high=10,
            low=10,
            close=10,
            volume_shares=1_000,
            amount_cny=10_000,
            adjustment=Adjustment.QFQ,
            source="test",
        ),
        Bar(
            symbol="000001.SH",
            timestamp=datetime(2026, 8, 19, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
            timeframe=Timeframe.DAY,
            open=3_000,
            high=3_000,
            low=3_000,
            close=3_000,
            volume_shares=1_000,
            amount_cny=3_000_000,
            adjustment=Adjustment.NONE,
            source="test",
        ),
        Bar(
            symbol="000001.SH",
            timestamp=datetime(2026, 8, 20, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
            timeframe=Timeframe.DAY,
            open=3_150,
            high=3_150,
            low=3_150,
            close=3_150,
            volume_shares=1_000,
            amount_cny=3_150_000,
            adjustment=Adjustment.NONE,
            source="test",
        ),
    ])

    response = client.get(
        "/api/symbols/600001.SH/benchmark-comparison",
        params={"timeframe": "1d", "start": "2026-08-19", "end": "2026-08-20"},
    )

    assert response.status_code == 200
    assert response.json()["benchmark_symbol"] == "000001.SH"
    assert response.json()["benchmark_name"] == "上证指数"
    assert response.json()["points"][0]["stock_return_pct"] == 0


class FakeBenchmarkApi:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def sync(self, *args):
        self.calls.append(args)
        return {"stock_bars": 12, "benchmark_bars": 12}


def test_chart_data_sync_endpoint_passes_exact_scope(tmp_path: Path) -> None:
    fake = FakeBenchmarkApi()
    client, _ = _client(tmp_path, lambda _database, _store: fake)

    response = client.post(
        "/api/symbols/600001.SH/chart-data/sync",
        json={
            "timeframe": "15m",
            "start": "2026-08-20",
            "end": "2026-08-20",
            "include_benchmark": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"stock_bars": 12, "benchmark_bars": 12}
    assert fake.calls == [
        (
            "600001.SH",
            Timeframe.MIN_15,
            date(2026, 8, 20),
            date(2026, 8, 20),
            True,
        )
    ]


def test_benchmark_endpoint_returns_structured_missing_data_error(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.get(
        "/api/symbols/600001.SH/benchmark-comparison",
        params={"timeframe": "1d", "start": "2026-08-20", "end": "2026-08-20"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "benchmark_data_missing",
        "message": "对应大盘数据尚未同步",
    }


def test_chart_indicators_use_history_before_visible_window(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    bar_store = BarStore(tmp_path / "bars")
    history = [
        Bar(
            symbol="600001.SH",
            timestamp=datetime(2026, 7, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")) + timedelta(days=day - 1),
            timeframe=Timeframe.DAY,
            open=day,
            high=day + 1,
            low=day - 1,
            close=day,
            volume_shares=day * 100,
            amount_cny=day * 1_000,
            adjustment=Adjustment.QFQ,
            source="test",
        )
        for day in range(1, 36)
    ]
    bar_store.upsert(history)

    response = client.get(
        "/api/symbols/600001.SH/indicators",
        params={"timeframe": "1d", "start": "2026-08-04", "end": "2026-08-04"},
    )

    assert response.status_code == 200
    result = response.json()[0]
    assert result["timestamp"] == "2026-08-04T15:00:00+08:00"
    assert result["ma_5"] == 33.0
    assert result["ma_10"] == 30.5
    assert result["ma_20"] == 25.5
    assert result["ma_30"] == 20.5
    assert result["boll_middle"] == 25.5
    assert result["rsi_14"] == 100.0
    assert result["volume_ma_20"] == 2550.0
    assert result["atr_14"] == 2.0


def test_screen_run_and_saved_results_report_total_matches_with_pagination(
    tmp_path: Path,
) -> None:
    client, database = _client(tmp_path)
    database.connection.executemany(
        """
        insert into symbols (symbol, name, exchange, board, is_listed)
        values (?, ?, 'SH', 'main', true)
        """,
        [["600002.SH", "股票二"], ["600003.SH", "股票三"]],
    )
    database.connection.executemany(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close, return_20)
        values (?, '1d', '2026-08-20', 'v1', 12, ?)
        """,
        [["600002.SH", 40], ["600003.SH", 45]],
    )

    first = client.post(
        "/api/screens/run",
        json={
            "tree": CONDITION,
            "mode": "close",
            "as_of": "2026-08-20",
            "limit": 2,
            "offset": 0,
        },
    )
    run_id = first.json()["run_id"]
    last = client.get(
        f"/api/screens/runs/{run_id}", params={"limit": 1, "offset": 2}
    )

    assert first.status_code == 200
    assert first.json()["match_count"] == 3
    assert len(first.json()["matches"]) == 2
    assert last.status_code == 200
    assert last.json()["match_count"] == 3
    assert [match["rank"] for match in last.json()["matches"]] == [3]


def test_saved_results_sort_all_matches_before_paginating(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    database.connection.executemany(
        """
        insert into symbols (symbol, name, exchange, board, is_listed)
        values (?, ?, 'SH', 'main', true)
        """,
        [["600002.SH", "股票二"], ["600003.SH", "股票三"]],
    )
    database.connection.executemany(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close, return_20)
        values (?, '1d', '2026-08-20', 'v1', 12, ?)
        """,
        [["600002.SH", 40], ["600003.SH", 45]],
    )
    run = client.post(
        "/api/screens/run",
        json={"tree": CONDITION, "mode": "close", "as_of": "2026-08-20"},
    )
    run_id = run.json()["run_id"]

    first_page = client.get(
        f"/api/screens/runs/{run_id}",
        params={"limit": 2, "offset": 0, "sort_by": "return_20", "sort_direction": "desc"},
    )
    second_page = client.get(
        f"/api/screens/runs/{run_id}",
        params={"limit": 2, "offset": 2, "sort_by": "return_20", "sort_direction": "desc"},
    )

    assert [match["symbol"] for match in first_page.json()["matches"]] == ["600003.SH", "600002.SH"]
    assert [match["symbol"] for match in second_page.json()["matches"]] == ["600001.SH"]


def test_catalog_exposes_hierarchical_filter_metadata(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    catalog = {
        metric["key"]: metric for metric in client.get("/api/catalog").json()
    }

    assert catalog["return_20"]["group"] == "price"
    assert catalog["return_20"]["family"] == "price_change"
    assert catalog["return_20"]["period"] == 20
    assert catalog["return_20"]["directions"] == [
        {"value": "rise", "label": "上涨幅度"},
        {"value": "fall", "label": "下跌幅度"},
    ]
    assert catalog["board"]["multiple"] is True
    assert {"eq", "ne", "in", "not_in"}.issubset(catalog["board"]["operators"])
    assert catalog["board"]["choices"] == [
        {"value": "main", "label": "主板"},
        {"value": "chinext", "label": "创业板"},
        {"value": "star", "label": "科创板"},
        {"value": "beijing", "label": "北交所"},
    ]
    assert catalog["pattern_type"]["multiple"] is True
    assert {"eq", "ne", "in", "not_in"}.issubset(
        catalog["pattern_type"]["operators"]
    )
    assert {choice["value"] for choice in catalog["pattern_type"]["choices"]} >= {
        "morning_star",
        "hammer",
        "bullish_engulfing",
    }
    assert catalog["listing_stage"]["choices"] == [
        {"value": "new", "label": "新股"},
        {"value": "secondary_new", "label": "次新股"},
        {"value": "established", "label": "老股"},
    ]
    assert catalog["is_new"]["visible"] is False
    assert catalog["is_secondary_new"]["visible"] is False


def test_bars_zones_run_results_and_sync_status_contracts(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    run = client.post(
        "/api/screens/run",
        json={"tree": CONDITION, "mode": "close", "as_of": "2026-08-20"},
    ).json()
    run_id = run["run_id"]
    job_id = "00000000-0000-0000-0000-000000000009"

    bars = client.get(
        "/api/symbols/600001.SH/bars",
        params={"timeframe": "1d", "start": "2026-08-01", "end": "2026-08-20"},
    )
    zones = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "1d", "as_of": "2026-08-20"},
    )
    results = client.get(f"/api/screens/runs/{run_id}")
    sync = client.get(f"/api/sync/jobs/{job_id}")

    assert bars.json()[0]["close"] == 12
    assert zones.json()[0]["zone_kind"] == "support"
    assert zones.json()[0]["source"] == "auto"
    assert results.json()["matches"][0]["symbol"] == "600001.SH"
    assert sync.json()["succeeded"] == 100


def test_zones_api_hides_legacy_auto_trends_and_keeps_horizontal_limit(
    tmp_path: Path,
) -> None:
    client, database = _client(tmp_path)
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, slope, intercept, strength,
           touches, last_touched_on, source, rule_version)
        values (?, '600001.SH', '1d', '2026-08-20', ?, 'trend', ?, ?, ?, ?, ?,
                0.8, 3, '2026-08-20', 'auto', ?)
        """,
        [
            [
                "00000000-0000-0000-0000-000000000201",
                "uptrend",
                12.9,
                13.0,
                13.1,
                0.1,
                10.0,
                ZONE_RULE_VERSION,
            ],
            [
                "00000000-0000-0000-0000-000000000202",
                "downtrend",
                10.9,
                11.0,
                11.1,
                -0.1,
                14.0,
                ZONE_RULE_VERSION,
            ],
        ],
    )

    response = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "1d", "as_of": "2026-08-20", "limit_each": 1},
    )

    assert response.status_code == 200
    assert {row["zone_kind"] for row in response.json()} == {"support"}
    assert all(row["geometry"] == "horizontal" for row in response.json())


def test_zones_api_uses_latest_non_null_close(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    database.connection.execute(
        """
        insert into market_features
          (symbol, timeframe, feature_date, feature_version, close)
        values ('600001.SH', '1d', '2026-08-21', 'v1', null)
        """
    )

    response = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "1d", "as_of": "2026-08-21", "limit_each": 1},
    )

    assert response.status_code == 200
    assert [(row["zone_kind"], row["center_price"]) for row in response.json()] == [
        ("support", 10.0)
    ]


def test_zones_api_builds_and_reuses_requested_minute_timeframe(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    client.app.state.context.bar_store.upsert(_fifteen_minute_trend_source_bars())

    first = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "15m", "as_of": "2026-08-20", "limit_each": 1},
    )
    first_rows = database.connection.execute(
        """
        select zone_id, created_at from support_resistance_zones
        where symbol = '600001.SH' and timeframe = '15m' and source = 'auto'
        order by zone_id
        """
    ).fetchall()
    second = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "15m", "as_of": "2026-08-20", "limit_each": 1},
    )
    second_rows = database.connection.execute(
        """
        select zone_id, created_at from support_resistance_zones
        where symbol = '600001.SH' and timeframe = '15m' and source = 'auto'
        order by zone_id
        """
    ).fetchall()

    assert first.status_code == 200
    assert second.status_code == 200
    assert database.connection.execute(
        """
        select count(*) from market_features
        where symbol = '600001.SH' and timeframe = '15m' and close is not null
        """
    ).fetchone() == (0,)
    assert first.json()
    assert all(
        row["source"] == "auto" and row["geometry"] == "horizontal"
        for row in first.json()
    )
    assert first_rows
    assert second_rows == first_rows

    client.app.state.context.bar_store.upsert(
        [
            Bar(
                symbol="600001.SH",
                timestamp=datetime(
                    2026, 8, 21, 9, minute, tzinfo=ZoneInfo("Asia/Shanghai")
                ),
                timeframe=Timeframe.MIN_5,
                open=12,
                high=12.4,
                low=11.6,
                close=12,
                volume_shares=100,
                amount_cny=1_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
            for minute in (35, 40, 45)
        ]
    )
    refreshed = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "15m", "as_of": "2026-08-21", "limit_each": 1},
    )

    assert refreshed.status_code == 200
    assert database.connection.execute(
        """
        select max(as_of_date) from support_resistance_zones
        where symbol = '600001.SH' and timeframe = '15m' and source = 'auto'
        """
    ).fetchone() == (date(2026, 8, 21),)
    assert refreshed.json()
    assert all(
        row["source"] == "auto" and row["geometry"] == "horizontal"
        for row in refreshed.json()
    )


def test_minute_chart_uses_bar_close_and_does_not_rebuild_deleted_latest_batch(
    tmp_path: Path,
) -> None:
    client, database = _client(tmp_path)
    client.app.state.context.bar_store.upsert(
        [
            Bar(
                symbol="600001.SH",
                timestamp=datetime(
                    2026, 8, 20, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai")
                ),
                timeframe=Timeframe.MIN_5,
                open=12,
                high=12.4,
                low=11.6,
                close=12,
                volume_shares=100,
                amount_cny=1_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
        ]
    )
    previous_zone = PriceZone(
        as_of_date=date(2026, 8, 19),
        zone_kind="support",
        geometry="horizontal",
        lower_price=7.8,
        center_price=8,
        upper_price=8.2,
        slope=None,
        intercept=None,
        anchors=((date(2026, 8, 19), 8),),
        strength=0.8,
        touches=1,
    )
    replace_auto_zones(
        database.connection,
        "600001.SH",
        Timeframe.MIN_5,
        date(2026, 8, 19),
        [previous_zone],
    )
    replace_auto_zones(
        database.connection,
        "600001.SH",
        Timeframe.MIN_5,
        date(2026, 8, 20),
        [
            PriceZone(
                as_of_date=date(2026, 8, 20),
                zone_kind="support",
                geometry="horizontal",
                lower_price=9.8,
                center_price=10,
                upper_price=10.2,
                slope=None,
                intercept=None,
                anchors=((date(2026, 8, 20), 10),),
                strength=0.8,
                touches=1,
            )
        ],
        latest_bar_at=datetime(
            2026, 8, 20, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        source_revision=client.app.state.context.bar_store.revision(
            "600001.SH", Timeframe.MIN_5, date(2026, 8, 20)
        ),
    )
    zone_id = database.connection.execute(
        """
        select zone_id from support_resistance_zones
        where symbol = '600001.SH' and timeframe = '5m' and source = 'auto'
          and as_of_date = '2026-08-20'
        """
    ).fetchone()[0]

    visible = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "5m", "as_of": "2026-08-20"},
    )
    deleted = client.delete(f"/api/symbols/600001.SH/zones/{zone_id}")
    after_delete = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "5m", "as_of": "2026-08-20"},
    )

    assert visible.status_code == 200
    assert [(row["zone_kind"], row["center_price"]) for row in visible.json()] == [
        ("support", 10.0)
    ]
    assert deleted.status_code == 204
    assert after_delete.json() == []
    assert database.connection.execute(
        "select state from support_resistance_zones where zone_id = ?", [zone_id]
    ).fetchone() == ("deleted",)


def test_minute_chart_without_bars_still_returns_active_manual_zone(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    payload = {
        "timeframe": "30m",
        "as_of_date": "2026-08-20",
        "zone_kind": "support",
        "geometry": "horizontal",
        "lower_price": 9.8,
        "center_price": 10.0,
        "upper_price": 10.2,
        "anchors": [["2026-08-20", 10.0]],
    }
    created = client.post("/api/symbols/600001.SH/zones/manual", json=payload)

    response = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "30m", "as_of": "2026-08-20"},
    )

    assert created.status_code == 201
    assert [row["zone_id"] for row in response.json()] == [created.json()["zone_id"]]


def test_validation_errors_have_stable_code_message_and_path(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    invalid = {**CONDITION, "metric": "not_a_metric"}

    response = client.post("/api/screens/validate", json=invalid)

    assert response.json() == {
        "valid": False,
        "errors": [
            {
                "code": "unknown_metric",
                "message": "unknown metric: not_a_metric",
                "path": "root",
            }
        ],
    }


def test_default_app_factory_is_runnable_with_configured_data_directory(tmp_path: Path) -> None:
    app = create_default_app(Settings(data_dir=tmp_path / "runtime-data"))

    response = TestClient(app).get("/api/catalog")

    assert response.status_code == 200


def test_bars_api_supports_five_fifteen_thirty_sixty_day_week_and_month(
    tmp_path: Path,
) -> None:
    client, database = _client(tmp_path)
    bars_root = tmp_path / "bars"
    store = BarStore(bars_root)
    store.upsert(
        [
            Bar(
                symbol="600001.SH",
                timestamp=datetime(2026, 8, 20, 9, minute, tzinfo=ZoneInfo("Asia/Shanghai")),
                timeframe=Timeframe.MIN_5,
                open=10,
                high=11,
                low=9,
                close=10.5,
                volume_shares=100,
                amount_cny=1_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
            for minute in (35, 40, 45)
        ]
    )

    for timeframe in ("5m", "15m", "30m", "60m", "1d", "1w", "1mo"):
        response = client.get(
            "/api/symbols/600001.SH/bars",
            params={
                "timeframe": timeframe,
                "start": "2026-08-01",
                "end": "2026-08-20",
            },
        )
        assert response.status_code == 200
        assert response.json(), timeframe
    database.connection.close()


def test_manual_zone_create_and_delete_api(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    payload = {
        "timeframe": "1d",
        "as_of_date": "2026-08-20",
        "zone_kind": "resistance",
        "geometry": "trend",
        "lower_price": 14.8,
        "center_price": 15.0,
        "upper_price": 15.2,
        "slope": -0.02,
        "intercept": 15.4,
        "anchors": [["2026-08-01", 15.4], ["2026-08-20", 15.0]],
    }

    created = client.post("/api/symbols/600001.SH/zones/manual", json=payload)
    assert created.status_code == 201
    assert created.json()["source"] == "manual"
    assert created.json()["reappeared"] is False
    zone_id = created.json()["zone_id"]

    zones = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "1d", "as_of": "2026-08-20", "limit_each": 20},
    ).json()
    assert any(row["zone_id"] == zone_id for row in zones)

    deleted = client.delete(f"/api/symbols/600001.SH/zones/{zone_id}")
    missing = client.delete(f"/api/symbols/600001.SH/zones/{zone_id}")
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_automatic_zone_can_be_deleted_only_by_its_symbol(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    zone_id = database.connection.execute(
        "select zone_id from support_resistance_zones where source = 'auto'"
    ).fetchone()[0]

    wrong_symbol = client.delete(f"/api/symbols/000001.SZ/zones/{zone_id}")
    deleted = client.delete(f"/api/symbols/600001.SH/zones/{zone_id}")

    assert wrong_symbol.status_code == 404
    assert deleted.status_code == 204
    assert database.connection.execute(
        "select count(*) from zone_deletion_markers where symbol = '600001.SH'"
    ).fetchone() == (1,)


def test_api_serves_built_frontend_and_spa_routes(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    frontend = tmp_path / "dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html><body>ASTOCK WORKBENCH</body></html>")
    (frontend / "assets" / "app.js").write_text("console.log('astock')")
    context = client.app.state.context
    spa = TestClient(create_app(context, frontend_dir=frontend))

    assert "ASTOCK WORKBENCH" in spa.get("/").text
    assert "ASTOCK WORKBENCH" in spa.get("/chart/600001.SH").text
    assert "console.log" in spa.get("/assets/app.js").text
    database.connection.close()


def test_backtest_run_and_result_endpoints(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    payload = {
        "symbols": ["600001.SH"],
        "timeframe": "1d",
        "start": "2026-08-01",
        "end": "2026-08-20",
        "entry_tree": CONDITION,
        "exit_tree": CONDITION,
        "initial_cash": 100000,
        "position_size": 1,
        "mode": "simple",
        "adjustment": "qfq",
    }

    created = client.post("/api/backtests/run", json=payload)

    assert created.status_code == 200
    run_id = created.json()["run_id"]
    stored = client.get(f"/api/backtests/{run_id}")
    assert stored.status_code == 200
    assert stored.json()["result"]["request"]["symbols"] == ["600001.SH"]


def test_backtest_endpoint_reports_missing_local_history(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    payload = {
        "symbols": ["000001.SZ"],
        "timeframe": "1d",
        "start": "2026-08-01",
        "end": "2026-08-20",
        "entry_tree": CONDITION,
        "exit_tree": CONDITION,
        "initial_cash": 100000,
    }

    response = client.post("/api/backtests/run", json=payload)

    assert response.status_code == 422
    assert response.json()["symbols"] == ["000001.SZ"]


def test_monitor_task_crud_and_scheduler_status_endpoints(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    payload = {
        "name": "茅台突破 1500",
        "symbols": ["600519.SH"],
        "comparator": "cross_above",
        "threshold": 1500,
        "cooldown_seconds": 300,
        "scope": "watchlist",
        "enabled": True,
    }

    created = client.post("/api/monitor/tasks", json=payload)

    assert created.status_code == 201
    task_id = created.json()["task_id"]
    assert client.get("/api/monitor/tasks").json()[0]["name"] == "茅台突破 1500"
    disabled = client.patch(f"/api/monitor/tasks/{task_id}", json={"enabled": False})
    assert disabled.json()["enabled"] is False
    assert client.post("/api/monitor/start").json()["running"] is True
    assert client.get("/api/monitor/status").json()["running"] is True
    assert client.post("/api/monitor/stop").json()["running"] is False
    assert client.delete(f"/api/monitor/tasks/{task_id}").status_code == 204
