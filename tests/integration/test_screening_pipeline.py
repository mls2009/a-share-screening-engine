from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from astock.data.market_sync import MarketSyncService
from astock.data.service import MarketDataService
from astock.domain.market import Adjustment, Bar, Timeframe
from astock.domain.security import Security
from astock.features.builder import FeatureBuilder
from astock.features.store import MarketFeatureStore
from astock.features.zones import nearest_zones
from astock.screening.models import GroupNode
from astock.screening.service import ScreeningService
from astock.storage.bars import BarStore
from astock.storage.database import Database
from astock.storage.jobs import SyncJobRepository

TZ = ZoneInfo("Asia/Shanghai")


class FixedProvider:
    def __init__(self) -> None:
        dates = pd.date_range("2026-06-26", periods=40, freq="B")
        closes = [10, 10.5, 11, 10.2, 11.5] * 4 + [12, 13, 14, 13, 15] * 4
        self.bars = [
            Bar(
                symbol="600001.SH",
                timestamp=datetime.combine(stamp.date(), time(15), tzinfo=TZ),
                timeframe=Timeframe.DAY,
                open=close - 0.1,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume_shares=200 if index == 39 else 100,
                amount_cny=close * (200 if index == 39 else 100),
                adjustment=Adjustment.QFQ,
                source="fixed",
            )
            for index, (stamp, close) in enumerate(zip(dates, closes, strict=True))
        ]

    def securities_on(self, on_date: date) -> list[Security]:
        return [
            Security(
                symbol="600001.SH",
                name="测试股票",
                exchange="SH",
                board="main",
                listed_on=date(2020, 1, 1),
            )
        ]

    def symbols_on(self, on_date: date) -> list[dict]:
        return [{"symbol": "600001.SH", "name": "测试股票"}]

    def trading_dates(self, start: date, end: date) -> set[date]:
        return {
            bar.timestamp.date()
            for bar in self.bars
            if start <= bar.timestamp.date() <= end
        }

    def history(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: date,
        end: date,
        adjustment: Adjustment,
    ) -> list[Bar]:
        return [
            bar
            for bar in self.bars
            if start <= bar.timestamp.date() <= end
        ]

    def adjustment_factors(self, symbol: str, start: date, end: date) -> list[dict]:
        return []

    def corporate_actions(self, symbol: str, start: date, end: date) -> list[dict]:
        return []

    def security_status(self, symbol: str, start: date, end: date) -> list[dict]:
        return []


def test_sync_feature_screen_bars_and_zones_pipeline(tmp_path: Path) -> None:
    database = Database(tmp_path / "pipeline.duckdb")
    database.migrate()
    bars = BarStore(tmp_path / "bars")
    provider = FixedProvider()
    market_data = MarketDataService(
        provider,
        bars,
        database,
        reference_provider=provider,
    )
    features = MarketFeatureStore(database)
    sync = MarketSyncService(
        market_data,
        provider,
        SyncJobRepository(database.connection),
        FeatureBuilder(bars, features, database),
    )

    summary = sync.start(end=date(2026, 8, 20), years=1)
    condition = GroupNode.model_validate(
        {
            "kind": "group",
            "logic": "and",
            "children": [
                {
                    "kind": "condition",
                    "metric": "return_20",
                    "timeframe": "1d",
                    "operator": "gte",
                    "right": {"kind": "constant", "value": 30, "unit": "percent"},
                },
                {
                    "kind": "condition",
                    "metric": "volume",
                    "timeframe": "1d",
                    "operator": "gt",
                    "right": {
                        "kind": "metric",
                        "metric": "volume_ma_20",
                        "timeframe": "1d",
                        "multiplier": 1.5,
                    },
                },
            ],
        }
    )
    result = ScreeningService(database, features).run(
        condition, as_of=date(2026, 8, 20)
    )

    assert summary.status == "completed"
    assert [match.symbol for match in result.matches] == ["600001.SH"]
    assert len(bars.read("600001.SH", Timeframe.DAY, Adjustment.QFQ)) == 40
    assert nearest_zones(
        database.connection,
        "600001.SH",
        Timeframe.DAY,
        date(2026, 8, 20),
    )
