from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from astock.api.app import ApiContext, create_app, create_default_app
from astock.config import Settings
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.features.store import MarketFeatureStore
from astock.features.zones import PriceZone, replace_auto_zones
from astock.screening.service import ScreeningService
from astock.storage.bars import BarStore
from astock.storage.database import Database


class FakeSync:
    def status(self, job_id: UUID):
        return SimpleNamespace(
            job_id=job_id,
            status="running",
            total=5000,
            succeeded=100,
            failed=2,
        )


def _client(tmp_path: Path) -> tuple[TestClient, Database]:
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
    )
    context = ApiContext(
        database=database,
        bar_store=bar_store,
        screening=ScreeningService(database, MarketFeatureStore(database)),
        market_sync=FakeSync(),
    )
    return TestClient(create_app(context)), database


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


def test_zones_api_returns_trends_independently_of_horizontal_limit(tmp_path: Path) -> None:
    client, database = _client(tmp_path)
    database.connection.executemany(
        """
        insert into support_resistance_zones
          (zone_id, symbol, timeframe, as_of_date, zone_kind, geometry,
           lower_price, center_price, upper_price, slope, intercept, strength,
           touches, last_touched_on, source, rule_version)
        values (?, '600001.SH', '1d', '2026-08-20', ?, 'trend', ?, ?, ?, ?, ?,
                0.8, 3, '2026-08-20', 'auto', 'v1')
        """,
        [
            ["00000000-0000-0000-0000-000000000201", "uptrend", 12.9, 13.0, 13.1, 0.1, 10.0],
            ["00000000-0000-0000-0000-000000000202", "downtrend", 10.9, 11.0, 11.1, -0.1, 14.0],
        ],
    )

    response = client.get(
        "/api/symbols/600001.SH/zones",
        params={"timeframe": "1d", "as_of": "2026-08-20", "limit_each": 1},
    )

    assert response.status_code == 200
    assert {row["zone_kind"] for row in response.json()} == {
        "support",
        "uptrend",
        "downtrend",
    }


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
