from astock.domain.market import Timeframe
from astock.screening.evaluator import TruthValue, evaluate_tree
from astock.screening.models import ConditionNode, GroupNode


def _condition(**updates: object) -> ConditionNode:
    payload = {
        "kind": "condition",
        "metric": "return_20",
        "timeframe": "1d",
        "operator": "gte",
        "right": {"kind": "constant", "value": 30, "unit": "percent"},
    }
    payload.update(updates)
    return ConditionNode.model_validate(payload)


def test_evaluates_constant_and_metric_multiplier_comparisons() -> None:
    history = {
        Timeframe.DAY: [
            {"return_20": 35.0, "volume": 180.0, "volume_ma_20": 100.0}
        ]
    }
    return_result = evaluate_tree(_condition(), history)
    volume_result = evaluate_tree(
        _condition(
            metric="volume",
            operator="gt",
            right={
                "kind": "metric",
                "metric": "volume_ma_20",
                "timeframe": "1d",
                "multiplier": 1.5,
            },
        ),
        history,
    )

    assert return_result.result == TruthValue.TRUE
    assert return_result.actual == 35.0
    assert volume_result.result == TruthValue.TRUE
    assert volume_result.expected == 150.0


def test_missing_value_is_unknown_and_propagates_through_boolean_groups() -> None:
    unknown = _condition(metric="return_60")
    false = _condition(right={"kind": "constant", "value": 50, "unit": "percent"})
    tree = GroupNode(kind="group", logic="and", children=[unknown, false])

    result = evaluate_tree(tree, {Timeframe.DAY: [{"return_20": 35.0}]})

    assert result.result == TruthValue.FALSE
    assert result.children[0].result == TruthValue.UNKNOWN


def test_evaluates_cross_and_recent_occurrence_operators() -> None:
    history = {
        Timeframe.DAY: [
            {"close": 11.0, "ma_20": 10.0, "return_1": 2.0},
            {"close": 9.0, "ma_20": 10.0, "return_1": -1.0},
            {"close": 8.0, "ma_20": 9.0, "return_1": 3.0},
        ]
    }
    cross = _condition(
        metric="close",
        operator="crosses_above",
        right={"kind": "metric", "metric": "ma_20", "timeframe": "1d"},
    )
    recent = _condition(
        metric="return_1",
        operator="at_least",
        right={"kind": "constant", "value": 0, "unit": "percent"},
        lookback=3,
        occurrences=2,
    )

    assert evaluate_tree(cross, history).result == TruthValue.TRUE
    assert evaluate_tree(recent, history).result == TruthValue.TRUE
