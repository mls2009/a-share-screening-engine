from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from astock.domain.market import Bar, Quote, Timeframe


def test_bar_rejects_invalid_ohlc() -> None:
    with pytest.raises(ValidationError):
        Bar(
            symbol="600519.SH",
            timestamp=datetime.now(ZoneInfo("Asia/Shanghai")),
            timeframe=Timeframe.DAY,
            open=10,
            high=9,
            low=8,
            close=9,
            volume_shares=100,
            amount_cny=900,
        )


def test_quote_uses_share_volume() -> None:
    quote = Quote(
        symbol="600519.SH",
        timestamp=datetime.now(ZoneInfo("Asia/Shanghai")),
        price=10,
        volume_shares=12_300,
        amount_cny=123_000,
        source="mootdx",
    )

    assert quote.volume_shares == 12_300
