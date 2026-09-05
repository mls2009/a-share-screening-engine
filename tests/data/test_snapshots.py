from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock.data.snapshots import overlay_snapshot
from astock.domain.market import MarketSnapshot


def test_live_snapshot_creates_temporary_feature_row_without_mutating_history() -> None:
    history = [
        {"feature_date": f"2026-08-{19 - index:02d}", "close": 10.0, "volume": 100.0}
        for index in range(10)
    ]
    original = [dict(row) for row in history]
    snapshot = MarketSnapshot(
        symbol="600001.SH",
        timestamp=datetime(2026, 8, 20, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        price=11.0,
        open=10.2,
        high=11.2,
        low=10.1,
        previous_close=10.0,
        volume_shares=180,
        amount_cny=1_900,
        turnover_rate=2.5,
        volume_ratio=1.8,
        source="tencent",
    )

    overlaid = overlay_snapshot(history, snapshot)

    assert overlaid[0]["return_1"] == 10.0
    assert overlaid[0]["close"] == 11.0
    assert overlaid[0]["volume_ratio"] == 1.8
    assert overlaid[0]["volume_ratio_20"] is None
    assert overlaid[1:] == original
    assert history == original


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="600001.SH",
        timestamp=datetime(2026, 8, 20, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        price=11, previous_close=10, volume_shares=200, amount_cny=2200,
        volume_ratio=8, source="test",
    )


def test_live_does_not_reuse_uncomputed_historical_indicators() -> None:
    history = [{"feature_date": "2026-08-19", "close": 10, "macd": 3,
                "rsi_14": 80, "pattern_type": "hammer", "is_suspended": False,
                "volume_ratio_20": 2, "name": "股票一", "board": "main"}]
    live = overlay_snapshot(history, _snapshot())[0]
    for key in ("macd", "rsi_14", "pattern_type", "is_suspended", "volume_ratio_20"):
        assert live.get(key) is None, key
    assert live["board"] == "main"
    assert live["volume_ratio"] == 8


def test_live_replaces_same_day_row_instead_of_counting_it_twice() -> None:
    history = [
        {"feature_date": f"2026-08-{day}", "close": close, "volume": 100}
        for day, close in [(20, 99), (19, 10), (18, 9), (17, 8), (16, 7)]
    ]
    overlaid = overlay_snapshot(history, _snapshot())
    assert len(overlaid) == 5
    assert overlaid[0]["ma_5"] == 9
    assert overlaid[0]["return_3"] == pytest.approx((11 / 8 - 1) * 100)
    assert history[0]["close"] == 99


def test_live_twenty_period_volume_ratio_uses_same_formula_as_close_mode() -> None:
    history = [{"feature_date": "2026-08-19", "close": 10, "volume": 100}] * 19
    live = overlay_snapshot(history, _snapshot())[0]
    assert live["volume_ratio_20"] == pytest.approx(200 / ((1900 + 200) / 20))
    assert live["volume_ratio"] == 8
