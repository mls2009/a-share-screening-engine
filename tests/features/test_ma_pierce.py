import pandas as pd

from astock.features.ma_pierce import (
    MA_PIERCE_2Y_METRIC,
    MA_PIERCE_METRIC,
    MA_PIERCE_WINDOWS,
    ma_pierce_2y_exists,
    ma_pierce_2y_hits,
    ma_pierce_2y_scan,
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


def flat_frame(length=120, price=10.0, volume=1000.0):
    """横向盘整的日线 frame：均线全部放平粘连在 price 上，量能恒定。"""
    dates = pd.bdate_range("2024-01-01", periods=length)
    return pd.DataFrame({
        "feature_date": dates,
        "open": [price] * length,
        "close": [price] * length,
        "volume": [volume] * length,
        "volume_ma_20": [volume] * length,
        **{f"ma_{window}": [price] * length for window in MA_PIERCE_WINDOWS},
    })


def pierced_row(frame, index, open_, close, volume=None):
    frame.loc[index, "open"] = open_
    frame.loc[index, "close"] = close
    if volume is not None:
        frame.loc[index, "volume"] = volume


def test_2y_scan_detects_full_pattern():
    frame = flat_frame()
    pierced_row(frame, 60, 9.5, 11.0, volume=2500.0)
    result = ma_pierce_2y_scan(frame)
    assert bool(result.iloc[60]) is True
    assert int(result.sum()) == 1


def test_2y_scan_rejects_without_volume():
    frame = flat_frame()
    pierced_row(frame, 60, 9.5, 11.0, volume=1500.0)  # 不足 2 倍均量
    assert bool(ma_pierce_2y_scan(frame).iloc[60]) is False


def test_2y_scan_rejects_rising_cluster():
    frame = flat_frame()
    # 均线束整体上行（每日约 0.8%）：MA10/20/30 斜率远超走平阈值
    for window in MA_PIERCE_WINDOWS:
        frame[f"ma_{window}"] = [10.0 * (1 + 0.008 * i) for i in range(len(frame))]
    pierced_row(frame, 100, 13.0, 14.5, volume=2500.0)
    assert bool(ma_pierce_2y_scan(frame).iloc[100]) is False


def test_2y_scan_rejects_wide_spread():
    frame = flat_frame()
    # MA10/20/30 相互距离超过 2%
    for index in range(len(frame)):
        frame.loc[index, "ma_10"] = 10.3
        frame.loc[index, "ma_30"] = 9.7
    pierced_row(frame, 60, 9.4, 11.2, volume=2500.0)
    assert bool(ma_pierce_2y_scan(frame).iloc[60]) is False


def test_2y_scan_ignores_rows_with_missing_ma():
    frame = flat_frame(30)
    pierced_row(frame, 25, 9.5, 11.0, volume=2500.0)
    frame.loc[25, "ma_120"] = None  # 上市不足 120 日
    assert bool(ma_pierce_2y_scan(frame).iloc[25]) is False


def test_2y_hits_report_dates():
    frame = flat_frame()
    pierced_row(frame, 40, 9.5, 11.0, volume=2500.0)
    hits = ma_pierce_2y_hits(frame)
    assert len(hits) == 1
    assert hits[0]["date"] == str(frame.loc[40, "feature_date"].date())
    assert hits[0]["close"] == 11.0


def test_2y_exists_respects_two_year_window():
    # 命中发生在 ~2.2 年前：对最新一行已超出两年窗口
    long_frame = flat_frame(580)  # 约 2.3 个自然年
    pierced_row(long_frame, 10, 9.5, 11.0, volume=2500.0)
    exists = ma_pierce_2y_exists(long_frame)
    assert bool(exists.iloc[10]) is True
    assert bool(exists.iloc[-1]) is False

    # 命中发生在 ~1.3 年前：仍在窗口内
    short_frame = flat_frame(340)
    pierced_row(short_frame, 10, 9.5, 11.0, volume=2500.0)
    assert bool(ma_pierce_2y_exists(short_frame).iloc[-1]) is True


def test_2y_metric_detected_by_uses_ma_pierce():
    tree = {"kind": "condition", "metric": MA_PIERCE_2Y_METRIC, "timeframe": "1d",
            "operator": "eq", "right": {"kind": "constant", "value": True, "unit": "boolean"}}
    assert uses_ma_pierce(tree) is True


def test_flat_slope_uses_five_prior_sessions_not_breakout_day():
    import pandas as pd
    from astock.features.ma_pierce import ma_pierce_2y_scan
    frame = pd.DataFrame({
        'open': [9.0]*10, 'close': [12.0]*10,
        'volume': [300.0]*10, 'volume_ma_20': [100.0]*10,
        **{f'ma_{w}': [10.0]*9+[11.0] for w in (5,10,20,30,60,120)},
    })
    # 五个完整的前置交易日均线走平，突破日均线跳升不影响走平判定。
    result = ma_pierce_2y_scan(frame)
    assert not result.iloc[:9].any()
    assert result.iloc[9]
    # 前置窗口明显上行，不能被突破当天的回落抵消。
    for w in (10,20,30):
        frame[f'ma_{w}'] = [10.0]*4+[9.6,9.7,9.8,9.9,10.0,9.7]
    assert not ma_pierce_2y_scan(frame).iloc[9]


def test_flat_rejects_prior_daily_slope_even_when_last_five_are_flat():
    frame = flat_frame(12)
    frame.loc[:8, "ma_20"] = [9.5, 9.6, 9.7, 9.8, 10, 10, 10, 10, 10]
    pierced_row(frame, 9, 9, 11, volume=2500)
    assert not ma_pierce_2y_scan(frame).iloc[9]


def test_flat_rejects_overall_slope_between_point_one_and_point_two():
    frame = flat_frame(12)
    frame["ma_10"] = [10 + .015*i for i in range(12)]
    pierced_row(frame, 9, 9, 11, volume=2500)
    assert not ma_pierce_2y_scan(frame).iloc[9]


def test_ten_day_version_ignores_ma120_and_marks_full_consolidation():
    frame = flat_frame(30)
    frame['ma_120'] = float('nan')
    pierced_row(frame, 20, 9, 11, volume=2500)
    assert ma_pierce_2y_scan(frame, ten_day=True).iloc[20]
    assert not ma_pierce_2y_scan(frame).iloc[20]
    hit = ma_pierce_2y_hits(frame, ten_day=True)[0]
    assert hit['start_date'] == str(frame.iloc[10].feature_date.date())
    assert hit['end_date'] == str(frame.iloc[19].feature_date.date())
    assert hit['date'] == str(frame.iloc[20].feature_date.date())
    frame.loc[10, 'ma_30'] = 10.09
    assert not ma_pierce_2y_scan(frame, ten_day=True).iloc[20]


def test_ten_day_version_excludes_breakout_day_from_cluster_and_requires_warmup():
    frame = flat_frame(30)
    pierced_row(frame, 20, 9, 11, volume=2500)
    frame.loc[20, 'ma_30'] = 10.5
    assert ma_pierce_2y_scan(frame, ten_day=True).iloc[20]
    assert not ma_pierce_2y_scan(frame.iloc[7:].reset_index(drop=True), ten_day=True).iloc[13]
