"""Freeze chart evidence from the successful leaves of a saved screening run."""
import re

from astock.domain.market import Timeframe
from astock.screening.evaluator import TruthValue, evaluate_tree
from astock.screening.models import ConditionNode


def entry_histories(histories: dict, mode: str, as_of, snapshot: dict) -> dict:
    """Keep intraday evidence independent of subsequently downloaded closing bars."""
    if mode != "live":
        return histories
    result = {timeframe: [row for row in rows if row["feature_date"] < as_of]
              for timeframe, rows in histories.items()}
    result[Timeframe.DAY] = [{**snapshot, "feature_date": as_of}, *result.get(Timeframe.DAY, [])]
    return result


def condition_marks(tree: dict, explanation: dict, histories: dict) -> list[dict]:
    marks = []
    active_path = "root"

    def add(metric, timeframe, rows, start, end, label):
        if not rows or start >= len(rows):
            return
        end = min(end, len(rows) - 1)
        marks.append({"metric": metric, "timeframe": timeframe, "path": active_path,
                      "date": str(rows[start]["feature_date"]),
                      "startDate": str(rows[end]["feature_date"]),
                      "periods": end - start + 1, "label": label})

    def visit(node, result, path="root"):
        nonlocal active_path
        active_path = path
        if result["result"] != "true" or node.get("logic") == "not":
            return
        if node["kind"] == "group":
            for index, (child, child_result) in enumerate(zip(node["children"], result["children"], strict=True)):
                visit(child, child_result, f"{path}.children[{index}]")
            return
        metric, timeframe = node["metric"], node["timeframe"]
        rows = histories.get(Timeframe(timeframe), [])
        label = f"实际 {result.get('actual')}，期望 {result.get('expected')}"
        if not rows:
            return
        if metric in {"limit_up_count_5_max_60", "limit_up_burst_5_count_60"}:
            for index in range(min(56, len(rows) - 4)):
                count = sum(bool(row.get("is_limit_up")) for row in rows[index:index + 5])
                threshold = 2 if metric == "limit_up_burst_5_count_60" else result.get("actual")
                if count >= (threshold or 1):
                    add("close", timeframe, rows, index, index + 4, label)
            return
        if metric == "return_10_max_60":
            candidates = [(row.get("return_10"), index) for index, row in enumerate(rows[:50])
                          if row.get("return_10") is not None and index + 10 < len(rows)]
            if candidates:
                _, index = max(candidates)
                add("close", timeframe, rows, index, index + 10, label)
            return
        if node["operator"] in {"continuous", "at_least"}:
            simple = ConditionNode.model_validate({**node, "operator": node.get("comparison_operator", "gt"), "lookback": None, "occurrences": None})
            for index in range(min(node.get("lookback") or node.get("occurrences") or 1, len(rows))):
                shifted = {key: [row for row in values if row["feature_date"] <= rows[index]["feature_date"]]
                           for key, values in histories.items()}
                if evaluate_tree(simple, shifted).result == TruthValue.TRUE:
                    add(metric, timeframe, rows, index, index, label)
                    right = node.get("right", {})
                    if right.get("kind") == "metric":
                        other = histories.get(Timeframe(right["timeframe"]), [])
                        other = [row for row in other if row["feature_date"] <= rows[index]["feature_date"]]
                        add(right["metric"], right["timeframe"], other, 0, 0, label)
            return
        change = re.fullmatch(r"return_(\d+)", metric)
        if change:
            add("close", timeframe, rows, 0, int(change[1]), label)
            return
        flatness = re.fullmatch(r"ma_(\d+)_(?:slope_abs|range)_5", metric)
        if flatness:
            add(f"ma_{flatness[1]}", timeframe, rows, 0, 4, label)
        if metric == "ma_10_20_distance":
            for average in ("ma_10", "ma_20"):
                add(average, timeframe, rows, 0, 0, label)
        pattern_periods = {"bullish_engulfing": 2, "bearish_engulfing": 2, "piercing": 2,
                           "dark_cloud_cover": 2, "morning_star": 3, "evening_star": 3,
                           "three_white_soldiers": 3, "three_black_crows": 3}
        pattern = node.get("right", {}).get("value")
        span = max((pattern_periods.get(value, 1) for value in (pattern if isinstance(pattern, list) else [pattern])), default=1) if metric == "pattern_type" else 1
        add(metric, timeframe, rows, 0, span - 1, label)
        right = node.get("right", {})
        if right.get("kind") == "metric":
            other = histories.get(Timeframe(right["timeframe"]), [])
            add(right["metric"], right["timeframe"], other, 0, 0, label)

    visit(tree, explanation)
    return marks
