from astock.screening.comparison import previous_run_comparison
from astock.features.chart_shapes import uses_shapes
import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from astock.api.dependencies import ApiContext
from astock.api.notes import register_notes
from astock.api.workbench import register_workbench
from astock.sequoia.api import register_sequoia
from astock.backtest.models import BacktestRequest
from astock.backtest.service import BacktestDataError, BacktestService
from astock.config import Settings
from astock.data.daily_update import DailyMarketUpdateScheduler
from astock.data.backup_daily import BackupDailySync, ResilientDailySync
from astock.data.limit_colors import annotate_limits
from astock.data.market_sync import MarketSyncService
from astock.data.providers.akshare import AkShareProvider
from astock.data.providers.baostock import BAOSTOCK_SESSION_LOCK
from astock.data.providers.routing import build_default_market_providers
from astock.data.providers.tencent import TencentQuoteProvider
from astock.data.sectors import SectorStore
from astock.data.service import MarketDataService
from astock.data.updates import MarketUpdates
from astock.domain.market import Adjustment, Timeframe
from astock.features.benchmark import BenchmarkDataError, BenchmarkService
from astock.features.builder import FeatureBuilder, chart_base_timeframe
from astock.features.store import MarketFeatureStore
from astock.features.vacuum import uses_vacuum
from astock.features.price_action import uses_price_action
from astock.features.technical import compute_technical_features
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
from astock.screening.annotations import condition_marks, entry_histories
from astock.screening.catalog import DEFAULT_CATALOG
from astock.screening.models import Node
from astock.screening.scheduler import ScreenScheduleRunner
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
    scope: Literal["market", "watchlist", "run", "board"] = "market"
    watch_group_id: UUID | None = None
    watch_ungrouped: bool = False
    source_run_id: UUID | None = None
    boards: list[str] = Field(default_factory=list)
    instrument_type: Literal["all", "stock", "etf"] = "all"
    extra_timeframes: list[Timeframe] = Field(default_factory=list)
    extra_columns: list[str] = Field(default_factory=list, max_length=200)


class EnabledRequest(BaseModel):
    enabled: bool


class ChartDataSyncRequest(BaseModel):
    timeframe: Timeframe
    start: date
    end: date
    include_benchmark: bool = False


class ScreenTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    tree: Node


class WatchlistRequest(BaseModel):
    symbol: str
    run_id: UUID | None = None
    group_id: UUID | None = None


def _screen_template(row: tuple) -> dict:
    tree = json.loads(row[3]) if isinstance(row[3], str) else row[3]
    return {
        "template_id": str(row[0]),
        "name": row[1],
        "version": row[2],
        "tree": tree,
        "updated_at": row[4],
    }


def _catalog() -> list[dict]:
    return [
        {
            "key": metric.key,
            "label": metric.label,
            "unit": metric.unit.value,
            "timeframes": sorted(item.value for item in metric.timeframes),
            "supported_modes": sorted(metric.supported_modes),
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
        "diagnostics": result.diagnostics,
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
    register_notes(app, context.database)
    monitoring = context.monitoring or MonitoringService(
        context.database,
        MonitoringRepository(context.database),
        TencentQuoteProvider(),
    )
    monitor_scheduler = MonitoringScheduler(monitoring)
    data_update_scheduler = DailyMarketUpdateScheduler(context.market_sync)
    app.state.monitoring = monitoring
    screen_scheduler = ScreenScheduleRunner(context, getattr(monitoring, "outbox", None))
    app.state.screen_scheduler = screen_scheduler
    app.add_event_handler("startup", screen_scheduler.start)
    app.add_event_handler("shutdown", screen_scheduler.stop)
    app.state.monitor_scheduler = monitor_scheduler
    app.state.data_update_scheduler = data_update_scheduler
    app.add_event_handler("startup", data_update_scheduler.start)
    app.add_event_handler("shutdown", monitor_scheduler.stop)
    app.add_event_handler("shutdown", data_update_scheduler.stop)
    feature_builder = FeatureBuilder(
        context.bar_store, MarketFeatureStore(context.database), context.database
    )
    sector_store = SectorStore(context.database)

    @app.get("/api/sectors/status")
    def sector_status():
        return sector_store.status()

    @app.post("/api/sectors/sync", status_code=202)
    def sync_sectors():
        sector_store.start()
        return sector_store.status()

    @app.get("/api/catalog")
    def catalog() -> list[dict]:
        result = _catalog()
        for metric in result:
            if metric["key"] in {"em_industry", "em_concept"}:
                metric["choices"] = sector_store.choices(metric["key"])
        return result

    updates = getattr(context.market_sync, "updates", None) or MarketUpdates()

    @app.get("/api/market-updates/status")
    def market_update_status():
        con = context.database.connection
        latest = con.execute("""select max(feature_date) from market_features
            where timeframe = '1d' and feature_version = 'v1'""").fetchone()[0]
        row = con.execute("""select job_id, end_date, status, total, succeeded, failed,
            current_symbol, started_at, finished_at from data_sync_jobs
            order by started_at desc limit 1""").fetchone()
        job = dict(zip(("job_id", "end_date", "status", "total", "succeeded", "failed",
                        "current_symbol", "started_at", "finished_at"), row)) if row else None
        coverage_start = (latest or datetime.now(SHANGHAI).date()) - timedelta(days=7)
        total_stocks = con.execute("select count(*) from symbols where instrument_type='stock' and is_listed").fetchone()[0]
        coverage = con.execute("""select latest_date,count(*) from (
            select f.symbol,max(f.feature_date) as latest_date from market_features f
            join symbols s on s.symbol=f.symbol and s.instrument_type='stock' and s.is_listed
            where f.timeframe='1d' and f.feature_version='v1'
              and f.feature_date between ? and ?
            group by f.symbol)
            group by latest_date order by latest_date desc""",
            [coverage_start, latest or datetime.now(SHANGHAI).date()],
        ).fetchall()
        older_stocks = total_stocks - sum(count for _, count in coverage)
        if older_stocks:
            coverage.append((None, older_stocks))
        failures = []
        if row:
            failures = [{"symbol": symbol, "error": error} for symbol, error in con.execute(
                "select symbol,error from sync_job_symbols where job_id=? and status='failed' order by updated_at desc limit 12",
                [row[0]]).fetchall()]
        return {"scheduler_running": data_update_scheduler.running,
                "scheduled_at": data_update_scheduler.run_at.strftime("%H:%M"),
                "timezone": "Asia/Shanghai", "latest_daily_date": latest,
                "source": getattr(context.market_sync, "active_source", "baostock"),
                "last_attempt": data_update_scheduler.last_attempt,
                "last_error": data_update_scheduler.last_error,
                "target_date": data_update_scheduler.target_date,
                "next_attempt": data_update_scheduler.next_attempt,
                "latest_completed_end_date": context.market_sync.latest_completed_end_date(),
                "daily_coverage": [{"date": day, "stocks": count} for day, count in coverage],
                "coverage_window_start": coverage_start,
                "failure_examples": failures, "latest_job": job}

    @app.get("/api/market-updates")
    async def market_updates(request: Request):
        async def events():
            revision = updates.revision
            # Also refresh on reconnection: a batch may have finished while offline.
            yield f"event: ready\ndata: {revision}\n\n"
            while not await request.is_disconnected():
                current = await asyncio.to_thread(updates.wait, revision)
                if current != revision:
                    revision = current
                    yield f"event: market-updated\ndata: {revision}\n\n"
                else:
                    yield ": keepalive\n\n"
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/watchlist")
    def list_watchlist():
        con = context.database.connection
        rows = con.execute("select symbol, name, sources, added_at from watchlist order by added_at desc").fetchall()
        groups = {}
        for symbol, identifier, name in con.execute("""select m.symbol, g.group_id, g.name
                from watchlist_group_members m join watchlist_groups g using(group_id) order by g.name""").fetchall():
            groups.setdefault(symbol, []).append({"id": str(identifier), "name": name})
        quotes = {row[0]: {"date": row[1], "close": row[2], "change_percent": row[3]} for row in con.execute(
            """select symbol, feature_date, close, return_1 from market_features
            where timeframe = '1d' and feature_version = 'v1' and symbol in (select symbol from watchlist) and feature_date <= ?
            qualify row_number() over(partition by symbol order by feature_date desc, feature_version desc) = 1""",
            [datetime.now(SHANGHAI).date()],
        ).fetchall()}
        statuses = {row[0]: {"date": row[1], "is_suspended": row[2]} for row in con.execute(
            """select symbol, trade_date, is_suspended from security_status
            where symbol in (select symbol from watchlist) and trade_date <= ?
            qualify row_number() over(partition by symbol order by trade_date desc) = 1""",
            [datetime.now(SHANGHAI).date()],
        ).fetchall()}
        current_quotes = {}
        provider = context.screening.snapshot_provider
        if rows and provider is not None:
            try:
                batch = provider.snapshot_many([row[0] for row in rows])
                current_quotes = {quote.symbol: {
                    "date": quote.timestamp.date(), "timestamp": quote.timestamp,
                    "close": quote.price,
                    "change_percent": (quote.price / quote.previous_close - 1) * 100
                        if quote.previous_close and quote.previous_close > 0 else None,
                    "source": quote.source,
                } for quote in batch.snapshots}
            except Exception:
                logging.getLogger(__name__).exception("watchlist quote refresh failed")
        return jsonable_encoder([
            {"symbol": row[0], "name": row[1], "sources": json.loads(row[2]), "added_at": row[3],
             "groups": groups.get(row[0], []), "quote": quotes.get(row[0]),
             "trading_status": statuses.get(row[0]), "current_quote": current_quotes.get(row[0])}
            for row in rows
        ])

    @app.post("/api/watchlist")
    def add_watchlist(payload: WatchlistRequest):
        con = context.database.connection
        security = con.execute("select name from symbols where symbol = ?", [payload.symbol]).fetchone()
        if not security:
            return JSONResponse(status_code=404, content={"message": "证券不存在"})
        if payload.group_id is not None and not con.execute(
            "select 1 from watchlist_groups where group_id = ?", [payload.group_id]
        ).fetchone():
            return JSONResponse(status_code=422, content={"message": "目标分组不存在，请重新选择"})
        existing = con.execute("select sources from watchlist where symbol = ?", [payload.symbol]).fetchone()
        sources = json.loads(existing[0]) if existing else []
        if payload.run_id is not None:
            source = con.execute(
                """select r.as_of_date, r.condition_tree, m.explanation, r.mode, m.feature_snapshot
                from screen_runs r join screen_matches m on r.run_id = m.run_id
                where r.run_id = ? and m.symbol = ?""",
                [payload.run_id, payload.symbol],
            ).fetchone()
            if not source:
                return JSONResponse(status_code=422, content={"message": "该股票不在此筛选结果中"})
            if not any(item["run_id"] == str(payload.run_id) for item in sources):
                stored_tree, stored_result = json.loads(source[1]), json.loads(source[2])
                histories = {timeframe: MarketFeatureStore(context.database).read_history(
                    payload.symbol, timeframe, source[0], 1000, enrich=False, include_vacuum=uses_vacuum(stored_tree), include_shapes=uses_shapes(stored_tree), include_price_action=uses_price_action(stored_tree)
                ) for timeframe in Timeframe}
                histories = entry_histories(histories, source[3], source[0], json.loads(source[4]))
                sources.append({"run_id": str(payload.run_id), "as_of": source[0].isoformat(),
                                "tree": stored_tree, "explanation": stored_result,
                                "marks": condition_marks(stored_tree, stored_result, histories),
                                "mode": source[3]})
        con.execute(
            """insert into watchlist(symbol, name, sources) values (?, ?, ?)
            on conflict(symbol) do update set name = excluded.name, sources = excluded.sources""",
            [payload.symbol, security[0], json.dumps(sources, ensure_ascii=False)],
        )
        if payload.group_id is not None:
            con.execute("insert into watchlist_group_members values (?, ?) on conflict do nothing", [payload.group_id, payload.symbol])
        return {"symbol": payload.symbol, "name": security[0], "sources": sources}

    register_workbench(app, context, add_watchlist, WatchlistRequest)
    register_sequoia(app, context)

    @app.delete("/api/watchlist/{symbol}", status_code=204)
    def remove_watchlist(symbol: str):
        context.database.connection.execute("delete from watchlist_group_members where symbol = ?", [symbol])
        context.database.connection.execute("delete from watchlist where symbol = ?", [symbol])
        return Response(status_code=204)

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

    @app.get("/api/screens/templates")
    def screen_templates() -> list[dict]:
        rows = context.database.connection.execute(
            """
            select definition_id, name, version, condition_tree, updated_at
            from screen_definitions order by updated_at desc, name
            """
        ).fetchall()
        return jsonable_encoder([_screen_template(row) for row in rows])

    @app.post("/api/screens/templates", status_code=201)
    def save_screen_template(payload: ScreenTemplateRequest):
        errors = context.screening.validate(payload.tree)
        if errors:
            return JSONResponse(
                status_code=422,
                content={
                    "errors": [
                        {"code": error.code, "message": error.message, "path": error.path}
                        for error in errors
                    ]
                },
            )
        name = payload.name.strip()
        existing = context.database.connection.execute(
            "select definition_id from screen_definitions where lower(name) = lower(?) limit 1",
            [name],
        ).fetchone()
        tree = payload.tree.model_dump_json()
        if existing:
            context.database.connection.execute(
                """
                update screen_definitions
                set name = ?, version = version + 1, condition_tree = ?, updated_at = now()
                where definition_id = ?
                """,
                [name, tree, existing[0]],
            )
            template_id = existing[0]
        else:
            template_id = context.database.connection.execute(
                """
                insert into screen_definitions (name, condition_tree)
                values (?, ?) returning definition_id
                """,
                [name, tree],
            ).fetchone()[0]
        row = context.database.connection.execute(
            """
            select definition_id, name, version, condition_tree, updated_at
            from screen_definitions where definition_id = ?
            """,
            [template_id],
        ).fetchone()
        return jsonable_encoder(_screen_template(row))

    @app.delete("/api/screens/templates/{template_id}", status_code=204)
    def delete_screen_template(template_id: UUID):
        row = context.database.connection.execute(
            "delete from screen_definitions where definition_id = ? returning definition_id",
            [template_id],
        ).fetchone()
        if row is None:
            return JSONResponse(
                status_code=404,
                content={"code": "template_not_found", "message": "screen template not found"},
            )
        return Response(status_code=204)

    def execute_screen(request: ScreenRunRequest, progress=None):
        scope_symbols = None
        con = context.database.connection
        if request.scope == "watchlist":
            scope_symbols = [row[0] for row in con.execute("select symbol from watchlist").fetchall()]
            if request.watch_group_id is not None:
                if not con.execute("select 1 from watchlist_groups where group_id = ?", [request.watch_group_id]).fetchone():
                    return JSONResponse(status_code=422, content={"message": "自选分组不存在"})
                members = {row[0] for row in con.execute("select symbol from watchlist_group_members where group_id = ?", [request.watch_group_id]).fetchall()}
                scope_symbols = [symbol for symbol in scope_symbols if symbol in members]
            elif request.watch_ungrouped:
                members = {row[0] for row in con.execute("select symbol from watchlist_group_members").fetchall()}
                scope_symbols = [symbol for symbol in scope_symbols if symbol not in members]
        elif request.scope == "run":
            if request.source_run_id is None or not con.execute("select 1 from screen_runs where run_id = ?", [request.source_run_id]).fetchone():
                return JSONResponse(status_code=422, content={"message": "请选择有效的来源筛选"})
            scope_symbols = [row[0] for row in con.execute("select symbol from screen_matches where run_id = ?", [request.source_run_id]).fetchall()]
        elif request.scope == "board":
            if not request.boards:
                return JSONResponse(status_code=422, content={"message": "请至少选择一个板块"})
            scope_symbols = [row[0] for row in con.execute("select symbol from symbols where board in (select unnest(?))", [request.boards]).fetchall()]
        if request.instrument_type != "all":
            typed = {row[0] for row in con.execute("select symbol from symbols where instrument_type = ?", [request.instrument_type]).fetchall()}
            scope_symbols = sorted(typed if scope_symbols is None else typed.intersection(scope_symbols))
        try:
            result = context.screening.run(
                request.tree,
                as_of=request.as_of,
                mode=request.mode,
                limit=request.limit,
                offset=request.offset,
                scope_symbols=scope_symbols,
                scope_metadata=request.model_dump(mode="json", include={"scope", "source_run_id", "boards", "instrument_type", "watch_group_id", "watch_ungrouped"}),
                extra_timeframes=request.extra_timeframes,
                extra_columns=request.extra_columns,
                progress=progress,
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
        return {**_run_response(result), "new_comparison": previous_run_comparison(context.database.connection, result.run_id)}

    @app.post("/api/screens/run")
    def run_screen(request: ScreenRunRequest):
        return execute_screen(request)

    from astock.screening.tasks import ScreeningTasks
    screen_tasks = ScreeningTasks()

    @app.post("/api/screens/tasks", status_code=202)
    def start_screen_task(request: ScreenRunRequest, tasks: BackgroundTasks):
        job, created = screen_tasks.start(request.model_dump(mode="json"))
        if created:
            tasks.add_task(screen_tasks.run, job['job_id'], lambda progress: execute_screen(request, progress))
        return job

    @app.get("/api/screens/tasks/{job_id}")
    def screen_task(job_id: str):
        return screen_tasks.get(job_id)

    @app.get("/api/screens/runs/{run_id}")
    def screen_results(
        run_id: UUID,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        sort_by: str | None = None,
        sort_direction: Literal["asc", "desc"] | None = None,
        new_only: bool = False,
    ) -> dict:
        row = context.database.connection.execute(
            """
            select status, mode, as_of_date, universe_size, realtime_covered,
                   failed_batches,
                   (select count(*) from screen_matches
                    where screen_matches.run_id = screen_runs.run_id), diagnostics
            from screen_runs where run_id = ?
            """,
            [run_id],
        ).fetchone()
        if row is None:
            return JSONResponse(
                status_code=404,
                content={"code": "run_not_found", "message": "screen run not found"},
            )
        comparison = previous_run_comparison(context.database.connection, run_id)
        entered = comparison['entered'] if comparison else []
        return {
            "new_comparison": comparison,
            "filtered_count": len(entered) if new_only else row[6],
            "run_id": str(run_id),
            "status": row[0],
            "mode": row[1],
            "as_of": row[2],
            "universe_size": row[3],
            "realtime_covered": row[4],
            "failed_batches": row[5],
            "match_count": row[6],
            "diagnostics": {"conditions": {}, "warnings": [], "data_dates": {},
                            **(json.loads(row[7]) if row[7] else {})},
            "matches": context.screening.results(
                run_id, limit, offset, sort_by, sort_direction, symbols=entered if new_only else None
            ),
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

    @app.get("/api/symbols/{symbol}/overview")
    def stock_overview(symbol: str):
        identity = context.database.connection.execute(
            "select name, exchange, board, listed_on, instrument_type from symbols where symbol = ?", [symbol]
        ).fetchone()
        if identity is None:
            return JSONResponse(status_code=404, content={"message": "证券不存在"})
        quote = None
        message = None
        provider = context.screening.snapshot_provider
        try:
            if provider is not None:
                batch = provider.snapshot_many([symbol])
                quote = next((row for row in batch.snapshots if row.symbol == symbol), None)
            if quote is None:
                message = "最新行情暂不可用，请稍后刷新"
        except Exception:  # noqa: BLE001 - external quote provider boundary
            message = "行情源暂不可用，请稍后刷新"
        return jsonable_encoder({
            "symbol": symbol, "name": identity[0], "exchange": identity[1],
            "board": identity[2], "listed_on": identity[3], "instrument_type": identity[4],
            "quote": quote, "message": message,
            "valuation_note": "市盈率采用腾讯公布的 PE 原值，接口未明确标注静态/动态/TTM 口径；负值保留，缺失值不按零处理。市值为当前快照。",
        })

    @app.get("/api/symbols/{symbol}/indicators")
    def symbol_indicators(
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[dict]:
        base = chart_base_timeframe(timeframe)
        source = [
            bar
            for bar in context.bar_store.read(symbol, base, Adjustment.QFQ)
            if bar.timestamp.date() <= end and bar.is_final
        ]
        bars = source if timeframe == base else MarketDataService.derive(source, timeframe)
        if not bars:
            return []
        frame = pd.DataFrame(
            [
                {
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume_shares": bar.volume_shares,
                    "amount_cny": bar.amount_cny,
                }
                for bar in bars
            ]
        )
        fields = (
            "ma_5", "ma_10", "ma_20", "ma_30", "boll_upper", "boll_middle",
            "boll_lower", "macd", "macd_signal", "macd_hist", "kdj_k",
            "kdj_d", "kdj_j", "rsi_14", "volume_ma_5", "volume_ma_20",
            "obv", "atr_14",
        )
        features = compute_technical_features(frame)
        fields = tuple(dict.fromkeys((*fields, *[
            metric.key for metric in DEFAULT_CATALOG.all()
            if metric.key in features.columns and metric.unit.value not in {"category", "boolean"}
        ])))
        visible = features[
            features["timestamp"].dt.date.between(start, end)
        ]
        return [
            {
                "timestamp": row["timestamp"],
                **{
                    field: None if pd.isna(row[field]) else float(row[field])
                    for field in fields
                },
            }
            for _, row in visible.iterrows()
        ]

    @app.get("/api/symbols/{symbol}/benchmark-comparison")
    def benchmark_comparison(
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ):
        if context.benchmark is None:
            return JSONResponse(
                status_code=503,
                content={"code": "benchmark_unavailable", "message": "大盘对比服务未配置"},
            )
        try:
            result = context.benchmark.compare(
                symbol, timeframe, start, end, start_at, end_at
            )
        except BenchmarkDataError as error:
            status = 404 if error.code == "symbol_not_found" else 409
            return JSONResponse(
                status_code=status,
                content={"code": error.code, "message": str(error)},
            )
        return result.model_dump(mode="json")

    @app.post("/api/symbols/{symbol}/chart-data/sync")
    def sync_chart_data(symbol: str, request: ChartDataSyncRequest):
        if context.benchmark is None:
            return JSONResponse(
                status_code=503,
                content={"code": "sync_unavailable", "message": "行情同步服务未配置"},
            )
        try:
            return context.benchmark.sync(
                symbol,
                request.timeframe,
                request.start,
                request.end,
                request.include_benchmark,
            )
        except BenchmarkDataError as error:
            if error.code == "symbol_not_found":
                status = 404
            elif error.code == "minute_history_unavailable":
                status = 422
            else:
                status = 409
            return JSONResponse(
                status_code=status,
                content={"code": error.code, "message": str(error)},
            )

    def refresh_chart_limits(symbol: str, start: date, end: date) -> None:
        market_data = getattr(context.market_sync, "market_data", None)
        if market_data is not None and BAOSTOCK_SESSION_LOCK.acquire(blocking=False):
            try:
                market_data.history(symbol, Timeframe.DAY, start, end, Adjustment.NONE)
                reference = market_data.reference_provider
                if reference is not None:
                    statuses = reference.security_status(symbol, start, end)
                    if statuses:
                        con = context.database.connection
                        con.executemany("insert or replace into security_status values (?, ?, ?, ?, ?, ?, ?, ?)",
                            [[row[key] for key in ("symbol", "trade_date", "board", "is_st", "is_suspended", "previous_close", "limit_up", "limit_down")] for row in statuses])
            except Exception:
                logging.getLogger(__name__).exception("chart limit-price data unavailable")
            finally:
                BAOSTOCK_SESSION_LOCK.release()

    @app.get("/api/symbols/{symbol}/bars")
    def symbol_bars(
        background_tasks: BackgroundTasks,
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
        identity = context.database.connection.execute("select instrument_type from symbols where symbol = ?", [symbol]).fetchone()
        if timeframe == Timeframe.DAY and identity and identity[0] == "stock":
            background_tasks.add_task(refresh_chart_limits, symbol, start, end)
            raw = context.bar_store.read_range(symbol, Timeframe.DAY, Adjustment.NONE, start, end)
            statuses = {row[0]: row[1:] for row in context.database.connection.execute(
                "select trade_date,is_suspended,limit_up,limit_down from security_status where symbol = ? and trade_date between ? and ?", [symbol,start,end]
            ).fetchall()}
            return annotate_limits(bars, raw, statuses)
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
                    "message": str(error),
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
    market_sync = ResilientDailySync(market_sync, BackupDailySync(
        database, bars, market_sync.jobs, market_sync.feature_builder, market_sync.updates
    ))
    benchmark = BenchmarkService(database, bars, market_data, AkShareProvider())
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
    return create_app(
        ApiContext(database, bars, screening, market_sync, monitoring, benchmark)
    )


__all__ = ["ApiContext", "create_app", "create_default_app"]
