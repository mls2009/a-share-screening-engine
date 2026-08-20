import pytest

from astock.backtest.broker import Broker
from astock.backtest.models import BacktestMode, FeeSchedule


def test_realistic_broker_uses_board_lots_slippage_and_sell_tax() -> None:
    broker = Broker(
        BacktestMode.REALISTIC,
        FeeSchedule(
            commission_rate=0.0003,
            minimum_commission=5,
            sell_stamp_tax_rate=0.0005,
            transfer_fee_rate=0.00001,
            slippage_bps=10,
        ),
    )

    buy = broker.buy(cash=100_000, market_price=10, target_cash=50_000)
    sell = broker.sell(quantity=buy.quantity, market_price=11)

    assert buy.quantity == 4900
    assert buy.price == pytest.approx(10.01)
    assert buy.commission >= 5
    assert sell.price == pytest.approx(10.989)
    assert sell.tax > 0
    assert sell.net_cash < sell.quantity * sell.price
