import json
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID, uuid4

from astock.data.providers.tencent import SnapshotBatchResult
from astock.data.snapshots import overlay_snapshot
from astock.domain.market import Timeframe
from astock.features.store import MarketFeatureStore
from astock.screening.evaluator import Evaluation, TruthValue, evaluate_tree
from astock.screening.models import ConditionNode, GroupNode, MetricOperand, Node
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
    matches: list[ScreenMatch]
    status: str = "completed"
    realtime_covered: int = 0
    failed_batches: int = 0


class ScreenDefinitionError(ValueError):
    def __init__(self, issues: list[ScreenValidationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in issues))


class SnapshotProvider:
    def snapshot_many(self, symbols: list[str]) -> SnapshotBatchResult: ...


def _requirements(tree: Node) -> tuple[set[Timeframe], int]:
    timeframes: set[Timeframe] = set()
    limit = 2

    def visit(node: ConditionNode | GroupNode) -> None:
        nonlocal limit
        if isinstance(node, GroupNode):
            for child in node.children:
                visit(child)
            return
        timeframes.add(node.timeframe)
        if isinstance(node.right, MetricOperand):
            timeframes.add(node.right.timeframe)
        limit = max(limit, node.lookback or 1, node.occurrences or 1)

    visit(tree)
    return timeframes, limit


class ScreeningService:
    def __init__(
        self,
        database: Database,
        feature_store: MarketFeatureStore,
        snapshot_provider: SnapshotProvider | None = None,
    ) -> None:
        self.connection = database.connection
        self.feature_store = feature_store
        self.snapshot_provider = snapshot_provider

    def validate(self, tree: Node) -> list[ScreenValidationIssue]:
        return validate_tree(tree)

    def results(self, run_id: UUID, limit: int = 100, offset: int = 0) -> list[dict]:
        cursor = self.connection.execute(
            """
            select symbol, match_rank, feature_snapshot, explanation
            from screen_matches where run_id = ?
            order by match_rank limit ? offset ?
            """,
            [run_id, limit, offset],
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
    ) -> ScreenRunResult:
        issues = self.validate(tree)
        if issues:
            raise ScreenDefinitionError(issues)
        symbols = [
            row[0]
            for row in self.connection.execute(
                "select symbol from symbols where is_listed order by symbol"
            ).fetchall()
        ]
        timeframes, history_limit = _requirements(tree)
        batch = SnapshotBatchResult((), len(symbols), 0)
        if mode == "live":
            if self.snapshot_provider is None:
                raise RuntimeError("live screening requires a snapshot provider")
            batch = self.snapshot_provider.snapshot_many(symbols)
            history_limit = max(history_limit, 250)
            timeframes.add(Timeframe.DAY)
        snapshots = {snapshot.symbol: snapshot for snapshot in batch.snapshots}
        candidates = []
        for symbol in symbols:
            history = {
                timeframe: self.feature_store.read_history(
                    symbol, timeframe, as_of, history_limit
                )
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
            explanation = evaluate_tree(tree, history)
            if explanation.result != TruthValue.TRUE:
                continue
            snapshot = history.get(Timeframe.DAY, [{}])[0] if history.get(Timeframe.DAY) else {}
            rank_value = None
            if rank is not None:
                rank_rows = history.get(rank.timeframe)
                if rank_rows is None:
                    rank_rows = self.feature_store.read_history(
                        symbol, rank.timeframe, as_of, 1
                    )
                rank_value = rank_rows[0].get(rank.metric) if rank_rows else None
            candidates.append((symbol, snapshot, explanation, rank_value))

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
        run_id = self._persist_run(tree, as_of, symbols, matches, mode, batch)
        return ScreenRunResult(
            run_id=run_id,
            universe_size=len(symbols),
            matches=matches[offset : offset + limit],
            realtime_covered=len(batch.snapshots),
            failed_batches=batch.failed_batches,
        )

    def _persist_run(
        self,
        tree: Node,
        as_of: date,
        symbols: list[str],
        matches: list[ScreenMatch],
        mode: Literal["close", "live"],
        batch: SnapshotBatchResult,
    ) -> UUID:
        run_id = uuid4()
        tree_json = json.dumps(tree.model_dump(mode="json"), ensure_ascii=False)
        self.connection.execute(
            """
            insert into screen_runs
              (run_id, mode, as_of_date, feature_version, condition_tree,
               universe_size, realtime_covered, failed_batches, status, snapshot, finished_at)
            values (?, ?, ?, 'v1', ?, ?, ?, ?, 'completed', ?, now())
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
