from dataclasses import dataclass

from astock.screening.catalog import DEFAULT_CATALOG, MetricCatalog
from astock.screening.models import ConditionNode, ConstantOperand, GroupNode, MetricOperand, Node


@dataclass(frozen=True)
class ScreenValidationIssue:
    code: str
    message: str
    path: str


def validate_tree(
    tree: Node,
    catalog: MetricCatalog = DEFAULT_CATALOG,
    max_depth: int = 32,
    max_nodes: int = 512,
) -> list[ScreenValidationIssue]:
    issues: list[ScreenValidationIssue] = []
    node_count = 0

    def issue(code: str, message: str, path: str) -> None:
        issues.append(ScreenValidationIssue(code, message, path))

    def visit(node: ConditionNode | GroupNode, path: str, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if depth > max_depth:
            if not any(item.code == "tree_too_deep" for item in issues):
                issue("tree_too_deep", f"condition tree exceeds depth {max_depth}", path)
            return
        if isinstance(node, GroupNode):
            for index, child in enumerate(node.children):
                visit(child, f"{path}.children[{index}]", depth + 1)
            return

        left = catalog.get(node.metric)
        if left is None:
            issue("unknown_metric", f"unknown metric: {node.metric}", path)
            return
        if node.timeframe not in left.timeframes:
            issue("unsupported_timeframe", f"unsupported timeframe: {node.timeframe}", path)
        if node.operator not in left.operators:
            issue("unsupported_operator", f"unsupported operator: {node.operator}", path)

        if isinstance(node.right, ConstantOperand):
            if node.right.unit != left.unit:
                issue("unit_mismatch", f"{left.unit} cannot compare with {node.right.unit}", path)
            if node.operator.value in {"between", "not_between"} and (
                not isinstance(node.right.value, list) or len(node.right.value) != 2
            ):
                issue("invalid_range", "between requires exactly two values", path)
            return

        assert isinstance(node.right, MetricOperand)
        right = catalog.get(node.right.metric)
        if right is None:
            issue("unknown_metric", f"unknown metric: {node.right.metric}", path)
        elif right.unit != left.unit:
            issue("unit_mismatch", f"{left.unit} cannot compare with {right.unit}", path)
        elif node.right.timeframe not in right.timeframes:
            issue(
                "unsupported_timeframe",
                f"unsupported right timeframe: {node.right.timeframe}",
                path,
            )

    visit(tree, "root", 1)
    if node_count > max_nodes:
        issues.insert(
            0,
            ScreenValidationIssue(
                "too_many_nodes", f"condition tree exceeds {max_nodes} nodes", "root"
            ),
        )
    return issues
