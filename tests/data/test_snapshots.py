from datetime import datetime
from zoneinfo import ZoneInfo

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
    assert overlaid[0]["volume_ratio_20"] == 1.8
    assert overlaid[1:] == original
    assert history == original
