from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

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


def test_akshare_normalizes_index_daily_bars_without_adjustment() -> None:
    calls: list[dict] = []

    def stock_zh_index_daily_em(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame({
            "date": [date(2026, 8, 19)],
            "open": [3_700.0],
            "close": [3_720.5],
            "high": [3_730.0],
            "low": [3_690.0],
            "volume": [456_000_000],
            "amount": [789_000_000_000.0],
        })

    provider = AkShareProvider(SimpleNamespace(
        stock_zh_index_daily_em=stock_zh_index_daily_em,
    ))

    bars = provider.index_history(
        "000001.SH", Timeframe.DAY, date(2026, 8, 1), date(2026, 8, 20)
    )

    assert calls == [{
        "symbol": "sh000001", "start_date": "20260801", "end_date": "20260820",
    }]
    assert bars[0].symbol == "000001.SH"
    assert bars[0].timestamp.isoformat() == "2026-08-19T15:00:00+08:00"
    assert bars[0].volume_shares == 456_000_000
    assert bars[0].adjustment == Adjustment.NONE


def test_akshare_normalizes_index_five_minute_volume_from_lots() -> None:
    calls: list[dict] = []

    def index_zh_a_hist_min_em(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame({
            "时间": ["2026-08-20 09:35:00"],
            "开盘": [2_800.0],
            "收盘": [2_805.0],
            "最高": [2_806.0],
            "最低": [2_799.0],
            "成交量": [12_300],
            "成交额": [345_000_000.0],
        })

    provider = AkShareProvider(SimpleNamespace(
        index_zh_a_hist_min_em=index_zh_a_hist_min_em,
    ))

    bars = provider.index_history(
        "399006.SZ", Timeframe.MIN_5, date(2026, 8, 20), date(2026, 8, 20)
    )

    assert calls == [{
        "symbol": "399006",
        "period": "5",
        "start_date": "2026-08-20 00:00:00",
        "end_date": "2026-08-20 23:59:59",
    }]
    assert bars[0].timestamp.isoformat() == "2026-08-20T09:35:00+08:00"
    assert bars[0].volume_shares == 1_230_000
    assert bars[0].adjustment == Adjustment.NONE


def test_akshare_index_history_only_accepts_base_timeframes() -> None:
    provider = AkShareProvider(SimpleNamespace())

    with pytest.raises(ValueError, match="unsupported index timeframe"):
        provider.index_history(
            "000001.SH", Timeframe.MIN_15, date(2026, 8, 1), date(2026, 8, 20)
        )
