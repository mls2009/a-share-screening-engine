from datetime import date, timedelta

from astock.screening.waves import WaveRequest, scan_waves


def rows(prices):
    return list(reversed([{"feature_date": date(2024, 1, 1) + timedelta(days=i), "close": price, "ma_10": 11} for i, price in enumerate(prices)]))


def condition(operator="gt"):
    return {"kind": "condition", "metric": "close", "timeframe": "1d", "operator": operator,
            "right": {"kind": "metric", "metric": "ma_10", "timeframe": "1d"}}


def test_merges_consecutive_matches_and_includes_latest_and_single_day():
    result = scan_waves(rows([12, 13, 10, 15]), WaveRequest(tree=condition()))
    assert result["matched_days"] == 3
    assert [(r["start"], r["end"], r["days"]) for r in result["matches"]] == [
        ("2024-01-04", "2024-01-04", 1), ("2024-01-01", "2024-01-02", 2)]
    assert result["matches"][0]["gain"] == 0


def test_unknown_breaks_interval_and_is_counted_separately():
    result = scan_waves(rows([12, None, 14]), WaveRequest(tree=condition()))
    assert result["unknown"] == 1
    assert result["total"] == 2
    assert result["matched_days"] == 2


def test_crossing_uses_only_history_available_on_each_date():
    result = scan_waves(rows([10, 12, 15, 10, 13]), WaveRequest(tree=condition("crosses_above")))
    assert [r["start"] for r in result["matches"]] == ["2024-01-05", "2024-01-02"]
    assert all(r["days"] == 1 for r in result["matches"])


def test_combined_conditions_and_empty_history():
    tree = {"kind": "group", "logic": "and", "children": [condition(), {
        "kind": "condition", "metric": "close", "timeframe": "1d", "operator": "lt",
        "right": {"kind": "constant", "value": 14, "unit": "price"}}]}
    result = scan_waves(rows([10, 12, 15]), WaveRequest(tree=tree))
    assert result["matched_days"] == 1
    assert result["matches"][0]["start"] == "2024-01-02"
    assert scan_waves([], WaveRequest(tree=tree))["bars"] == 0
