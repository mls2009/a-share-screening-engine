import math

import pandas as pd

from astock.features.technical import compute_burst_features, compute_technical_features


def _frame(rows: int = 30) -> pd.DataFrame:
    close = pd.Series(range(1, rows + 1), dtype=float)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=rows, freq="B"),
            "open": close - 0.25,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume_shares": [100] * rows,
            "amount_cny": close * 100,
        }
    )


def test_computes_returns_averages_volume_and_obv() -> None:
    features = compute_technical_features(_frame())
    last = features.iloc[-1]

    assert last["return_20"] == 200.0
    assert last["ma_5"] == 28.0
    assert last["volume_ma_20"] == 100.0
    assert last["volume_ratio_20"] == 1.0
    assert last["obv"] == 2_900.0


def test_computes_bollinger_atr_rsi_and_streaks() -> None:
    features = compute_technical_features(_frame())
    last = features.iloc[-1]

    assert last["boll_middle"] == 20.5
    assert math.isclose(last["boll_upper"], 20.5 + 2 * math.sqrt(33.25))
    assert last["atr_14"] == 2.0
    assert last["rsi_14"] == 100.0
    assert last["up_streak"] == 29


def test_computes_available_history_high_and_low() -> None:
    frame = _frame(3)
    frame["high"] = [5.0, 3.0, 4.0]
    frame["low"] = [2.0, 1.0, 1.5]

    features = compute_technical_features(frame)

    assert features["high_history"].tolist() == [5.0, 5.0, 5.0]
    assert features["low_history"].tolist() == [2.0, 1.0, 1.0]


def test_computes_ma_flatness_and_convergence_metrics() -> None:
    features = compute_technical_features(_frame())
    last = features.iloc[-1]

    assert math.isclose(last["ma_10_slope_abs_5"], 1 / 23.5 * 100)
    assert math.isclose(last["ma_20_slope_abs_5"], 1 / 18.5 * 100)
    assert math.isclose(last["ma_10_range_5"], (25.5 / 21.5 - 1) * 100)
    assert math.isclose(last["ma_20_range_5"], (20.5 / 16.5 - 1) * 100)
    assert math.isclose(last["ma_10_20_distance"], 5 / 23 * 100)


def test_ma_flatness_requires_five_complete_ma_values() -> None:
    features = compute_technical_features(_frame(23))

    assert math.isnan(features.iloc[-1]["ma_20_slope_abs_5"])
    assert math.isnan(features.iloc[-1]["ma_20_range_5"])


def test_features_do_not_change_past_rows_when_future_bars_are_added() -> None:
    short = compute_technical_features(_frame(20))
    full = compute_technical_features(_frame(30)).iloc[:20]

    pd.testing.assert_frame_equal(short, full)


def test_counts_separate_five_day_double_limit_up_episodes_without_overlap() -> None:
    features = pd.DataFrame(
        {
            "return_1": [0.0] * 70,
            "return_10": [float("nan")] * 70,
        }
    )
    features.loc[[20, 22, 40, 42], "return_1"] = 10.0
    thresholds = pd.Series([10.0] * 70)

    result = compute_burst_features(features, thresholds)

    assert result.iloc[-1]["limit_up_burst_5_count_60"] == 2
