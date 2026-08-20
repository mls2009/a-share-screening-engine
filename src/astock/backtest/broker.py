from dataclasses import dataclass
from math import floor

from astock.backtest.models import BacktestMode, FeeSchedule


@dataclass(frozen=True)
class Execution:
    quantity: int
    price: float
    gross: float
    commission: float
    tax: float
    transfer_fee: float
    total_cost: float
    net_cash: float


class Broker:
    def __init__(self, mode: BacktestMode, fees: FeeSchedule) -> None:
        self.mode = mode
        self.fees = fees

    def _commission(self, gross: float) -> float:
        if gross <= 0 or self.fees.commission_rate == 0:
            return 0
        return max(self.fees.minimum_commission, gross * self.fees.commission_rate)

    def buy(self, cash: float, market_price: float, target_cash: float) -> Execution:
        price = market_price * (1 + self.fees.slippage_bps / 10_000)
        budget = min(cash, target_cash)
        raw_quantity = floor(budget / price)
        quantity = raw_quantity // 100 * 100 if self.mode == BacktestMode.REALISTIC else raw_quantity
        while quantity > 0:
            gross = quantity * price
            commission = self._commission(gross)
            transfer = gross * self.fees.transfer_fee_rate
            total = gross + commission + transfer
            if total <= cash and total <= budget:
                return Execution(
                    quantity, price, gross, commission, 0, transfer, total, 0
                )
            quantity -= 100 if self.mode == BacktestMode.REALISTIC else 1
        return Execution(0, price, 0, 0, 0, 0, 0, 0)

    def sell(self, quantity: int, market_price: float) -> Execution:
        price = market_price * (1 - self.fees.slippage_bps / 10_000)
        gross = quantity * price
        commission = self._commission(gross)
        tax = gross * self.fees.sell_stamp_tax_rate
        transfer = gross * self.fees.transfer_fee_rate
        net = gross - commission - tax - transfer
        return Execution(quantity, price, gross, commission, tax, transfer, 0, net)
