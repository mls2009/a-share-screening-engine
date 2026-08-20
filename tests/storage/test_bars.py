from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.domain.market import Adjustment, Bar, Timeframe
from astock.storage.bars import BarStore


def test_upsert_bars_deduplicates_symbol_timestamp(tmp_path: Path) -> None:
    bar = Bar(
        symbol="600519.SH",
        timestamp=datetime(2026, 8, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
        timeframe=Timeframe.DAY,
        open=10,
        high=11,
        low=9,
        close=10.5,
        volume_shares=1_000,
        amount_cny=10_500,
        source="test",
    )
    store = BarStore(tmp_path)

    store.upsert([bar, bar])
    saved = store.read("600519.SH", Timeframe.DAY, Adjustment.NONE)

    assert saved == [bar]
