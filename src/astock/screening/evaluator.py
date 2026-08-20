from dataclasses import dataclass
from enum import StrEnum
from typing import Any

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

    def to_dict(self) -> dict:
        return {
            "path": self.path,
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
        return _truth(left == right)
    if operator == Operator.NE:
        return _truth(left != right)
    if operator == Operator.GT:
        return _truth(left > right)
    if operator == Operator.GTE:
        return _truth(left >= right)
    if operator == Operator.LT:
        return _truth(left < right)
    if operator == Operator.LTE:
        return _truth(left <= right)
    if operator in {Operator.BETWEEN, Operator.NOT_BETWEEN}:
        inside = right[0] <= left <= right[1]
        return _truth(inside if operator == Operator.BETWEEN else not inside)
    raise ValueError(f"operator requires history handling: {operator}")


def _value(history: dict[Timeframe, list[dict]], timeframe: Timeframe, metric: str, index: int) -> Any:
    rows = history.get(timeframe, [])
    return rows[index].get(metric) if index < len(rows) else None


def _right_value(
    node: ConditionNode,
    history: dict[Timeframe, list[dict]],
    index: int,
) -> Any:
    if isinstance(node.right, ConstantOperand):
        return node.right.value
    assert isinstance(node.right, MetricOperand)
    value = _value(history, node.right.timeframe, node.right.metric, index)
    return None if value is None else value * node.right.multiplier


def _evaluate_condition(
    node: ConditionNode,
    history: dict[Timeframe, list[dict]],
    path: str,
) -> Evaluation:
    actual = _value(history, node.timeframe, node.metric, 0)
    expected = _right_value(node, history, 0)
    unit_spec = DEFAULT_CATALOG.get(node.metric)
    unit = unit_spec.unit.value if unit_spec else None

    if node.operator in {Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW}:
        previous_actual = _value(history, node.timeframe, node.metric, 1)
        previous_expected = _right_value(node, history, 1)
        if None in {actual, expected, previous_actual, previous_expected}:
            result = TruthValue.UNKNOWN
        elif node.operator == Operator.CROSSES_ABOVE:
            result = _truth(actual > expected and previous_actual <= previous_expected)
        else:
            result = _truth(actual < expected and previous_actual >= previous_expected)
        return Evaluation(path, result, actual, expected, unit)

    if node.operator in {Operator.AT_LEAST, Operator.CONTINUOUS}:
        lookback = node.lookback or node.occurrences or 1
        results = [
            _compare(
                _value(history, node.timeframe, node.metric, index),
                _right_value(node, history, index),
                Operator.GT,
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
        return Evaluation(path, result, actual, expected, unit)

    return Evaluation(path, _compare(actual, expected, node.operator), actual, expected, unit)


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
