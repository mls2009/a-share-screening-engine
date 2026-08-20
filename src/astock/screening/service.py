import json
from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID, uuid4

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


class ScreenDefinitionError(ValueError):
    def __init__(self, issues: list[ScreenValidationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.path}: {issue.message}" for issue in issues))


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
    def __init__(self, database: Database, feature_store: MarketFeatureStore) -> None:
        self.connection = database.connection
        self.feature_store = feature_store

    def validate(self, tree: Node) -> list[ScreenValidationIssue]:
        return validate_tree(tree)

    def run(
        self,
        tree: Node,
        as_of: date,
        rank: RankSpec | None = None,
        limit: int = 100,
        offset: int = 0,
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
        candidates = []
        for symbol in symbols:
            history = {
                timeframe: self.feature_store.read_history(
                    symbol, timeframe, as_of, history_limit
                )
                for timeframe in timeframes
            }
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
        run_id = self._persist_run(tree, as_of, symbols, matches)
        return ScreenRunResult(
            run_id=run_id,
            universe_size=len(symbols),
            matches=matches[offset : offset + limit],
        )

    def _persist_run(
        self,
        tree: Node,
        as_of: date,
        symbols: list[str],
        matches: list[ScreenMatch],
    ) -> UUID:
        run_id = uuid4()
        tree_json = json.dumps(tree.model_dump(mode="json"), ensure_ascii=False)
        self.connection.execute(
            """
            insert into screen_runs
              (run_id, mode, as_of_date, feature_version, condition_tree,
               universe_size, status, finished_at)
            values (?, 'close', ?, 'v1', ?, ?, 'completed', now())
            """,
            [run_id, as_of, tree_json, len(symbols)],
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
