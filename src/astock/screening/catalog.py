from dataclasses import dataclass

from astock.domain.market import Timeframe
from astock.features.price_action import PA_LABELS
from astock.features.chart_shapes import SHAPE_LABELS
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
MEMBERSHIP_OPERATORS = frozenset({Operator.IN, Operator.NOT_IN})
CATEGORY_OPERATORS = EQUALITY_OPERATORS | MEMBERSHIP_OPERATORS
SCREEN_TIMEFRAMES = frozenset({Timeframe.DAY, Timeframe.WEEK, Timeframe.MONTH})
ALL_TIMEFRAMES = frozenset(Timeframe)


@dataclass(frozen=True)
class ChoiceSpec:
    value: str
    label: str


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: Unit
    timeframes: frozenset[Timeframe] = SCREEN_TIMEFRAMES
    operators: frozenset[Operator] = NUMERIC_OPERATORS
    group: str = "technical"
    family: str | None = None
    period: int | str | None = None
    directions: tuple[ChoiceSpec, ...] = ()
    choices: tuple[ChoiceSpec, ...] = ()
    multiple: bool = False
    visible: bool = True
    supported_modes: frozenset[str] = frozenset({"close", "backtest"})


def _metric(
    key: str,
    label: str,
    unit: Unit,
    *,
    group: str = "technical",
    family: str | None = None,
    period: int | str | None = None,
    directions: tuple[ChoiceSpec, ...] = (),
) -> MetricSpec:
    return MetricSpec(
        key=key,
        label=label,
        unit=unit,
        timeframes=ALL_TIMEFRAMES,
        group=group,
        family=family,
        period=period,
        directions=directions,
        supported_modes=frozenset({"close", "backtest", "live"}) if (
            key in {"open", "high", "low", "close", "volume", "amount", "volume_ratio_20"}
            or key.startswith(("return_", "volume_ma_"))
            or (key.startswith("ma_") and key[3:].isdigit())
        ) else frozenset({"close", "backtest"}),
    )


RISE_FALL = (
    ChoiceSpec("rise", "上涨幅度"),
    ChoiceSpec("fall", "下跌幅度"),
)
INCREASE_DECREASE = (
    ChoiceSpec("increase", "成交量增加"),
    ChoiceSpec("decrease", "成交量减少"),
)
BOARD_CHOICES = (
    ChoiceSpec("main", "主板"),
    ChoiceSpec("chinext", "创业板"),
    ChoiceSpec("star", "科创板"),
    ChoiceSpec("beijing", "北交所"),
)
LISTING_STAGE_CHOICES = (
    ChoiceSpec("new", "新股"),
    ChoiceSpec("secondary_new", "次新股"),
    ChoiceSpec("established", "老股"),
)
PATTERN_CHOICES = (
    ChoiceSpec("doji", "十字星"),
    ChoiceSpec("long_upper_shadow", "长上影线"),
    ChoiceSpec("long_lower_shadow", "长下影线"),
    ChoiceSpec("hammer", "锤头线"),
    ChoiceSpec("bullish_engulfing", "看涨吞没"),
    ChoiceSpec("bearish_engulfing", "看跌吞没"),
    ChoiceSpec("piercing", "刺透形态"),
    ChoiceSpec("dark_cloud_cover", "乌云盖顶"),
    ChoiceSpec("three_white_soldiers", "红三兵"),
    ChoiceSpec("three_black_crows", "三只乌鸦"),
    ChoiceSpec("morning_star", "早晨之星"),
    ChoiceSpec("evening_star", "黄昏之星"),
    ChoiceSpec("consolidation_breakout", "盘整突破"),
)


METRICS = [
    *[MetricSpec(key, label, Unit.BOOLEAN, timeframes=frozenset({Timeframe.WEEK if key.startswith("pw_") else Timeframe.DAY}),
                 operators=EQUALITY_OPERATORS, group="candlestick", family=key,
                 choices=(ChoiceSpec("true", "是"), ChoiceSpec("false", "否")),
                 supported_modes=frozenset({"close", "backtest"})) for key, label in (PA_LABELS | SHAPE_LABELS).items()],
    MetricSpec("vacuum_reentry_ma120_within_250", "近250交易日内缩量急跌区间重入且当日站上MA120", Unit.BOOLEAN,
               timeframes=frozenset({Timeframe.DAY}), operators=EQUALITY_OPERATORS, group="trend",
               choices=(ChoiceSpec("true", "是"), ChoiceSpec("false", "否"))),
    MetricSpec("vacuum_reentry", "缩量急跌区间跌出后重新进入（跌幅>25%）", Unit.BOOLEAN,
               timeframes=frozenset({Timeframe.DAY}), operators=EQUALITY_OPERATORS, group="trend",
               choices=(ChoiceSpec("true", "是"), ChoiceSpec("false", "否"))),
    *[MetricSpec(key, label, unit, timeframes=frozenset({Timeframe.DAY}), group="trend")
      for key, label, unit in (
          ("vacuum_volume_ratio", "急跌段日均成交量/前20日日均量", Unit.RATIO),
          ("vacuum_lower", "缩量急跌区间下沿（跌幅>25%）", Unit.PRICE),
          ("vacuum_upper", "缩量急跌区间上沿（跌幅>25%）", Unit.PRICE),
          ("vacuum_drop", "缩量急跌区间形成跌幅", Unit.PERCENT),
          ("vacuum_days", "缩量急跌区间下跌天数", Unit.DAYS),
          ("vacuum_efficiency", "缩量急跌区间下跌效率", Unit.PERCENT),
          ("vacuum_break_age", "缩量急跌区间跌出后交易日数", Unit.DAYS),
      )],

    *[
        _metric(key, label, Unit.PRICE, group="price", family=key)
        for key, label in (
            ("open", "开盘价"),
            ("high", "最高价"),
            ("low", "最低价"),
            ("close", "收盘价"),
        )
    ],
    *[
        _metric(
            f"return_{window}",
            "价格涨跌",
            Unit.PERCENT,
            group="price",
            family="price_change",
            period=window,
            directions=RISE_FALL,
        )
        for window in (1, 3, 5, 10, 20, 60, 120, 250)
    ],
    _metric("volume", "成交量", Unit.SHARES, group="activity", family="volume"),
    _metric("amount", "成交额", Unit.AMOUNT, group="activity", family="amount"),
    *[
        _metric(
            f"volume_ma_{window}",
            "平均成交量",
            Unit.SHARES,
            group="activity",
            family="volume_average",
            period=window,
        )
        for window in (5, 20, 60)
    ],
    _metric("volume_ratio_20", "20周期量比", Unit.RATIO, group="activity", family="volume_ratio"),
    MetricSpec("volume_ratio", "实时量比", Unit.RATIO, group="activity", family="live_volume_ratio", supported_modes=frozenset({"live"})),
    *[
        _metric(
            f"volume_change_{window}",
            "成交量增减",
            Unit.PERCENT,
            group="activity",
            family="volume_change",
            period=window,
            directions=INCREASE_DECREASE,
        )
        for window in (1, 5, 20)
    ],
    MetricSpec("turnover_rate", "换手率", Unit.PERCENT, group="activity", family="turnover_rate", supported_modes=frozenset({"live"})),
    MetricSpec("pe_ratio", "市盈率（腾讯）", Unit.RATIO, timeframes=frozenset({Timeframe.DAY}), operators=NUMERIC_OPERATORS - {Operator.CONTINUOUS, Operator.AT_LEAST, Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW}, group="attributes", supported_modes=frozenset({"live"})),
    MetricSpec("pb_ratio", "市净率", Unit.RATIO, timeframes=frozenset({Timeframe.DAY}), operators=NUMERIC_OPERATORS - {Operator.CONTINUOUS, Operator.AT_LEAST, Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW}, group="attributes", supported_modes=frozenset({"live"})),
    MetricSpec("total_market_cap", "总市值", Unit.AMOUNT, group="attributes", family="total_market_cap", supported_modes=frozenset({"live"})),
    MetricSpec("float_market_cap", "流通市值", Unit.AMOUNT, group="attributes", family="float_market_cap", supported_modes=frozenset({"live"})),
    *[
        _metric(f"ma_{window}", "移动平均线", Unit.PRICE, family="ma", period=window)
        for window in (5, 10, 20, 30, 60, 120, 250)
    ],
    *[
        _metric(
            f"ma_{window}_slope_abs_5",
            "均线放平斜率（近5周期）",
            Unit.PERCENT,
            group="trend",
            family="ma_flat_slope_5",
            period=window,
        )
        for window in (10, 20)
    ],
    *[
        _metric(
            f"ma_{window}_range_5",
            "均线放平波动范围（近5周期）",
            Unit.PERCENT,
            group="trend",
            family="ma_flat_range_5",
            period=window,
        )
        for window in (10, 20)
    ],
    _metric(
        "ma_10_20_distance",
        "MA10/MA20 粘合距离",
        Unit.PERCENT,
        group="trend",
        family="ma_convergence",
    ),
    *[_metric(key, label, Unit.PRICE, family=key) for key, label in (("macd", "MACD"), ("macd_signal", "MACD 信号线"), ("macd_hist", "MACD 柱"))],
    *[_metric(key, label, Unit.SCORE, family=key) for key, label in (("kdj_k", "KDJ K"), ("kdj_d", "KDJ D"), ("kdj_j", "KDJ J"), ("rsi_14", "RSI 14"))],
    *[
        _metric(key, label, Unit.PRICE, family=key)
        for key, label in (("boll_upper", "布林上轨"), ("boll_middle", "布林中轨"), ("boll_lower", "布林下轨"), ("atr_14", "ATR 14"), ("obv", "OBV"))
    ],
    *[_metric(key, label, Unit.PERCENT, group="price", family=key) for key, label in (("amplitude", "振幅"), ("volatility_20", "20周期波动率"))],
    *[
        _metric(f"high_{window}", "阶段最高价", Unit.PRICE, group="price", family="period_high", period=window)
        for window in (20, 60, 250)
    ],
    _metric("high_history", "阶段最高价", Unit.PRICE, group="price", family="period_high", period="history"),
    *[
        _metric(f"low_{window}", "阶段最低价", Unit.PRICE, group="price", family="period_low", period=window)
        for window in (20, 60, 250)
    ],
    _metric("low_history", "阶段最低价", Unit.PRICE, group="price", family="period_low", period="history"),
    MetricSpec(
        "return_10_max_60",
        "近3个月任意10日最大涨幅",
        Unit.PERCENT,
        timeframes=frozenset({Timeframe.DAY}),
        group="price",
        family="burst_return",
        supported_modes=frozenset({"close", "backtest"}),
    ),
    *[
        _metric(f"max_drawdown_{window}", "最大回撤", Unit.PERCENT, group="trend", family="max_drawdown", period=window)
        for window in (20, 60, 250)
    ],
    _metric("up_streak", "连续上涨周期数", Unit.DAYS, group="trend", family="up_streak"),
    _metric("down_streak", "连续下跌周期数", Unit.DAYS, group="trend", family="down_streak"),
    MetricSpec("listing_trade_days", "上市交易日数", Unit.DAYS, group="attributes", family="listing_days"),
    MetricSpec("listing_stage", "上市阶段", Unit.CATEGORY, operators=MEMBERSHIP_OPERATORS, group="attributes", family="listing_stage", choices=LISTING_STAGE_CHOICES, multiple=True),
    MetricSpec("is_new", "新股", Unit.BOOLEAN, operators=EQUALITY_OPERATORS, group="attributes", family="is_new", visible=False),
    MetricSpec("is_secondary_new", "次新股", Unit.BOOLEAN, operators=EQUALITY_OPERATORS, group="attributes", family="is_secondary_new", visible=False),
    MetricSpec("is_st", "ST 状态", Unit.BOOLEAN, operators=EQUALITY_OPERATORS, group="status", family="st_status", choices=(ChoiceSpec("true", "ST"), ChoiceSpec("false", "非 ST"))),
    MetricSpec("is_suspended", "交易状态", Unit.BOOLEAN, operators=EQUALITY_OPERATORS, group="status", family="suspension_status", choices=(ChoiceSpec("false", "正常交易"), ChoiceSpec("true", "停牌"))),
    MetricSpec(
        "limit_up_count_5_max_60",
        "近3个月任意5日最多涨停次数",
        Unit.COUNT,
        timeframes=frozenset({Timeframe.DAY}),
        group="status",
        family="burst_limit_up",
        supported_modes=frozenset({"close", "backtest"}),
    ),
    MetricSpec(
        "limit_up_burst_5_count_60",
        "近3个月5日双涨停事件次数",
        Unit.COUNT,
        timeframes=frozenset({Timeframe.DAY}),
        group="status",
        family="burst_limit_up_episodes",
        supported_modes=frozenset({"close", "backtest"}),
    ),
    MetricSpec("board", "所属板块", Unit.CATEGORY, operators=CATEGORY_OPERATORS, group="attributes", family="board", choices=BOARD_CHOICES, multiple=True),
    MetricSpec("em_industry", "东方财富行业", Unit.CATEGORY, timeframes=frozenset({Timeframe.DAY}), operators=MEMBERSHIP_OPERATORS, group="attributes", family="em_industry", multiple=True, supported_modes=frozenset({"close", "live"})),
    MetricSpec("em_concept", "东方财富概念", Unit.CATEGORY, timeframes=frozenset({Timeframe.DAY}), operators=MEMBERSHIP_OPERATORS, group="attributes", family="em_concept", multiple=True, supported_modes=frozenset({"close", "live"})),
    MetricSpec("pattern_type", "K 线形态", Unit.CATEGORY, operators=CATEGORY_OPERATORS, group="candlestick", family="pattern", choices=PATTERN_CHOICES, multiple=True),
    MetricSpec("pattern_strength", "形态强度", Unit.SCORE, group="candlestick", family="pattern_strength"),
    MetricSpec("support_distance", "距支撑位", Unit.PERCENT, group="trend", family="support_distance"),
    MetricSpec("resistance_distance", "距压力位", Unit.PERCENT, group="trend", family="resistance_distance"),
]


class MetricCatalog:
    def __init__(self, metrics: list[MetricSpec] = METRICS) -> None:
        self._metrics = {metric.key: metric for metric in metrics}

    def get(self, key: str) -> MetricSpec | None:
        return self._metrics.get(key)

    def all(self) -> list[MetricSpec]:
        return list(self._metrics.values())


DEFAULT_CATALOG = MetricCatalog()
