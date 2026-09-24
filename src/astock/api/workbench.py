import csv
import io
import json
from datetime import date, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, TypeAdapter, field_validator

from astock.data.sectors import SectorStore
from astock.domain.market import Timeframe
from astock.features.chart_shapes import uses_shapes
from astock.features.ma_pierce import uses_ma_pierce
from astock.features.price_action import PA_METRICS, uses_price_action
from astock.features.store import MarketFeatureStore
from astock.features.vacuum import uses_vacuum
from astock.live.calendar import SHANGHAI
from astock.screening.annotations import condition_marks, entry_histories
from astock.screening.evaluator import evaluate_tree
from astock.screening.models import GroupNode, MetricOperand, Node
from astock.screening.validation import validate_tree
from astock.screening.waves import WaveRequest, scan_waves


class BatchWatchRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    all_matches: bool = False
    group_id: UUID | None = None


class WatchGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("分组名称不能为空")
        return value.strip()


class WatchMembershipRequest(BaseModel):
    group_ids: list[UUID] = Field(max_length=100)


class ScheduleRequest(BaseModel):
    enabled: bool
    notify: bool = False


def register_workbench(app, context, add_watchlist, watch_request):
    con = context.database.connection

    @app.get("/api/watchlist/groups")
    def watch_groups():
        return [{"id": str(identifier), "name": name} for identifier, name in
                con.execute("select group_id, name from watchlist_groups order by name").fetchall()]

    def unique_group_name(name, identifier=None):
        row = con.execute("select group_id from watchlist_groups where name = ?", [name]).fetchone()
        if row and row[0] != identifier:
            raise HTTPException(409, "已有同名分组")

    @app.post("/api/watchlist/groups")
    def create_watch_group(payload: WatchGroupRequest):
        unique_group_name(payload.name)
        identifier = uuid4()
        con.execute("insert into watchlist_groups values (?, ?)", [identifier, payload.name])
        return {"id": str(identifier), "name": payload.name}

    @app.put("/api/watchlist/groups/{identifier}")
    def rename_watch_group(identifier: UUID, payload: WatchGroupRequest):
        if not con.execute("select 1 from watchlist_groups where group_id = ?", [identifier]).fetchone():
            raise HTTPException(404, "分组不存在")
        unique_group_name(payload.name, identifier)
        con.execute("update watchlist_groups set name = ? where group_id = ?", [payload.name, identifier])
        return {"id": str(identifier), "name": payload.name}

    @app.delete("/api/watchlist/groups/{identifier}", status_code=204)
    def delete_watch_group(identifier: UUID):
        con.execute("begin transaction")
        try:
            con.execute("delete from watchlist_group_members where group_id = ?", [identifier])
            con.execute("delete from watchlist_groups where group_id = ?", [identifier])
            con.execute("commit")
        except Exception:
            con.execute("rollback")
            raise
        return Response(status_code=204)

    @app.put("/api/watchlist/{symbol}/groups")
    def set_watch_groups(symbol: str, payload: WatchMembershipRequest):
        if not con.execute("select 1 from watchlist where symbol = ?", [symbol]).fetchone():
            raise HTTPException(404, "自选股不存在")
        wanted = set(payload.group_ids)
        available = {row[0] for row in con.execute("select group_id from watchlist_groups").fetchall()}
        if not wanted.issubset(available):
            raise HTTPException(422, "所选分组已不存在")
        con.execute("begin transaction")
        try:
            con.execute("delete from watchlist_group_members where symbol = ?", [symbol])
            for identifier in wanted:
                con.execute("insert into watchlist_group_members values (?, ?)", [identifier, symbol])
            con.execute("commit")
        except Exception:
            con.execute("rollback")
            raise
        return {"symbol": symbol, "group_ids": sorted(map(str, wanted))}

    @app.post("/api/watchlist/{symbol}/waves")
    def waves(symbol: str, payload: WaveRequest):
        if not con.execute("select 1 from watchlist where symbol = ?", [symbol]).fetchone():
            raise HTTPException(404, "请先将股票加入自选")
        if payload.tree is not None:
            issues = validate_tree(payload.tree)
            if issues:
                raise HTTPException(422, issues[0].message)
            def check(node):
                if isinstance(node, GroupNode):
                    for child in node.children:
                        check(child)
                    return
                from astock.screening.catalog import DEFAULT_CATALOG
                operands = [node] + ([node.right] if isinstance(node.right, MetricOperand) else [])
                for operand in operands:
                    spec = DEFAULT_CATALOG.get(operand.metric)
                    if operand.timeframe != Timeframe.DAY or (spec.group not in {"price", "activity", "technical", "trend"} and operand.metric not in PA_METRICS) or "backtest" not in spec.supported_modes or operand.metric in {"support_distance", "resistance_distance"}:
                        raise HTTPException(422, "历史条件筛选支持日线价格、成交活跃度和技术指标")
            check(payload.tree)
        count = con.execute("select count(*) from market_features where symbol = ? and timeframe = '1d'", [symbol]).fetchone()[0]
        rows = MarketFeatureStore(context.database).read_history(symbol, Timeframe.DAY, datetime.now(SHANGHAI).date(), count, enrich=False, include_vacuum=uses_vacuum(payload.tree), include_shapes=uses_shapes(payload.tree), include_price_action=uses_price_action(payload.tree), include_ma_pierce=uses_ma_pierce(payload.tree))
        return scan_waves(rows, payload)

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

    @app.get("/api/symbols/{symbol}/chart-shapes")
    def chart_shapes(symbol: str, as_of: date):
        from astock.features.chart_shapes import SHAPE_LABELS
        store = MarketFeatureStore(context.database)
        rows = store.read_history(symbol, Timeframe.DAY, as_of, 1, enrich=False, include_shapes=True)
        if not rows:
            return {"marks": [], "data_date": None}
        marks = []
        for metric in SHAPE_LABELS:
            if rows[0].get(metric):
                marks.extend(condition_marks({"kind":"condition","metric":metric,"timeframe":"1d","operator":"eq"},
                                             {"result":"true"}, {Timeframe.DAY:rows}))
        return {"marks":marks,"data_date":str(rows[0]['feature_date'])}

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
        if payload.group_id is not None and not con.execute(
            "select 1 from watchlist_groups where group_id = ?", [payload.group_id]
        ).fetchone():
            raise HTTPException(422, "目标分组不存在，请重新选择")
        con.execute("begin transaction")
        try:
            for symbol in sorted(wanted):
                result = add_watchlist(watch_request(symbol=symbol, run_id=run_id))
                if isinstance(result, Response):
                    con.execute("rollback")
                    return result
                if payload.group_id is not None:
                    con.execute("insert into watchlist_group_members values (?, ?) on conflict do nothing",
                                [payload.group_id, symbol])
            con.execute("commit")
        except Exception:
            con.execute("rollback")
            raise
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
        histories = {timeframe: store.read_history(symbol, timeframe, as_of, 1100, enrich=timeframe.value in enriched_frames, include_vacuum=uses_vacuum(record["tree"]), include_shapes=uses_shapes(record["tree"]), include_price_action=uses_price_action(record["tree"]), include_ma_pierce=uses_ma_pierce(record["tree"])) for timeframe in Timeframe}
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
        from astock.screening.sequoia_confluence import HIT_KEYS, attach_confluence
        for metric in HIT_KEYS:
            if latest and metric in json.dumps(record["tree"]):
                attach_confluence(con, {symbol: histories[Timeframe.DAY]}, as_of, lambda *_: None, metric=metric)
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
