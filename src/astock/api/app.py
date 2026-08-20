from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from astock.api.dependencies import ApiContext
from astock.data.service import MarketDataService
from astock.domain.market import Adjustment, Timeframe
from astock.features.zones import nearest_zones
from astock.screening.catalog import DEFAULT_CATALOG
from astock.screening.models import Node
from astock.screening.service import ScreenDefinitionError


class ScreenRunRequest(BaseModel):
    tree: Node
    mode: Literal["close", "live"] = "close"
    as_of: date
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


def _catalog() -> list[dict]:
    return [
        {
            "key": metric.key,
            "label": metric.label,
            "unit": metric.unit.value,
            "timeframes": sorted(item.value for item in metric.timeframes),
            "operators": sorted(item.value for item in metric.operators),
        }
        for metric in DEFAULT_CATALOG.all()
    ]


def _run_response(result: object) -> dict:
    return {
        "run_id": str(result.run_id),
        "status": result.status,
        "universe_size": result.universe_size,
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


def create_app(context: ApiContext) -> FastAPI:
    app = FastAPI(title="AStock Internal API", version="0.1.0")

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
            select status, mode, as_of_date, universe_size, realtime_covered, failed_batches
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

    @app.get("/api/symbols/{symbol}/bars")
    def symbol_bars(
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
    ) -> list[dict]:
        if timeframe not in {Timeframe.DAY, Timeframe.WEEK, Timeframe.MONTH}:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "unsupported_timeframe",
                    "message": "chart API supports day, week and month",
                    "path": "timeframe",
                },
            )
        daily = context.bar_store.read_range(
            symbol, Timeframe.DAY, Adjustment.QFQ, start, end
        )
        bars = daily if timeframe == Timeframe.DAY else MarketDataService.derive(daily, timeframe)
        return [bar.model_dump(mode="json") for bar in bars]

    @app.get("/api/symbols/{symbol}/zones")
    def symbol_zones(
        symbol: str,
        timeframe: Timeframe,
        as_of: date,
        limit_each: int = Query(default=3, ge=1, le=20),
    ) -> list[dict]:
        rows = nearest_zones(
            context.database.connection, symbol, timeframe, as_of, limit_each
        )
        return jsonable_encoder(rows)

    return app


__all__ = ["ApiContext", "create_app"]
