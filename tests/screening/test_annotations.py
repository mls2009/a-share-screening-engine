from datetime import date, timedelta

from astock.domain.market import Timeframe
from astock.screening.annotations import condition_marks


def test_window_marks_respect_less_than_comparison():
    tree = {"kind": "condition", "metric": "close", "timeframe": "1d",
            "operator": "at_least", "comparison_operator": "lt", "lookback": 2,
            "occurrences": 1, "right": {"kind": "constant", "value": 10, "unit": "price"}}
    rows = [{"feature_date": date(2026, 9, 4), "close": 9},
            {"feature_date": date(2026, 9, 3), "close": 11}]
    marks = condition_marks(tree, {"result": "true"}, {Timeframe.DAY: rows})
    assert [mark["date"] for mark in marks] == ["2026-09-04"]


def test_continuous_marks_actual_days_and_both_price_and_average():
    tree = {"kind": "condition", "metric": "close", "timeframe": "1d", "operator": "continuous",
            "lookback": 3, "right": {"kind": "metric", "metric": "ma_20", "timeframe": "1d"}}
    rows = [{"feature_date": date(2026, 9, 4) - timedelta(days=index), "close": 11, "ma_20": 10}
            for index in range(3)]
    marks = condition_marks(tree, {"result": "true", "actual": 11, "expected": 10}, {Timeframe.DAY: rows})
    assert len(marks) == 6
    assert {mark["date"] for mark in marks} == {"2026-09-04", "2026-09-03", "2026-09-02"}
    assert {mark["metric"] for mark in marks} == {"close", "ma_20"}


def test_non_matching_or_branch_has_no_mark():
    child = {"kind": "condition", "metric": "close", "timeframe": "1d", "operator": "gt",
             "right": {"kind": "constant", "value": 10, "unit": "price"}}
    tree = {"kind": "group", "logic": "or", "children": [child, {**child, "metric": "ma_20"}]}
    explanation = {"result": "true", "children": [{"result": "true"}, {"result": "false"}]}
    marks = condition_marks(tree, explanation, {Timeframe.DAY: [{"feature_date": date(2026, 9, 4)}]})
    assert [mark["metric"] for mark in marks] == ["close"]


def test_flatness_marks_five_average_points():
    tree = {"kind": "condition", "metric": "ma_10_slope_abs_5", "timeframe": "1d", "operator": "lte",
            "right": {"kind": "constant", "value": 0.05, "unit": "percent"}}
    rows = [{"feature_date": date(2026, 9, 4) - timedelta(days=index)} for index in range(6)]
    marks = condition_marks(tree, {"result": "true"}, {Timeframe.DAY: rows})
    assert marks[0]["metric"] == "ma_10"
    assert marks[0]["periods"] == 5
