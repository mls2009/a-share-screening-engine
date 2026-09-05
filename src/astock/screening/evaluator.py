from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from astock.domain.market import Timeframe
from astock.screening.catalog import DEFAULT_CATALOG
from astock.screening.models import (
    ConditionNode,
    ConstantOperand,
    GroupLogic,
    MetricOperand,
    Node,
    Operator,
)


class TruthValue(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Evaluation:
    path: str
    result: TruthValue
    actual: Any = None
    expected: Any = None
    unit: str | None = None
    children: tuple["Evaluation", ...] = ()
    reason: str | None = None
    data_time: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "reason": self.reason,
            "data_time": self.data_time,
            "result": self.result.value,
            "actual": self.actual,
            "expected": self.expected,
            "unit": self.unit,
            "children": [child.to_dict() for child in self.children],
        }


def _truth(value: bool) -> TruthValue:
    return TruthValue.TRUE if value else TruthValue.FALSE


def _compare(left: Any, right: Any, operator: Operator) -> TruthValue:
    if left is None or right is None:
        return TruthValue.UNKNOWN
    if operator == Operator.EQ:
        return _truth(right in left if isinstance(left, list) else left == right)
    if operator == Operator.NE:
        return _truth(right not in left if isinstance(left, list) else left != right)
    if operator == Operator.GT:
        return _truth(left > right)
    if operator == Operator.GTE:
        return _truth(left >= right)
    if operator == Operator.LT:
        return _truth(left < right)
    if operator == Operator.LTE:
        return _truth(left <= right)
    if operator == Operator.IN:
        return _truth(
            any(value in right for value in left)
            if isinstance(left, list)
            else left in right
        )
    if operator == Operator.NOT_IN:
        return _truth(
            all(value not in right for value in left)
            if isinstance(left, list)
            else left not in right
        )
    if operator in {Operator.BETWEEN, Operator.NOT_BETWEEN}:
        inside = right[0] <= left <= right[1]
        return _truth(inside if operator == Operator.BETWEEN else not inside)
    raise ValueError(f"operator requires history handling: {operator}")


def _value(history: dict[Timeframe, list[dict]], timeframe: Timeframe, metric: str, index: int) -> Any:
    rows = history.get(timeframe, [])
    return rows[index].get(metric) if index < len(rows) else None


def _row_time(row: dict) -> datetime | None:
    value = row.get("timestamp") or row.get("feature_date")
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value) if len(value) > 10 else date.fromisoformat(value)
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, time(15))
        return value.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if value.tzinfo is None else value
    except (ValueError, TypeError, AttributeError):
        return None


def _right_value(
    node: ConditionNode,
    history: dict[Timeframe, list[dict]],
    index: int,
) -> Any:
    if isinstance(node.right, ConstantOperand):
        return node.right.value
    assert isinstance(node.right, MetricOperand)
    if node.timeframe == node.right.timeframe:
        value = _value(history, node.right.timeframe, node.right.metric, index)
    else:
        left_rows = history.get(node.timeframe, [])
        cutoff = _row_time(left_rows[index]) if index < len(left_rows) else None
        if cutoff is None:
            return None
        available = [
            (stamp, row) for row in history.get(node.right.timeframe, [])
            if (stamp := _row_time(row)) is not None and stamp <= cutoff
        ]
        value = max(available, key=lambda item: item[0])[1].get(node.right.metric) if available else None
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value * node.right.multiplier
    return value if node.right.multiplier == 1 else None


def _evaluate_condition(
    node: ConditionNode,
    history: dict[Timeframe, list[dict]],
    path: str,
) -> Evaluation:
    actual = _value(history, node.timeframe, node.metric, 0)
    expected = _right_value(node, history, 0)
    unit_spec = DEFAULT_CATALOG.get(node.metric)
    unit = unit_spec.unit.value if unit_spec else None

    rows = history.get(node.timeframe, [])
    data_time = str(rows[0].get("timestamp") or rows[0].get("feature_date") or "") if rows else None

    def outcome(result: TruthValue) -> Evaluation:
        reason = None
        if result == TruthValue.UNKNOWN:
            reason = "缺少指标值或历史窗口数据"
            if isinstance(node.right, MetricOperand) and node.right.timeframe != node.timeframe:
                reason = "跨周期缺少时间戳、时点前已可用指标值或历史窗口数据"
        return Evaluation(path, result, actual, expected, unit, reason=reason, data_time=data_time)

    if node.operator in {Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW}:
        previous_actual = _value(history, node.timeframe, node.metric, 1)
        previous_expected = _right_value(node, history, 1)
        if None in {actual, expected, previous_actual, previous_expected}:
            result = TruthValue.UNKNOWN
        elif node.operator == Operator.CROSSES_ABOVE:
            result = _truth(actual > expected and previous_actual <= previous_expected)
        else:
            result = _truth(actual < expected and previous_actual >= previous_expected)
        return outcome(result)

    if node.operator in {Operator.AT_LEAST, Operator.CONTINUOUS}:
        lookback = node.lookback or node.occurrences or 1
        results = [
            _compare(
                _value(history, node.timeframe, node.metric, index),
                _right_value(node, history, index),
                Operator(node.comparison_operator),
            )
            for index in range(lookback)
        ]
        if node.operator == Operator.AT_LEAST:
            required = node.occurrences or 1
            if sum(result == TruthValue.TRUE for result in results) >= required:
                result = TruthValue.TRUE
            elif any(result == TruthValue.UNKNOWN for result in results):
                result = TruthValue.UNKNOWN
            else:
                result = TruthValue.FALSE
        elif all(result == TruthValue.TRUE for result in results):
            result = TruthValue.TRUE
        elif any(result == TruthValue.FALSE for result in results):
            result = TruthValue.FALSE
        else:
            result = TruthValue.UNKNOWN
        return outcome(result)

    return outcome(_compare(actual, expected, node.operator))


def evaluate_tree(
    tree: Node,
    history: dict[Timeframe, list[dict]],
    path: str = "root",
) -> Evaluation:
    if isinstance(tree, ConditionNode):
        return _evaluate_condition(tree, history, path)
    children = tuple(
        evaluate_tree(child, history, f"{path}.children[{index}]")
        for index, child in enumerate(tree.children)
    )
    values = [child.result for child in children]
    if tree.logic == GroupLogic.NOT:
        result = {
            TruthValue.TRUE: TruthValue.FALSE,
            TruthValue.FALSE: TruthValue.TRUE,
            TruthValue.UNKNOWN: TruthValue.UNKNOWN,
        }[values[0]]
    elif tree.logic == GroupLogic.AND:
        if TruthValue.FALSE in values:
            result = TruthValue.FALSE
        elif TruthValue.UNKNOWN in values:
            result = TruthValue.UNKNOWN
        else:
            result = TruthValue.TRUE
    elif TruthValue.TRUE in values:
        result = TruthValue.TRUE
    elif TruthValue.UNKNOWN in values:
        result = TruthValue.UNKNOWN
    else:
        result = TruthValue.FALSE
    return Evaluation(path, result, children=children)
