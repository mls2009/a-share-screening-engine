from astock.features.ma_pierce import (
    MA_PIERCE_METRIC,
    MA_PIERCE_WINDOWS,
    ma_pierce_features,
    uses_ma_pierce,
)


def row(open_, close, mas=None):
    result = {"open": open_, "close": close, "high": max(open_, close) + 0.3,
              "low": min(open_, close) - 0.3}
    mas = mas if mas is not None else [10.0 + i * 0.15 for i in range(len(MA_PIERCE_WINDOWS))]
    for window, value in zip(MA_PIERCE_WINDOWS, mas, strict=True):
        result[f"ma_{window}"] = value
    return result


def test_bullish_body_through_entire_cluster():
    # 均线束 10.0~10.8：开盘低于最低均线、收盘高于最高均线、收阳
    derived = ma_pierce_features([row(9.9, 11.0)])
    assert derived[0][MA_PIERCE_METRIC] is True


def test_body_must_span_both_edges():
    # 收盘未站上最高均线，实体只穿了一半
    derived = ma_pierce_features([row(9.9, 10.5)])
    assert derived[0][MA_PIERCE_METRIC] is False

    # 开盘已高于最低均线，实体未从下方穿过
    derived = ma_pierce_features([row(10.1, 11.2)])
    assert derived[0][MA_PIERCE_METRIC] is False


def test_bearish_candle_is_not_a_pierce():
    derived = ma_pierce_features([row(11.0, 9.9)])
    assert derived[0][MA_PIERCE_METRIC] is False


def test_touching_edge_without_crossing_is_rejected():
    # 开盘正好压在最低均线上、收盘正好等于最高均线，均不算"穿过"
    derived = ma_pierce_features([row(10.0, 10.8)])
    assert derived[0][MA_PIERCE_METRIC] is False


def test_missing_any_average_is_unknown():
    mas = [10.0 + i * 0.2 for i in range(len(MA_PIERCE_WINDOWS))]
    mas[-1] = None  # ma_120 缺失（如上市不足 120 日）
    derived = ma_pierce_features([row(9.9, 11.0, mas)])
    assert derived[0][MA_PIERCE_METRIC] is None


def test_open_close_missing_is_unknown():
    derived = ma_pierce_features([{"ma_5": 10.0}])
    assert derived[0][MA_PIERCE_METRIC] is None


def test_empty_rows():
    assert ma_pierce_features([]) == []


def test_uses_ma_pierce_detects_nested_metric():
    tree = {"kind": "group", "logic": "and", "children": [
        {"kind": "condition", "metric": "ma_cluster_pierce_up", "timeframe": "1d",
         "operator": "eq", "right": {"kind": "constant", "value": True, "unit": "boolean"}}]}
    assert uses_ma_pierce(tree) is True
    other = {"kind": "condition", "metric": "ma_20", "timeframe": "1d",
             "operator": "gt", "right": {"kind": "constant", "value": 5, "unit": "price"}}
    assert uses_ma_pierce(other) is False
