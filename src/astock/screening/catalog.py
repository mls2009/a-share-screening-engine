from dataclasses import dataclass

from astock.domain.market import Timeframe
from astock.screening.models import Operator, Unit

NUMERIC_OPERATORS = frozenset(
    {
        Operator.EQ,
        Operator.NE,
        Operator.GT,
        Operator.GTE,
        Operator.LT,
        Operator.LTE,
        Operator.BETWEEN,
        Operator.NOT_BETWEEN,
        Operator.CROSSES_ABOVE,
        Operator.CROSSES_BELOW,
        Operator.AT_LEAST,
        Operator.CONTINUOUS,
    }
)
EQUALITY_OPERATORS = frozenset({Operator.EQ, Operator.NE})
SCREEN_TIMEFRAMES = frozenset({Timeframe.DAY, Timeframe.WEEK, Timeframe.MONTH})


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: Unit
    timeframes: frozenset[Timeframe] = SCREEN_TIMEFRAMES
    operators: frozenset[Operator] = NUMERIC_OPERATORS


def _metric(key: str, label: str, unit: Unit) -> MetricSpec:
    return MetricSpec(key=key, label=label, unit=unit)


METRICS = [
    *[_metric(key, key, Unit.PRICE) for key in ("open", "high", "low", "close")],
    *[
        _metric(f"return_{window}", f"{window}周期涨跌幅", Unit.PERCENT)
        for window in (1, 3, 5, 10, 20, 60, 120, 250)
    ],
    _metric("volume", "成交量", Unit.SHARES),
    _metric("amount", "成交额", Unit.AMOUNT),
    *[
        _metric(f"volume_ma_{window}", f"{window}周期均量", Unit.SHARES)
        for window in (5, 20, 60)
    ],
    _metric("volume_ratio_20", "20周期量比", Unit.RATIO),
    _metric("volume_ratio", "实时量比", Unit.RATIO),
    *[
        _metric(f"volume_change_{window}", f"成交量{window}周期增减", Unit.PERCENT)
        for window in (1, 5, 20)
    ],
    _metric("turnover_rate", "换手率", Unit.PERCENT),
    _metric("total_market_cap", "总市值", Unit.AMOUNT),
    _metric("float_market_cap", "流通市值", Unit.AMOUNT),
    *[
        _metric(f"ma_{window}", f"MA{window}", Unit.PRICE)
        for window in (5, 10, 20, 30, 60, 120, 250)
    ],
    *[_metric(key, key, Unit.PRICE) for key in ("macd", "macd_signal", "macd_hist")],
    *[_metric(key, key, Unit.SCORE) for key in ("kdj_k", "kdj_d", "kdj_j", "rsi_14")],
    *[
        _metric(key, key, Unit.PRICE)
        for key in ("boll_upper", "boll_middle", "boll_lower", "atr_14", "obv")
    ],
    *[_metric(key, key, Unit.PERCENT) for key in ("amplitude", "volatility_20")],
    *[
        _metric(f"high_{window}", f"{window}周期最高价", Unit.PRICE)
        for window in (20, 60, 250)
    ],
    *[
        _metric(f"low_{window}", f"{window}周期最低价", Unit.PRICE)
        for window in (20, 60, 250)
    ],
    *[
        _metric(f"max_drawdown_{window}", f"{window}周期最大回撤", Unit.PERCENT)
        for window in (20, 60, 250)
    ],
    _metric("up_streak", "连续上涨周期数", Unit.DAYS),
    _metric("down_streak", "连续下跌周期数", Unit.DAYS),
    _metric("listing_trade_days", "上市交易日数", Unit.DAYS),
    MetricSpec("is_new", "新股", Unit.BOOLEAN, operators=EQUALITY_OPERATORS),
    MetricSpec("is_secondary_new", "次新股", Unit.BOOLEAN, operators=EQUALITY_OPERATORS),
    MetricSpec("is_st", "ST", Unit.BOOLEAN, operators=EQUALITY_OPERATORS),
    MetricSpec("is_suspended", "停牌", Unit.BOOLEAN, operators=EQUALITY_OPERATORS),
    MetricSpec("board", "板块", Unit.CATEGORY, operators=EQUALITY_OPERATORS),
    MetricSpec("pattern_type", "K线形态", Unit.CATEGORY, operators=EQUALITY_OPERATORS),
    _metric("pattern_strength", "形态强度", Unit.SCORE),
    _metric("support_distance", "距支撑区", Unit.PERCENT),
    _metric("resistance_distance", "距压力区", Unit.PERCENT),
]


class MetricCatalog:
    def __init__(self, metrics: list[MetricSpec] = METRICS) -> None:
        self._metrics = {metric.key: metric for metric in metrics}

    def get(self, key: str) -> MetricSpec | None:
        return self._metrics.get(key)

    def all(self) -> list[MetricSpec]:
        return list(self._metrics.values())


DEFAULT_CATALOG = MetricCatalog()
