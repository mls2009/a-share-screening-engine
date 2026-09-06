import csv
import io
import json
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, TypeAdapter

from astock.data.sectors import SectorStore
from astock.domain.market import Timeframe
from astock.features.store import MarketFeatureStore
from astock.live.calendar import SHANGHAI
from astock.screening.annotations import condition_marks, entry_histories
from astock.screening.evaluator import evaluate_tree
from astock.screening.models import Node


class BatchWatchRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    all_matches: bool = False


class ScheduleRequest(BaseModel):
    enabled: bool
    notify: bool = False


def register_workbench(app, context, add_watchlist, watch_request):
    con = context.database.connection

    @app.get("/api/workbench/schedules")
    def schedules():
        return jsonable_encoder([dict(zip(["template_id", "enabled", "notify", "last_date", "last_version", "last_run_id", "last_error"], row, strict=True)) for row in con.execute("select * from screen_schedules").fetchall()])

    @app.put("/api/workbench/schedules/{template_id}")
    def save_schedule(template_id: UUID, payload: ScheduleRequest):
        if not con.execute("select 1 from screen_definitions where definition_id = ?", [template_id]).fetchone():
            raise HTTPException(404, "模板不存在")
        if payload.notify and not getattr(app.state.monitoring, "outbox", None):
            raise HTTPException(422, "尚未配置飞书机器人，请先在实时监控中检查配置")
        con.execute("""insert into screen_schedules(definition_id, enabled, notify) values (?, ?, ?)
            on conflict(definition_id) do update set enabled = excluded.enabled, notify = excluded.notify""", [template_id, payload.enabled, payload.notify])
        return {"template_id": str(template_id), **payload.model_dump()}

    def run_record(run_id):
        row = con.execute("select condition_tree, as_of_date, mode, diagnostics from screen_runs where run_id = ?", [run_id]).fetchone()
        if row is None:
            raise HTTPException(404, "筛选记录不存在")
        return {"tree": json.loads(row[0]), "as_of": row[1], "mode": row[2],
                "scope": (json.loads(row[3]) if row[3] else {}).get("scope", {"scope": "market"})}

    @app.get("/api/workbench/runs")
    def runs():
        rows = con.execute("""select run_id, as_of_date, mode, condition_tree, finished_at,
            (select count(*) from screen_matches m where m.run_id = r.run_id)
            from screen_runs r order by finished_at desc limit 100""").fetchall()
        return jsonable_encoder([{"run_id": str(row[0]), "as_of": row[1], "mode": row[2], "tree": json.loads(row[3]), "finished_at": row[4], "match_count": row[5]} for row in rows])

    @app.get("/api/workbench/runs/{run_id}/compare/{previous_id}")
    def compare(run_id: UUID, previous_id: UUID):
        current, previous = run_record(run_id), run_record(previous_id)
        def symbols(identifier):
            return {row[0]: json.loads(row[1]).get("name", row[0]) for row in con.execute("select symbol, feature_snapshot from screen_matches where run_id = ?", [identifier]).fetchall()}
        new, old = symbols(run_id), symbols(previous_id)
        return {"same_definition": TypeAdapter(Node).validate_python(current["tree"]) == TypeAdapter(Node).validate_python(previous["tree"]),
                "same_scope": current["scope"] == previous["scope"], "same_mode": current["mode"] == previous["mode"],
                "current_date": str(current["as_of"]), "previous_date": str(previous["as_of"]),
                **{key: [{"symbol": symbol, "name": new.get(symbol, old.get(symbol))} for symbol in sorted(items)]
                   for key, items in {"entered": new.keys() - old.keys(), "stayed": new.keys() & old.keys(), "exited": old.keys() - new.keys()}.items()}}

    @app.post("/api/workbench/runs/{run_id}/watchlist")
    def batch_watchlist(run_id: UUID, payload: BatchWatchRequest):
        run_record(run_id)
        matches = {row[0] for row in con.execute("select symbol from screen_matches where run_id = ?", [run_id]).fetchall()}
        wanted = matches if payload.all_matches else set(payload.symbols)
        if not wanted.issubset(matches):
            raise HTTPException(422, "所选股票不属于当前筛选结果")
        for symbol in sorted(wanted):
            result = add_watchlist(watch_request(symbol=symbol, run_id=run_id))
            if isinstance(result, Response):
                return result
        return {"added": len(wanted)}

    @app.get("/api/workbench/runs/{run_id}/export")
    def export(run_id: UUID, columns: str = "close,return_20,volume_ratio_20", sort_by: str | None = None, sort_direction: str = "asc"):
        run_record(run_id)
        from astock.screening.catalog import DEFAULT_CATALOG
        keys = [key for key in columns.split(",") if DEFAULT_CATALOG.get(key.split(":")[-1])]
        def label(key):
            parts = key.split(":")
            spec = DEFAULT_CATALOG.get(parts[-1])
            return f"{spec.label}{' ' + str(spec.period) + '周期' if spec.period else ''}{' (' + parts[0] + ')' if len(parts) == 2 else ''}"
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["代码", "名称", *map(label, keys)])
        count = con.execute("select count(*) from screen_matches where run_id = ?", [run_id]).fetchone()[0]
        def safe(value):
            if value is None:
                return ""
            return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value
        for match in context.screening.results(run_id, count, 0, sort_by, sort_direction):
            features = match["features"]
            writer.writerow([match["symbol"], safe(features.get("name")), *[safe(features.get("metric_values", {}).get(key) if ":" in key else features.get(key)) for key in keys]])
        return Response("\ufeff" + stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="screen-results.csv"'})

    @app.get("/api/workbench/runs/{run_id}/detail/{symbol}")
    def detail(run_id: UUID, symbol: str, latest: bool = False, days: int = Query(20, ge=1, le=60)):
        record = run_record(run_id)
        row = con.execute("select feature_snapshot, explanation from screen_matches where run_id = ? and symbol = ?", [run_id, symbol]).fetchone()
        if row is None:
            raise HTTPException(404, "股票不在该次筛选结果内")
        as_of = datetime.now(SHANGHAI).date() if latest else record["as_of"]
        store = MarketFeatureStore(context.database)
        def zone_timeframes(node):
            if node.get("children") is not None:
                return set().union(*(zone_timeframes(child) for child in node["children"]))
            return {item.get("timeframe", node.get("timeframe")) for item in (node, node.get("right", {}))
                    if item.get("metric") in {"support_distance", "resistance_distance"}}
        enriched_frames = zone_timeframes(record["tree"])
        histories = {timeframe: store.read_history(symbol, timeframe, as_of, 1100, enrich=timeframe.value in enriched_frames) for timeframe in Timeframe}
        # Point-in-time status and patterns are needed for historic condition checks.
        statuses = con.execute("select trade_date, is_st, is_suspended from security_status where symbol = ? and trade_date <= ? order by trade_date", [symbol, as_of]).fetchall()
        identity = con.execute("select name, board from symbols where symbol = ?", [symbol]).fetchone()
        patterns = {}
        for timeframe, stamp, pattern, strength in con.execute("select timeframe, event_date, pattern_type, strength from pattern_events where symbol = ? and event_date <= ?", [symbol, as_of]).fetchall():
            patterns.setdefault((timeframe, stamp), []).append((pattern, strength))
        for timeframe, values in histories.items():
            for value in values:
                value.update({"name": identity[0], "board": identity[1]} if identity else {})
                status = next((item for item in reversed(statuses) if item[0] <= value["feature_date"]), None)
                value.update({"is_st": status[1] if status else None, "is_suspended": status[2] if status else None})
                events = patterns.get((timeframe.value, value["feature_date"]), [])
                value["pattern_type"] = [event[0] for event in events] or None
                value["pattern_strength"] = max((event[1] for event in events), default=None)
        tree = TypeAdapter(Node).validate_python(record["tree"])
        evaluation = evaluate_tree(tree, histories).to_dict() if latest else json.loads(row[1])
        changes = []
        for day in reversed(histories[Timeframe.DAY][:days]):
            shifted = {timeframe: [value for value in values if value["feature_date"] <= day["feature_date"]] for timeframe, values in histories.items()}
            checked = evaluate_tree(tree, shifted).to_dict()
            changes.append({"date": str(day["feature_date"]), "evaluation": checked})
        features = (histories[Timeframe.DAY][0] if histories[Timeframe.DAY] else {}) if latest else json.loads(row[0])
        if latest:
            features.update(SectorStore(context.database).values().get(symbol, {}))
            evaluation = evaluate_tree(tree, histories).to_dict()
        mark_histories = histories if latest else entry_histories(histories, record["mode"], as_of, features)
        return jsonable_encoder({"symbol": symbol, "features": features, "source": {
            "run_id": str(run_id), "as_of": str(as_of), "mode": "close" if latest else record["mode"],
            "tree": record["tree"], "explanation": evaluation, "marks": condition_marks(record["tree"], evaluation, mark_histories)},
            "recent": changes, "checked_at": str(as_of), "latest": latest})
