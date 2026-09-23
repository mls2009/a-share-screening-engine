import pytest
from pydantic import TypeAdapter, ValidationError

from astock.screening.models import ConditionNode, GroupNode, Node


def test_condition_tree_parses_nested_and_or_not_json() -> None:
    payload = {
        "kind": "group",
        "logic": "and",
        "children": [
            {
                "kind": "condition",
                "metric": "return_20",
                "timeframe": "1d",
                "operator": "gte",
                "right": {"kind": "constant", "value": 30, "unit": "percent"},
            },
            {
                "kind": "group",
                "logic": "not",
                "children": [
                    {
                        "kind": "condition",
                        "metric": "is_st",
                        "timeframe": "1d",
                        "operator": "eq",
                        "right": {
                            "kind": "constant",
                            "value": True,
                            "unit": "boolean",
                        },
                    }
                ],
            },
        ],
    }

    tree = TypeAdapter(Node).validate_python(payload)

    assert isinstance(tree, GroupNode)
    assert isinstance(tree.children[0], ConditionNode)
    assert tree.children[0].right.value == 30
    assert tree.children[1].logic == "not"


def test_not_group_requires_exactly_one_child() -> None:
    with pytest.raises(ValidationError):
        GroupNode(kind="group", logic="not", children=[])


def test_metric_operand_supports_safe_multiplier_without_formula() -> None:
    condition = ConditionNode.model_validate(
        {
            "kind": "condition",
            "metric": "volume",
            "timeframe": "1d",
            "operator": "gt",
            "right": {
                "kind": "metric",
                "metric": "volume_ma_20",
                "timeframe": "1d",
                "multiplier": 1.5,
            },
        }
    )

    assert condition.right.multiplier == 1.5


def test_catalog_declares_supported_execution_modes() -> None:
    from astock.screening.catalog import DEFAULT_CATALOG

    assert "backtest" in DEFAULT_CATALOG.get("return_10_max_60").supported_modes
    assert "backtest" in DEFAULT_CATALOG.get("rsi_14").supported_modes
    assert "backtest" not in DEFAULT_CATALOG.get("total_market_cap").supported_modes
    assert "live" not in DEFAULT_CATALOG.get("rsi_14").supported_modes
    assert "live" in DEFAULT_CATALOG.get("ma_20").supported_modes
