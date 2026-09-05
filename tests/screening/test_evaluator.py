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


def test_evaluates_category_membership_and_exclusion() -> None:
    history = {Timeframe.DAY: [{"board": "chinext", "pattern_type": "hammer"}]}
    board = _condition(
        metric="board",
        operator="in",
        right={
            "kind": "constant",
            "value": ["main", "chinext"],
            "unit": "category",
        },
    )
    pattern = _condition(
        metric="pattern_type",
        operator="not_in",
        right={
            "kind": "constant",
            "value": ["morning_star", "bullish_engulfing"],
            "unit": "category",
        },
    )

    assert evaluate_tree(board, history).result == TruthValue.TRUE
    assert evaluate_tree(pattern, history).result == TruthValue.TRUE


def test_membership_and_legacy_equality_match_any_detected_pattern() -> None:
    history = {
        Timeframe.DAY: [
            {"pattern_type": ["doji", "hammer"], "board": "main"}
        ]
    }
    membership = _condition(
        metric="pattern_type",
        operator="in",
        right={"kind": "constant", "value": ["hammer"], "unit": "category"},
    )
    legacy = _condition(
        metric="pattern_type",
        operator="eq",
        right={"kind": "constant", "value": "hammer", "unit": "category"},
    )

    assert evaluate_tree(membership, history).result == TruthValue.TRUE
    assert evaluate_tree(legacy, history).result == TruthValue.TRUE


def test_cross_timeframe_uses_each_left_date_without_future_values() -> None:
    node = _condition(metric="close", operator="crosses_above", right={
        "kind": "metric", "metric": "ma_20", "timeframe": "1w",
    })
    history = {
        Timeframe.DAY: [{"feature_date": "2026-08-20", "close": 11},
                        {"feature_date": "2026-08-19", "close": 9}],
        Timeframe.WEEK: [{"feature_date": "2026-08-21", "ma_20": 100},
                         {"feature_date": "2026-08-14", "ma_20": 10}],
    }
    assert evaluate_tree(node, history).result == TruthValue.TRUE
    history[Timeframe.DAY] = [{"close": 11}, {"close": 9}]
    assert evaluate_tree(node, history).result == TruthValue.UNKNOWN


def test_recent_window_supports_less_than_comparison() -> None:
    node = _condition(operator="at_least", comparison_operator="lt", lookback=3,
                      occurrences=2, right={"kind": "constant", "value": 0, "unit": "percent"})
    result = evaluate_tree(node, {Timeframe.DAY: [
        {"return_20": -1}, {"return_20": 2}, {"return_20": -3},
    ]})
    assert result.result == TruthValue.TRUE


def test_unknown_explanation_includes_reason_and_data_time() -> None:
    result = evaluate_tree(_condition(), {Timeframe.DAY: [{"feature_date": "2026-08-20"}]})
    assert result.to_dict()["reason"]
    assert result.to_dict()["data_time"] == "2026-08-20"
