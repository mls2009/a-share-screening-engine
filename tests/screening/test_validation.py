from astock.screening.models import ConditionNode, GroupNode
from astock.screening.validation import validate_tree


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
