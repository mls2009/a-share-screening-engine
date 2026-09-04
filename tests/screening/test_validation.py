from astock.screening.models import ConditionNode, GroupNode
from astock.screening.validation import validate_tree


def test_catalog_contains_extended_price_volume_pattern_and_risk_metrics() -> None:
    from astock.screening.catalog import DEFAULT_CATALOG

    keys = {metric.key for metric in DEFAULT_CATALOG.all()}

    assert {
        "high_20",
        "high_history",
        "low_250",
        "low_history",
        "max_drawdown_60",
        "up_streak",
        "down_streak",
        "pattern_type",
        "support_distance",
        "resistance_distance",
        "limit_up_count_5_max_60",
        "limit_up_burst_5_count_60",
        "return_10_max_60",
        "ma_10_slope_abs_5",
        "ma_20_slope_abs_5",
        "ma_10_range_5",
        "ma_20_range_5",
        "ma_10_20_distance",
    } <= keys


def test_technical_metrics_support_all_chart_and_backtest_timeframes() -> None:
    from astock.domain.market import Timeframe
    from astock.screening.catalog import DEFAULT_CATALOG

    expected = set(Timeframe)

    assert DEFAULT_CATALOG.get("return_20") is not None
    assert set(DEFAULT_CATALOG.get("return_20").timeframes) == expected
    assert set(DEFAULT_CATALOG.get("volume_change_5").timeframes) == expected
    assert set(DEFAULT_CATALOG.get("ma_20").timeframes) == expected
    assert set(DEFAULT_CATALOG.get("rsi_14").timeframes) == expected
    assert set(DEFAULT_CATALOG.get("support_distance").timeframes) != expected


def test_validates_known_metric_operator_timeframe_and_unit() -> None:
    tree = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "return_20",
            "timeframe": "1d",
            "operator": "gte",
            "right": {"kind": "constant", "value": 30, "unit": "percent"},
        }
    )

    assert validate_tree(tree) == []


def test_validation_errors_include_exact_node_path() -> None:
    tree = GroupNode.model_validate(
        {
            "kind": "group",
            "logic": "and",
            "children": [
                {
                    "kind": "condition",
                    "metric": "imaginary_metric",
                    "timeframe": "1d",
                    "operator": "gte",
                    "right": {"kind": "constant", "value": 1, "unit": "percent"},
                }
            ],
        }
    )

    errors = validate_tree(tree)

    assert errors[0].path == "root.children[0]"
    assert errors[0].code == "unknown_metric"


def test_rejects_incompatible_units_and_metric_comparisons() -> None:
    wrong_constant = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "close",
            "timeframe": "1d",
            "operator": "gt",
            "right": {"kind": "constant", "value": 10, "unit": "percent"},
        }
    )
    wrong_metric = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "volume",
            "timeframe": "1d",
            "operator": "gt",
            "right": {
                "kind": "metric",
                "metric": "close",
                "timeframe": "1d",
                "multiplier": 1,
            },
        }
    )

    assert validate_tree(wrong_constant)[0].code == "unit_mismatch"
    assert validate_tree(wrong_metric)[0].code == "unit_mismatch"


def test_rejects_between_with_a_single_metric_operand() -> None:
    condition = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "close",
            "timeframe": "1d",
            "operator": "between",
            "right": {
                "kind": "metric",
                "metric": "ma_20",
                "timeframe": "1d",
                "multiplier": 1,
            },
        }
    )

    assert validate_tree(condition)[0].code == "invalid_range"


def test_rejects_tree_deeper_than_safety_limit() -> None:
    tree: dict = {
        "kind": "condition",
        "metric": "close",
        "timeframe": "1d",
        "operator": "gt",
        "right": {"kind": "constant", "value": 1, "unit": "price"},
    }
    for _ in range(33):
        tree = {"kind": "group", "logic": "not", "children": [tree]}

    parsed = GroupNode.model_validate(tree)
    errors = validate_tree(parsed)

    assert errors[0].code == "tree_too_deep"


def test_accepts_realtime_turnover_volume_ratio_and_market_cap_metrics() -> None:
    payloads = [
        ("turnover_rate", "percent"),
        ("volume_ratio", "ratio"),
        ("total_market_cap", "amount"),
        ("float_market_cap", "amount"),
    ]

    for metric, unit in payloads:
        condition = ConditionNode.model_validate(
            {
                "kind": "condition",
                "metric": metric,
                "timeframe": "1d",
                "operator": "gt",
                "right": {"kind": "constant", "value": 1, "unit": unit},
            }
        )
        assert validate_tree(condition) == []


def test_membership_requires_a_non_empty_category_list() -> None:
    valid = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "board",
            "timeframe": "1d",
            "operator": "in",
            "right": {
                "kind": "constant",
                "value": ["main", "chinext"],
                "unit": "category",
            },
        }
    )
    empty = valid.model_copy(
        update={
            "right": valid.right.model_copy(update={"value": []}),
        }
    )

    assert validate_tree(valid) == []
    assert validate_tree(empty)[0].code == "invalid_membership"


def test_category_membership_rejects_metric_operand_but_keeps_legacy_equality() -> None:
    membership_metric = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "board",
            "timeframe": "1d",
            "operator": "in",
            "right": {
                "kind": "metric",
                "metric": "pattern_type",
                "timeframe": "1d",
            },
        }
    )
    legacy = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "board",
            "timeframe": "1d",
            "operator": "eq",
            "right": {"kind": "constant", "value": "main", "unit": "category"},
        }
    )

    assert validate_tree(membership_metric)[0].code == "invalid_membership"
    assert validate_tree(legacy) == []


def test_numeric_range_rejects_strings_non_finite_values_and_reverse_order() -> None:
    def condition(value: list[object]) -> ConditionNode:
        return ConditionNode.model_validate(
            {
                "kind": "condition",
                "metric": "return_20",
                "timeframe": "1d",
                "operator": "between",
                "right": {"kind": "constant", "value": value, "unit": "percent"},
            }
        )

    assert validate_tree(condition(["low", "high"]))[0].code == "invalid_range"
    assert validate_tree(condition([10, float("inf")]))[0].code == "invalid_range"
    assert validate_tree(condition([30, 10]))[0].code == "invalid_range"
