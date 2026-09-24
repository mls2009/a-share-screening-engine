"""均线束穿线信号：单根阳线的实体自下而上穿过除年线外全部均线。

穿透判定只依赖当日已完成的 OHLC 与当日均线值：
  阳线（close > open）且 open < min(可用的短期均线) 且 close > max(可用的短期均线)。
均线取 MA5/MA10/MA20/MA30/MA60/MA120（年线 MA250 不参与）。
走平、粘连、放量由条件树里的既有指标组合表达，本指标不重复约束。
"""
MA_PIERCE_METRIC = "ma_cluster_pierce_up"
MA_PIERCE_LABELS = {
    MA_PIERCE_METRIC: "单K：阳线实体上穿除年线外全部均线（MA5/10/20/30/60/120）",
}
MA_PIERCE_METRICS = set(MA_PIERCE_LABELS)
MA_PIERCE_WINDOWS = (5, 10, 20, 30, 60, 120)


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
