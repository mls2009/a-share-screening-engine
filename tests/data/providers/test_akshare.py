from datetime import date
from types import SimpleNamespace

import pandas as pd

from astock.data.providers.akshare import AkShareProvider
from astock.domain.market import Adjustment, Timeframe


def test_akshare_normalizes_bse_universe_with_listing_dates() -> None:
    module = SimpleNamespace(
        stock_info_bj_name_code=lambda: pd.DataFrame(
            {
                "证券代码": ["920001", "920002"],
                "证券简称": ["北交一", "北交二"],
                "上市日期": [date(2025, 1, 2), date(2026, 1, 5)],
            }
        )
    )

    securities = AkShareProvider(module).securities_on(date(2026, 8, 20))

    assert [security.symbol for security in securities] == ["920001.BJ", "920002.BJ"]
    assert securities[0].listed_on == date(2025, 1, 2)
    assert all(security.board == "beijing" for security in securities)


def test_akshare_normalizes_bse_qfq_daily_volume_and_amount_units() -> None:
    calls: list[dict] = []

    def stock_zh_a_daily(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {
                "date": [date(2026, 8, 19)],
                "open": [10.0],
                "close": [10.5],
                "high": [10.8],
                "low": [9.9],
                "volume": [12_300],
                "amount": [129_150.0],
            }
        )

    provider = AkShareProvider(SimpleNamespace(stock_zh_a_daily=stock_zh_a_daily))

    bars = provider.history(
        "920001.BJ",
        Timeframe.DAY,
        date(2026, 8, 1),
        date(2026, 8, 20),
        Adjustment.QFQ,
    )

    assert bars[0].volume_shares == 12_300
    assert bars[0].amount_cny == 129_150
    assert bars[0].timestamp.isoformat() == "2026-08-19T15:00:00+08:00"
    assert calls[0]["symbol"] == "bj920001"
    assert calls[0]["adjust"] == "qfq"
