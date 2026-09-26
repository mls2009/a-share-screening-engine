import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal
from uuid import UUID, uuid4

from astock.data.providers.tencent import SnapshotBatchResult
from astock.data.sectors import SECTOR_KEYS, SectorStore
from astock.data.snapshots import overlay_snapshot
from astock.domain.market import Timeframe
from astock.features.chart_shapes import SHAPE_LABELS
from astock.features.ma250_reclaim import MA250_RECLAIM_METRICS
from astock.features.ma_support import MA_SUPPORT_METRIC
from astock.features.ma_pierce import MA_PIERCE_METRICS
from astock.features.price_action import PA_METRICS
from astock.features.store import MarketFeatureStore
from astock.features.vacuum import VACUUM_METRICS
from astock.screening.catalog import DEFAULT_CATALOG
from astock.screening.evaluator import Evaluation, TruthValue, evaluate_tree
from astock.screening.models import ConditionNode, GroupNode, MetricOperand, Node, Operator
from astock.screening.sequoia_confluence import HIT_KEYS as SEQUOIA_METRICS
from astock.screening.sequoia_confluence import attach_confluence
from astock.screening.validation import ScreenValidationIssue, validate_tree
from astock.storage.database import Database


@dataclass(frozen=True)
class RankSpec:
    metric: str
    direction: Literal["asc", "desc"] = "desc"
    timeframe: Timeframe = Timeframe.DAY


@dataclass(frozen=True)
class ScreenMatch:
    symbol: str
    rank: int
    features: dict
    explanation: Evaluation


@dataclass(frozen=True)
class ScreenRunResult:
    run_id: UUID
    universe_size: int
    match_count: int
    matches: list[ScreenMatch]
    status: str = "completed"
    realtime_covered: int = 0
    failed_batches: int = 0
    diagnostics: dict = field(default_factory=dict)


class ScreenDefinitionError(ValueError):
    def __init__(self, issues: list[ScreenValidationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in issues))


class SnapshotProvider:
    def snapshot_many(self, symbols: list[str]) -> SnapshotBatchResult: ...


ENRICHED_METRICS = {
    "board",
    "is_st",
    "is_suspended",
    "pattern_type",
    "pattern_strength",
    "support_distance",
    "resistance_distance",
}


def _live_history_limit(metrics: set[str]) -> int:
    limit = 1
    for metric in metrics:
        if metric == "volume_ratio_20":
            limit = max(limit, 20)
            continue
        if metric.startswith(("return_", "ma_", "volume_ma_")):
            suffix = metric.rsplit("_", 1)[-1]
            if suffix.isdigit():
                limit = max(limit, int(suffix))
    return limit


def _requirements(tree: Node) -> tuple[set[Timeframe], int, set[str]]:
    timeframes: set[Timeframe] = set()
    metrics: set[str] = set()
    limit = 1

    def visit(node: ConditionNode | GroupNode) -> None:
        nonlocal limit
        if isinstance(node, GroupNode):
            for child in node.children:
                visit(child)
            return
        timeframes.add(node.timeframe)
        metrics.add(node.metric)
        if isinstance(node.right, MetricOperand):
            timeframes.add(node.right.timeframe)
            metrics.add(node.right.metric)
        if node.operator in {Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW}:
            limit = max(limit, 2)
        limit = max(limit, node.lookback or 1, node.occurrences or 1)

    visit(tree)
    return timeframes, limit, metrics


class ScreeningService:
    def __init__(
        self,
        database: Database,
        feature_store: MarketFeatureStore,
        snapshot_provider: SnapshotProvider | None = None,
    ) -> None:
        self.connection = database.connection
        self.database = database
        self.feature_store = feature_store
        self.snapshot_provider = snapshot_provider

    def validate(self, tree: Node) -> list[ScreenValidationIssue]:
        return validate_tree(tree)

    def results(
        self,
        run_id: UUID,
        limit: int = 100,
        offset: int = 0,
        sort_by: str | None = None,
        sort_direction: Literal["asc", "desc"] | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict]:
        metric_sort = None
        if sort_by and ":" in sort_by:
            timeframe_key, metric_key = sort_by.split(":", 1)
            if timeframe_key in {item.value for item in Timeframe} and DEFAULT_CATALOG.get(metric_key):
                spec = DEFAULT_CATALOG.get(metric_key)
                metric_sort = f"json_extract_string(feature_snapshot, '$.metric_values.\"{sort_by}\"')" if spec.unit.value in {"category", "boolean"} else f"try_cast(json_extract(feature_snapshot, '$.metric_values.\"{sort_by}\"') as double)"
        order_by = {
            "rank": "match_rank",
            "symbol": "coalesce(json_extract_string(feature_snapshot, '$.name'), symbol)",
            "close": "try_cast(json_extract(feature_snapshot, '$.close') as double)",
            "return_20": "try_cast(json_extract(feature_snapshot, '$.return_20') as double)",
            "volume_ratio_20": "try_cast(json_extract(feature_snapshot, '$.volume_ratio_20') as double)",
        }.get(sort_by or "", metric_sort or "match_rank")
        direction = "desc" if sort_by is not None and sort_direction == "desc" else "asc"
        cursor = self.connection.execute(
            f"""
            select symbol, match_rank, feature_snapshot, explanation
            from screen_matches where run_id = ?
              {"and symbol in (select unnest(?::varchar[]))" if symbols is not None else ""}
            order by {order_by} {direction} nulls last, match_rank asc limit ? offset ?
            """,
            [run_id, *([symbols] if symbols is not None else []), limit, offset],
        )
        return [
            {
                "symbol": row[0],
                "rank": row[1],
                "features": json.loads(row[2]),
                "explanation": json.loads(row[3]),
            }
            for row in cursor.fetchall()
        ]

    def run(
        self,
        tree: Node,
        as_of: date,
        rank: RankSpec | None = None,
        limit: int = 100,
        offset: int = 0,
        mode: Literal["close", "live"] = "close",
        scope_symbols: list[str] | None = None,
        scope_metadata: dict | None = None,
        extra_timeframes: list[Timeframe] | None = None,
        extra_columns: list[str] | None = None,
        progress=None,
    ) -> ScreenRunResult:
        report = progress or (lambda *args: None)
        report(2, "校验筛选条件")
        issues = self.validate(tree)
        if issues:
            raise ScreenDefinitionError(issues)
        securities = self.connection.execute(
            "select symbol, name, board, is_listed, listed_on, delisted_on from symbols order by symbol"
        ).fetchall()
        symbols = []
        allowed = set(scope_symbols) if scope_symbols is not None else None
        uncertain = 0
        for symbol, _, _, is_listed, listed_on, delisted_on in securities:
            if allowed is not None and symbol not in allowed:
                continue
            if listed_on is None or (not is_listed and delisted_on is None):
                uncertain += 1
            if listed_on is not None and listed_on > as_of:
                continue
            if delisted_on is not None and as_of >= delisted_on:
                continue
            if not is_listed and delisted_on is None:
                continue
            symbols.append(symbol)
        diagnostics = {"conditions": {}, "warnings": [], "data_dates": {}, "scope": scope_metadata or {"scope": "market"}}
        if uncertain:
            diagnostics["warnings"].append(
                f"{uncertain} 只股票缺少上市或退市日期；兼容当前在市记录，退市日期未知者保守排除。"
            )
        timeframes, history_limit, metrics = _requirements(tree)
        if mode == "live" and metrics & SEQUOIA_METRICS.keys():
            raise ScreenDefinitionError([ScreenValidationIssue(
                "requires_close_mode", "Sequoia同日共振需使用已完成日线", "root",
            )])
        if mode == "live" and metrics & VACUUM_METRICS:
            raise ScreenDefinitionError([ScreenValidationIssue(
                "requires_close_mode", "真空区条件需使用收盘模式，不能用未收盘行情确认重新进入", "root",
            )])
        if mode == "live" and metrics & (PA_METRICS | SHAPE_LABELS.keys()):
            raise ScreenDefinitionError([ScreenValidationIssue(
                "requires_close_mode", "裸K形态需使用收盘模式，以已完成日线确认", "root",
            )])
        if mode == "live" and metrics & MA_PIERCE_METRICS:
            raise ScreenDefinitionError([ScreenValidationIssue(
                "requires_close_mode", "均线穿线条件需使用收盘模式，以已完成日线确认", "root",
            )])
        current_only = [DEFAULT_CATALOG.get(key) for key in metrics
                        if DEFAULT_CATALOG.get(key).supported_modes == frozenset({"live"})]
        if mode != "live" and current_only:
            raise ScreenDefinitionError([ScreenValidationIssue(
                "requires_live_mode", "、".join(spec.label for spec in current_only) + "需要选择实时行情模式；当前估值不能替代历史数据", "root",
            )])
        sector_values = SectorStore(self.database).values()
        if metrics & SECTOR_KEYS.keys():
            diagnostics["warnings"].append("东方财富行业/概念按当前成分名单筛选，不代表数据日期当时的归属；历史回测不支持此类条件。")
        timeframes.update(extra_timeframes or [])
        for column in extra_columns or []:
            frame, _, key = column.partition(":")
            if frame in {item.value for item in Timeframe} and DEFAULT_CATALOG.get(key):
                timeframes.add(Timeframe(frame))
                metrics.add(key)
        batch = SnapshotBatchResult((), len(symbols), 0)
        if mode == "live":
            if self.snapshot_provider is None:
                raise RuntimeError("live screening requires a snapshot provider")
            batch = self.snapshot_provider.snapshot_many(symbols)
            batch = SnapshotBatchResult(
                tuple(snapshot for snapshot in batch.snapshots if snapshot.timestamp.date() == as_of),
                batch.requested,
                batch.failed_batches,
            )
            history_limit = max(history_limit, _live_history_limit(metrics))
            timeframes.add(Timeframe.DAY)
        if rank is not None:
            timeframes.add(rank.timeframe)
        timeframes.add(Timeframe.DAY)
        snapshots = {snapshot.symbol: snapshot for snapshot in batch.snapshots}
        report(10, "读取历史行情并计算所需指标", 0, len(symbols))
        enrich = bool(metrics & ENRICHED_METRICS)
        histories = {
            timeframe: self.feature_store.read_histories(
                symbols,
                timeframe,
                as_of - timedelta(days=1) if mode == "live" else as_of,
                history_limit,
                enrich=enrich,
                include_vacuum=bool(metrics & VACUUM_METRICS),
                include_price_action=bool(metrics & PA_METRICS),
                include_shapes=bool(metrics & SHAPE_LABELS.keys()),
                include_ma_pierce=bool(metrics & MA_PIERCE_METRICS),
                include_ma_support=MA_SUPPORT_METRIC in metrics,
                include_ma250_reclaim=bool(MA250_RECLAIM_METRICS & metrics),
                progress=lambda message, done, total: report(10 + int(50*done/max(1,total)), message, done, total),
            )
            for timeframe in timeframes
        }
        # Load the right series through the earliest left observation, plus its predecessor.
        def conditions(node):
            if isinstance(node, ConditionNode):
                yield node
            else:
                for child in node.children:
                    yield from conditions(child)

        for condition in conditions(tree):
            if not isinstance(condition.right, MetricOperand) or condition.timeframe == condition.right.timeframe:
                continue
            dates = [row["feature_date"] for rows in histories[condition.timeframe].values()
                     for row in rows if row.get("feature_date") is not None]
            if not dates:
                continue
            right_timeframe = condition.right.timeframe
            end = as_of - timedelta(days=1) if mode == "live" else as_of
            count = self.connection.execute(
                """select coalesce(max(n), 0) + 1 from (
                    select count(*) as n from market_features
                    where symbol in (select unnest(?)) and timeframe = ?
                      and feature_version = 'v1' and feature_date >= ? and feature_date <= ?
                    group by symbol)""", [symbols, right_timeframe.value, min(dates), end]
            ).fetchone()[0]
            histories[right_timeframe] = self.feature_store.read_histories(
                symbols, right_timeframe, end, max(history_limit, count), enrich=enrich,
                include_vacuum=bool(metrics & VACUUM_METRICS),
                include_price_action=bool(metrics & PA_METRICS),
                include_shapes=bool(metrics & SHAPE_LABELS.keys()),
                include_ma_pierce=bool(metrics & MA_PIERCE_METRICS),
                include_ma_support=MA_SUPPORT_METRIC in metrics,
                include_ma250_reclaim=bool(MA250_RECLAIM_METRICS & metrics),
                progress=lambda message, done, total: report(10 + int(50*done/max(1,total)), message, done, total),
            )
        for metric in sorted(metrics & SEQUOIA_METRICS.keys()):
            attach_confluence(self.connection, histories[Timeframe.DAY], as_of,
                              lambda percent, message: report(60 + int(percent * .3), message, 0, len(symbols)), metric=metric)
        identities = {row[0]: {"name": row[1], "board": row[2]} for row in securities if row[0] in symbols}

        def record(evaluation, symbol):
            if evaluation.children:
                for child in evaluation.children:
                    record(child, symbol)
                return
            counts = diagnostics["conditions"].setdefault(
                evaluation.path, {"true": 0, "false": 0, "unknown": 0, "reasons": {}, "unknown_symbols": []}
            )
            counts[evaluation.result.value] += 1
            if evaluation.result == TruthValue.UNKNOWN:
                counts["unknown_symbols"].append({"symbol": symbol, "name": identities.get(symbol, {}).get("name", symbol), "reason": evaluation.reason or "缺少指标数据"})
            if evaluation.reason:
                counts["reasons"][evaluation.reason] = counts["reasons"].get(evaluation.reason, 0) + 1

        candidates = []
        evaluation_start = 90 if metrics & SEQUOIA_METRICS.keys() else 65
        report(evaluation_start, "逐股判断筛选条件", 0, len(symbols))
        for index, symbol in enumerate(symbols):
            if index % 50 == 0:
                report(evaluation_start + int((95 - evaluation_start) * index / max(1, len(symbols))), "逐股判断筛选条件", index, len(symbols))
            history = {
                timeframe: histories[timeframe].get(symbol, [])
                for timeframe in timeframes
            }
            if mode == "live":
                snapshot = snapshots.get(symbol)
                if snapshot is None:
                    history[Timeframe.DAY] = [{}, *history[Timeframe.DAY]]
                else:
                    history[Timeframe.DAY] = overlay_snapshot(
                        history[Timeframe.DAY], snapshot
                    )
            for timeframe, rows in history.items():
                if rows:
                    rows[0].update(sector_values.get(symbol, {}))
                stamp = str(rows[0].get("timestamp") or rows[0].get("feature_date") or "") if rows else ""
                dates = diagnostics["data_dates"].setdefault(timeframe.value, {"oldest": None, "latest": None})
                if stamp:
                    dates["oldest"] = min(dates["oldest"] or stamp, stamp)
                    dates["latest"] = max(dates["latest"] or stamp, stamp)
            explanation = evaluate_tree(tree, history)
            record(explanation, symbol)
            if explanation.result != TruthValue.TRUE:
                continue
            snapshot = dict(history.get(Timeframe.DAY, [{}])[0]) if history.get(Timeframe.DAY) else {}
            snapshot["metric_values"] = {f"{timeframe.value}:{key}": value
                                         for timeframe, rows in history.items() if rows
                                         for key, value in rows[0].items()
                                         if DEFAULT_CATALOG.get(key)}
            snapshot.update({key: value for key, value in identities.get(symbol, {}).items() if key not in snapshot})
            rank_value = None
            if rank is not None:
                rank_rows = history.get(rank.timeframe)
                if rank_rows is None:
                    rank_rows = histories[rank.timeframe].get(symbol, [])
                rank_value = rank_rows[0].get(rank.metric) if rank_rows else None
            candidates.append((symbol, snapshot, explanation, rank_value))

        report(95, "整理筛选结果", len(symbols), len(symbols))
        if rank is not None:
            missing = float("-inf") if rank.direction == "desc" else float("inf")
            candidates.sort(
                key=lambda item: item[3] if item[3] is not None else missing,
                reverse=rank.direction == "desc",
            )
        matches = [
            ScreenMatch(symbol, index + 1, snapshot, explanation)
            for index, (symbol, snapshot, explanation, _) in enumerate(candidates)
        ]
        report(98, "保存结果与入选依据", len(symbols), len(symbols))
        run_id = self._persist_run(tree, as_of, symbols, matches, mode, batch, diagnostics)
        return ScreenRunResult(
            run_id=run_id,
            universe_size=len(symbols),
            match_count=len(matches),
            matches=matches[offset : offset + limit],
            realtime_covered=len(batch.snapshots),
            failed_batches=batch.failed_batches,
            diagnostics=diagnostics,
        )

    def _persist_run(
        self,
        tree: Node,
        as_of: date,
        symbols: list[str],
        matches: list[ScreenMatch],
        mode: Literal["close", "live"],
        batch: SnapshotBatchResult,
        diagnostics: dict,
    ) -> UUID:
        run_id = uuid4()
        tree_json = json.dumps(tree.model_dump(mode="json"), ensure_ascii=False)
        self.connection.execute(
            """
            insert into screen_runs
              (run_id, mode, as_of_date, feature_version, condition_tree,
               universe_size, realtime_covered, failed_batches, status, snapshot, diagnostics, finished_at)
            values (?, ?, ?, 'v1', ?, ?, ?, ?, 'completed', ?, ?, now())
            """,
            [
                run_id,
                mode,
                as_of,
                tree_json,
                len(symbols),
                len(batch.snapshots),
                batch.failed_batches,
                json.dumps(
                    [snapshot.model_dump(mode="json") for snapshot in batch.snapshots],
                    ensure_ascii=False,
                ),
                json.dumps(diagnostics, ensure_ascii=False),
            ],
        )
        if matches:
            self.connection.executemany(
                """
                insert into screen_matches
                  (run_id, symbol, match_rank, feature_snapshot, explanation)
                values (?, ?, ?, ?, ?)
                """,
                [
                    [
                        run_id,
                        match.symbol,
                        match.rank,
                        json.dumps(match.features, ensure_ascii=False, default=str),
                        json.dumps(match.explanation.to_dict(), ensure_ascii=False),
                    ]
                    for match in matches
                ],
            )
        return run_id
