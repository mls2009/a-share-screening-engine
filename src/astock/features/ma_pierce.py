"""均线束穿线信号：单根阳线的实体自下而上穿过除年线外全部均线。

穿透判定只依赖当日已完成的 OHLC 与当日均线值：
  阳线（close > open）且 open < min(可用的短期均线) 且 close > max(可用的短期均线)。
均线取 MA5/MA10/MA20/MA30/MA60/MA120（年线 MA250 不参与）。

近两年变体（ma_cluster_pierce_up_2y）：在近两个自然年内出现过一次
「MA10/20/30 走平粘连 + 放量大阳实体穿线」的完整形态即命中。
走平斜率仅使用突破前5个交易日，不包含突破当天，绝对值≤0.10%/交易日。
这5天每一天的滚动5日拟合斜率绝对值均须≤0.20%/交易日（需9日前置均线值）。
走平/粘连只约束 MA10/MA20/MA30（MA5 波动大、不易放平，不参与走平粘连判定）。
"""
import pandas as pd

from astock.features.technical import _normalized_slope_abs

MA_PIERCE_METRIC = "ma_cluster_pierce_up"
MA_PIERCE_2Y_METRIC = "ma_cluster_pierce_up_2y"
MA_PIERCE_2Y_HITS = "ma_cluster_pierce_2y_hits"
MA_PIERCE_10D_METRIC = "ma_cluster_pierce_10d_no120_2y"
MA_PIERCE_10D_HITS = "ma_cluster_pierce_10d_hits"
MA_PIERCE_LABELS = {
    MA_PIERCE_10D_METRIC: "近两年：10日放平粘连0.8%·放量穿线（不含MA120）",
    MA_PIERCE_METRIC: "单K：阳线实体上穿除年线外全部均线（MA5/10/20/30/60/120）",
    MA_PIERCE_2Y_METRIC: "近两年：MA10/20/30走平粘连时，放量大阳实体上穿除年线外全部均线",
}
MA_PIERCE_METRICS = set(MA_PIERCE_LABELS)
MA_PIERCE_WINDOWS = (5, 10, 20, 30, 60, 120)
CLUSTER_WINDOWS = (10, 20, 30)

FLAT_SLOPE_MAX_PERCENT = 0.10
DAILY_SLOPE_MAX_PERCENT = 0.20
ENTANGLE_SPREAD_MAX_PERCENT = 2.0
VOLUME_MULTIPLE = 2.0
TWO_YEARS = pd.Timedelta(days=730)


def uses_ma_pierce(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return value.get("metric") in MA_PIERCE_METRICS or any(
            uses_ma_pierce(item) for item in value.values()
        )
    return isinstance(value, list) and any(uses_ma_pierce(item) for item in value)


def ma_pierce_features(rows: list[dict]) -> list[dict]:
    """逐行判定；rows 顺序任意，只使用每行自带的 open/close 与均线值。

    任一参与均线缺失（如上市不足 120 日时 ma_120 为空）记为 None，
    由条件树的三值逻辑按 unknown 处理，不当作未穿透。
    """
    output = []
    for row in rows:
        opening, closing = row.get("open"), row.get("close")
        averages = [row.get(f"ma_{window}") for window in MA_PIERCE_WINDOWS]
        if any(value is None for value in (opening, closing, *averages)):
            output.append({MA_PIERCE_METRIC: None})
            continue
        pierced = closing > opening and opening < min(averages) and closing > max(averages)
        output.append({MA_PIERCE_METRIC: bool(pierced)})
    return output


def ma_pierce_2y_scan(frame: pd.DataFrame, *, ten_day=False) -> pd.Series:
    """逐行判定完整形态：实体穿线 + MA10/20/30 走平粘连 + 放量，返回布尔序列。

    frame 需按时间升序，包含列 feature_date、open、close、volume、volume_ma_20
    与 ma_5/10/20/30/60/120。任一必需值缺失的行不构成命中（False）。
    """
    windows = (5, 10, 20, 30, 60) if ten_day else MA_PIERCE_WINDOWS
    duration = 10 if ten_day else 5
    opening = frame["open"].astype(float)
    closing = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    averages = frame[[f"ma_{window}" for window in windows]].astype(float)
    pierced = (
        (closing > opening)
        & (opening < averages.min(axis=1))
        & (closing > averages.max(axis=1))
    )
    cluster = pd.concat(
        [frame[f"ma_{window}"].astype(float) for window in CLUSTER_WINDOWS], axis=1
    )
    spread = (cluster.max(axis=1) / cluster.min(axis=1) - 1) * 100
    slopes = pd.DataFrame(
        {
            window: frame[f"ma_{window}"].astype(float).shift(1).rolling(5, min_periods=5).apply(
                _normalized_slope_abs, raw=True,
            )
            for window in CLUSTER_WINDOWS
        },
        index=frame.index,
    )
    # At t, slopes contains the fit ending at t-1; its last five values
    # therefore cover rolling fits ending at t-5 through t-1, never t.
    daily_max = slopes.rolling(duration, min_periods=duration).max()
    if ten_day:
        slopes = cluster.shift(1).rolling(10, min_periods=10).apply(_normalized_slope_abs, raw=True)
    flat = ((slopes <= FLAT_SLOPE_MAX_PERCENT).all(axis=1)
            & (daily_max <= DAILY_SLOPE_MAX_PERCENT).all(axis=1))
    entangled = (spread.where(cluster.notna().all(axis=1)).shift(1).rolling(10, min_periods=10).max() <= 0.8
                 if ten_day else spread <= ENTANGLE_SPREAD_MAX_PERCENT)
    voluminous = volume >= VOLUME_MULTIPLE * frame["volume_ma_20"].astype(float)
    required = ["open", "close", "volume", "volume_ma_20", *(f"ma_{w}" for w in windows)]
    complete = frame[required].notna().all(axis=1)
    return (pierced & flat & entangled & voluminous & complete).fillna(False)


def ma_pierce_2y_hits(frame: pd.DataFrame, *, ten_day=False) -> list[dict]:
    """扫描窗口内所有满足完整形态的日期（升序）。"""
    result = ma_pierce_2y_scan(frame, ten_day=ten_day)
    hits = []
    for position in frame.index[result]:
        row = frame.loc[position]
        hits.append({
            **({"start_date": str(pd.Timestamp(frame.iloc[frame.index.get_loc(position)-10]["feature_date"]).date()),
                "end_date": str(pd.Timestamp(frame.iloc[frame.index.get_loc(position)-1]["feature_date"]).date())} if ten_day else {}),
            "date": str(pd.Timestamp(row["feature_date"]).date()),
            "open": round(float(row["open"]), 3),
            "close": round(float(row["close"]), 3),
        })
    return hits


def ma_pierce_2y_exists(frame: pd.DataFrame, *, ten_day=False) -> pd.Series:
    """逐行：截至该行（含）的过去约两个自然年内是否出现过完整形态。

    供回测逐 bar 评估使用；窗口长度 TWO_YEARS，dates 需升序。
    """
    pattern = ma_pierce_2y_scan(frame, ten_day=ten_day).to_numpy(dtype=bool)
    dates = pd.to_datetime(frame["feature_date"]).to_numpy()
    exists = [False] * len(pattern)
    low, count = 0, 0
    for index in range(len(pattern)):
        boundary = dates[index] - TWO_YEARS
        while low <= index and dates[low] < boundary:
            if pattern[low]:
                count -= 1
            low += 1
        if pattern[index]:
            count += 1
        exists[index] = count > 0
    return pd.Series(exists, index=frame.index)
