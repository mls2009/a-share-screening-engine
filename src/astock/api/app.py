from datetime import date, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from astock.api.dependencies import ApiContext
from astock.backtest.models import BacktestRequest
from astock.backtest.service import BacktestDataError, BacktestService
from astock.config import Settings
from astock.data.market_sync import MarketSyncService
from astock.data.providers.routing import build_default_market_providers
from astock.data.providers.tencent import TencentQuoteProvider
from astock.data.service import MarketDataService
from astock.domain.market import Adjustment, Timeframe
from astock.features.builder import FeatureBuilder, chart_base_timeframe
from astock.features.store import MarketFeatureStore
from astock.features.zones import (
    ManualZoneInput,
    chart_zones,
    create_manual_zone,
    delete_zone,
)
from astock.live.calendar import SHANGHAI
from astock.live.models import MonitorScope, MonitorTaskCreate
from astock.live.repository import MonitoringRepository
from astock.live.scheduler import MonitoringScheduler
from astock.live.service import MonitoringService
from astock.notifications.feishu import FeishuNotifier
from astock.notifications.outbox import OutboxWorker
from astock.screening.catalog import DEFAULT_CATALOG
from astock.screening.models import Node
from astock.screening.service import ScreenDefinitionError, ScreeningService
from astock.storage.bars import BarStore
from astock.storage.database import Database
from astock.storage.jobs import SyncJobRepository


class ScreenRunRequest(BaseModel):
    tree: Node
    mode: Literal["close", "live"] = "close"
    as_of: date
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class EnabledRequest(BaseModel):
    enabled: bool


def _catalog() -> list[dict]:
    return [
        {
            "key": metric.key,
            "label": metric.label,
            "unit": metric.unit.value,
            "timeframes": sorted(item.value for item in metric.timeframes),
            "operators": sorted(item.value for item in metric.operators),
            "group": metric.group,
            "family": metric.family or metric.key,
            "period": metric.period,
            "directions": [
                {"value": item.value, "label": item.label}
                for item in metric.directions
            ],
            "choices": [
                {"value": item.value, "label": item.label}
                for item in metric.choices
            ],
            "multiple": metric.multiple,
            "visible": metric.visible,
        }
        for metric in DEFAULT_CATALOG.all()
    ]


def _run_response(result: object) -> dict:
    return {
        "run_id": str(result.run_id),
        "status": result.status,
        "universe_size": result.universe_size,
        "match_count": result.match_count,
        "realtime_covered": result.realtime_covered,
        "failed_batches": result.failed_batches,
        "matches": [
            {
                "symbol": match.symbol,
                "rank": match.rank,
                "features": match.features,
                "explanation": match.explanation.to_dict(),
            }
            for match in result.matches
        ],
    }


def create_app(context: ApiContext, frontend_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="AStock Internal API", version="0.1.0")
    app.state.context = context
    monitoring = context.monitoring or MonitoringService(
        context.database,
        MonitoringRepository(context.database),
        TencentQuoteProvider(),
    )
    monitor_scheduler = MonitoringScheduler(monitoring)
    app.state.monitoring = monitoring
    app.state.monitor_scheduler = monitor_scheduler
    app.add_event_handler("shutdown", monitor_scheduler.stop)
    feature_builder = FeatureBuilder(
        context.bar_store, MarketFeatureStore(context.database), context.database
    )

    @app.get("/api/catalog")
    def catalog() -> list[dict]:
        return _catalog()

    @app.post("/api/screens/validate")
    def validate_screen(tree: Node) -> dict:
        errors = context.screening.validate(tree)
        return {
            "valid": not errors,
            "errors": [
                {"code": error.code, "message": error.message, "path": error.path}
                for error in errors
            ],
        }

    @app.post("/api/screens/run")
    def run_screen(request: ScreenRunRequest):
        try:
            result = context.screening.run(
                request.tree,
                as_of=request.as_of,
                mode=request.mode,
                limit=request.limit,
                offset=request.offset,
            )
        except ScreenDefinitionError as error:
            return JSONResponse(
                status_code=422,
                content={
                    "errors": [
                        {
                            "code": issue.code,
                            "message": issue.message,
                            "path": issue.path,
                        }
                        for issue in error.issues
                    ]
                },
            )
        return _run_response(result)

    @app.get("/api/screens/runs/{run_id}")
    def screen_results(
        run_id: UUID,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        row = context.database.connection.execute(
            """
            select status, mode, as_of_date, universe_size, realtime_covered,
                   failed_batches,
                   (select count(*) from screen_matches
                    where screen_matches.run_id = screen_runs.run_id)
            from screen_runs where run_id = ?
            """,
            [run_id],
        ).fetchone()
        if row is None:
            return JSONResponse(
                status_code=404,
                content={"code": "run_not_found", "message": "screen run not found"},
            )
        return {
            "run_id": str(run_id),
            "status": row[0],
            "mode": row[1],
            "as_of": row[2],
            "universe_size": row[3],
            "realtime_covered": row[4],
            "failed_batches": row[5],
            "match_count": row[6],
            "matches": context.screening.results(run_id, limit, offset),
        }

    @app.get("/api/sync/jobs/{job_id}")
    def sync_status(job_id: UUID) -> dict:
        summary = context.market_sync.status(job_id)
        return {
            "job_id": str(summary.job_id),
            "status": summary.status,
            "total": summary.total,
            "succeeded": summary.succeeded,
            "failed": summary.failed,
        }

    @app.get("/api/symbols/search")
    def search_symbols(
        q: str,
        limit: int = Query(default=10, ge=1, le=20),
    ) -> list[dict]:
        query = q.strip()
        if not query:
            return []
        normalized = query.upper()
        rows = context.database.connection.execute(
            """
            select symbol, name, exchange, instrument_type
            from symbols
            where is_listed
              and (
                upper(symbol) = ?
                or split_part(upper(symbol), '.', 1) = ?
                or starts_with(upper(symbol), ?)
                or contains(upper(name), ?)
              )
            order by
              case
                when upper(symbol) = ? then 0
                when split_part(upper(symbol), '.', 1) = ? then 1
                when starts_with(upper(symbol), ?) then 2
                else 3
              end,
              symbol
            limit ?
            """,
            [
                normalized,
                normalized,
                normalized,
                normalized,
                normalized,
                normalized,
                normalized,
                limit,
            ],
        ).fetchall()
        return [
            {
                "symbol": row[0],
                "name": row[1],
                "exchange": row[2],
                "instrument_type": row[3],
            }
            for row in rows
        ]

    @app.get("/api/symbols/{symbol}/bars")
    def symbol_bars(
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[dict]:
        base = chart_base_timeframe(timeframe)
        source = context.bar_store.read_range(
            symbol, base, Adjustment.QFQ, start, end
        )
        bars = source if timeframe == base else MarketDataService.derive(source, timeframe)
        return [bar.model_dump(mode="json") for bar in bars]

    @app.get("/api/symbols/{symbol}/zones")
    def symbol_zones(
        symbol: str,
        timeframe: Timeframe,
        as_of: date,
        limit_each: int = Query(default=3, ge=1, le=20),
    ) -> list[dict]:
        latest_close = feature_builder.ensure_chart_zones(symbol, timeframe, as_of)
        rows = chart_zones(
            context.database.connection,
            symbol,
            timeframe,
            as_of,
            limit_each,
            close_override=latest_close,
        )
        return jsonable_encoder(rows)

    @app.post("/api/symbols/{symbol}/zones/manual", status_code=201)
    def add_manual_zone(symbol: str, zone: ManualZoneInput) -> dict:
        zone_id = create_manual_zone(context.database.connection, symbol, zone)
        row = context.database.connection.execute(
            "select * from support_resistance_zones where zone_id = ?", [zone_id]
        )
        values = row.fetchone()
        columns = [column[0] for column in row.description]
        created = dict(zip(columns, values, strict=True))
        created["reappeared"] = context.database.connection.execute(
            """
            select exists(
              select 1 from zone_deletion_markers
              where symbol = ? and timeframe = ? and geometry = ?
                and lower_price <= ? and upper_price >= ?
            )
            """,
            [
                symbol,
                zone.timeframe.value,
                zone.geometry,
                zone.center_price,
                zone.center_price,
            ],
        ).fetchone()[0]
        return jsonable_encoder(created)

    @app.delete("/api/symbols/{symbol}/zones/{zone_id}")
    def remove_zone(symbol: str, zone_id: UUID):
        if not delete_zone(context.database.connection, symbol, zone_id):
            return JSONResponse(
                status_code=404,
                content={"code": "zone_not_found", "message": "zone not found"},
            )
        return Response(status_code=204)

    @app.post("/api/backtests/run")
    def run_backtest(request: BacktestRequest):
        service = BacktestService(context.database, context.bar_store)
        try:
            run = service.run(request)
        except BacktestDataError as error:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "missing_backtest_data",
                    "message": "本地数据库缺少回测行情，请先同步对应股票和周期",
                    "symbols": error.symbols,
                },
            )
        return jsonable_encoder(run)

    @app.get("/api/backtests/{run_id}")
    def backtest_result(run_id: UUID):
        run = BacktestService(context.database, context.bar_store).get(run_id)
        if run is None:
            return JSONResponse(
                status_code=404,
                content={"code": "run_not_found", "message": "backtest run not found"},
            )
        return jsonable_encoder(run)

    @app.get("/api/monitor/tasks")
    def monitor_tasks() -> list[dict]:
        return jsonable_encoder(monitoring.repository.list_tasks())

    @app.post("/api/monitor/tasks", status_code=201)
    def create_monitor_task(payload: MonitorTaskCreate) -> dict:
        return jsonable_encoder(monitoring.repository.create_task(payload))

    @app.patch("/api/monitor/tasks/{task_id}")
    def update_monitor_task(task_id: UUID, payload: EnabledRequest):
        task = monitoring.repository.set_enabled(task_id, payload.enabled)
        if task is None:
            return JSONResponse(
                status_code=404,
                content={"code": "task_not_found", "message": "monitor task not found"},
            )
        return jsonable_encoder(task)

    @app.delete("/api/monitor/tasks/{task_id}")
    def delete_monitor_task(task_id: UUID):
        if not monitoring.repository.delete_task(task_id):
            return JSONResponse(
                status_code=404,
                content={"code": "task_not_found", "message": "monitor task not found"},
            )
        return Response(status_code=204)

    @app.post("/api/monitor/scan")
    def scan_monitor(scope: MonitorScope = MonitorScope.WATCHLIST) -> dict:
        now = datetime.now(SHANGHAI)
        result = (
            monitoring.run_watchlist_once(now, force=True)
            if scope == MonitorScope.WATCHLIST
            else monitoring.run_market_once(now, force=True)
        )
        return jsonable_encoder(result)

    @app.get("/api/monitor/signals")
    def monitor_signals(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict]:
        return jsonable_encoder(monitoring.repository.list_signals(limit))

    @app.get("/api/monitor/status")
    def monitor_status() -> dict:
        tasks = monitoring.repository.list_tasks()
        pending = context.database.connection.execute(
            "select count(*) from notification_outbox where status = 'pending'"
        ).fetchone()[0]
        return {
            "running": monitor_scheduler.running,
            "tasks": len(tasks),
            "enabled_tasks": sum(task.enabled for task in tasks),
            "pending_notifications": pending,
            "feishu_configured": monitoring.outbox is not None,
            "watchlist_interval_seconds": 5,
            "market_interval_seconds": 300,
        }

    @app.post("/api/monitor/start")
    def start_monitor() -> dict:
        monitor_scheduler.start()
        return {"running": monitor_scheduler.running}

    @app.post("/api/monitor/stop")
    def stop_monitor() -> dict:
        monitor_scheduler.stop()
        return {"running": monitor_scheduler.running}

    @app.post("/api/notifications/feishu/test")
    def test_feishu():
        if monitoring.outbox is None:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "feishu_not_configured",
                    "message": "请先设置 ASTOCK_FEISHU_WEBHOOK，可选设置 ASTOCK_FEISHU_SECRET",
                },
            )
        result = monitoring.outbox.notifier.send(
            {
                "type": "system_test",
                "task_name": "飞书机器人连接测试",
                "symbol": "SYSTEM",
                "comparator": "above",
                "threshold": "—",
                "price": "连接正常",
                "triggered_at": datetime.now(SHANGHAI).isoformat(),
            }
        )
        if not result.success:
            return JSONResponse(
                status_code=502,
                content={"code": "feishu_delivery_failed", "message": result.error},
            )
        return {"success": True}

    resolved_frontend = frontend_dir or Path(__file__).resolve().parents[3] / "web" / "dist"
    index_file = resolved_frontend / "index.html"
    assets_dir = resolved_frontend / "assets"
    if index_file.is_file():
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @app.get("/{spa_path:path}", include_in_schema=False)
        def frontend(spa_path: str):
            if spa_path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"code": "api_not_found", "message": "API route not found"},
                )
            return FileResponse(index_file)

    return app


def create_default_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.migrate()
    bars = BarStore(settings.bars_dir)
    history_provider, reference_provider = build_default_market_providers()
    feature_store = MarketFeatureStore(database)
    market_data = MarketDataService(
        history_provider,
        bars,
        database,
        reference_provider=reference_provider,
    )
    market_sync = MarketSyncService(
        market_data,
        reference_provider,
        SyncJobRepository(database.connection),
        FeatureBuilder(bars, feature_store, database),
    )
    screening = ScreeningService(
        database,
        feature_store,
        snapshot_provider=TencentQuoteProvider(),
    )
    repository = MonitoringRepository(database)
    outbox = None
    if settings.feishu_webhook is not None:
        notifier = FeishuNotifier(
            settings.feishu_webhook.get_secret_value(),
            settings.feishu_secret.get_secret_value() if settings.feishu_secret else None,
        )
        outbox = OutboxWorker(database, notifier)
    monitoring = MonitoringService(
        database,
        repository,
        TencentQuoteProvider(),
        outbox=outbox,
    )
    return create_app(ApiContext(database, bars, screening, market_sync, monitoring))


__all__ = ["ApiContext", "create_app", "create_default_app"]
