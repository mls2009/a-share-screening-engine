from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from astock.domain.market import Adjustment, Bar, Timeframe
from astock.features.builder import FeatureBuilder
from astock.features.store import MarketFeatureStore
from astock.storage.bars import BarStore
from astock.storage.database import Database

TZ = ZoneInfo("Asia/Shanghai")


def test_builder_persists_idempotent_daily_weekly_monthly_features(tmp_path: Path) -> None:
    database = Database(tmp_path / "features.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "bars")
    dates = pd.date_range("2026-01-02", periods=40, freq="B")
    bars = [
        Bar(
            symbol="600000.SH",
            timestamp=datetime.combine(stamp.date(), datetime.min.time(), tzinfo=TZ),
            timeframe=Timeframe.DAY,
            open=index,
            high=index + 1,
            low=index - 1,
            close=index + 0.5,
            volume_shares=1_000 * index,
            amount_cny=10_000 * index,
            adjustment=Adjustment.QFQ,
            source="test",
        )
        for index, stamp in enumerate(dates, start=1)
    ]
    bar_store.upsert(bars)
    database.connection.execute(
        """
        insert into symbols
          (symbol, name, exchange, listed_on, board, is_listed)
        values ('600000.SH', '浦发银行', 'SH', ?, 'main', true)
        """,
        [dates[0].date()],
    )
    store = MarketFeatureStore(database)
    builder = FeatureBuilder(bar_store, store, database)

    builder.build_symbol("600000.SH", dates[-1].date())
    builder.build_symbol("600000.SH", dates[-1].date())

    counts = dict(
        database.connection.execute(
            "select timeframe, count(*) from market_features group by timeframe"
        ).fetchall()
    )
    latest = store.read_latest("600000.SH", Timeframe.DAY, dates[-1].date())
    assert counts["1d"] == 40
    assert counts["1w"] > 1
    assert counts["1mo"] == 2
    assert database.connection.execute(
        "select count(*) from pattern_events where symbol = '600000.SH'"
    ).fetchone()[0] > 0
    assert latest is not None
    assert latest["listing_trade_days"] == 40
    assert latest["is_new"] is False
    assert latest["is_secondary_new"] is True


def test_builder_persists_automatic_support_and_resistance_zones(tmp_path: Path) -> None:
    database = Database(tmp_path / "zones.duckdb")
    database.migrate()
    bar_store = BarStore(tmp_path / "bars")
    closes = [12, 10.5, 12.5, 14.5, 13, 10.4, 12.5, 14.6, 13, 10.3, 12.5, 14.5, 12]
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    bars = []
    for index, (stamp, close) in enumerate(zip(dates, closes, strict=True)):
        low = {1: 10.0, 5: 10.1, 9: 9.95}.get(index, close - 0.4)
        high = {3: 15.0, 7: 15.1, 11: 14.95}.get(index, close + 0.4)
        bars.append(
            Bar(
                symbol="600000.SH",
                timestamp=datetime.combine(stamp.date(), datetime.min.time(), tzinfo=TZ),
                timeframe=Timeframe.DAY,
                open=close - 0.1,
                high=high,
                low=low,
                close=close,
                volume_shares=1_000,
                amount_cny=10_000,
                adjustment=Adjustment.QFQ,
                source="test",
            )
        )
    bar_store.upsert(bars)
    database.connection.execute(
        """
        insert into symbols (symbol, name, exchange, listed_on, is_listed)
        values ('600000.SH', '浦发银行', 'SH', ?, true)
        """,
        [dates[0].date()],
    )

    FeatureBuilder(bar_store, MarketFeatureStore(database), database).build_symbol(
        "600000.SH", dates[-1].date()
    )

    kinds = {
        row[0]
        for row in database.connection.execute(
            "select distinct zone_kind from support_resistance_zones where timeframe = '1d'"
        ).fetchall()
    }
    assert kinds == {"support", "resistance"}
