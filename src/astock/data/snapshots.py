from copy import deepcopy

from astock.domain.market import MarketSnapshot


def overlay_snapshot(history: list[dict], snapshot: MarketSnapshot) -> list[dict]:
    previous = deepcopy([
        row for row in history
        if str(row["feature_date"]) < snapshot.timestamp.date().isoformat()
    ])
    live = {key: None for key in history[0]} if history else {}
    for key in ("symbol", "name", "board", "timeframe", "feature_version"):
        if history and key in history[0]:
            live[key] = history[0][key]
    live.update(
        {
            "feature_date": snapshot.timestamp.date(),
            "open": snapshot.open,
            "high": snapshot.high,
            "low": snapshot.low,
            "close": snapshot.price,
            "volume": snapshot.volume_shares,
            "amount": snapshot.amount_cny,
            "turnover_rate": snapshot.turnover_rate,
            "volume_ratio": snapshot.volume_ratio,
            "pe_ratio": snapshot.pe_ratio,
            "pb_ratio": snapshot.pb_ratio,
            "total_market_cap": snapshot.total_market_cap,
            "float_market_cap": snapshot.float_market_cap,
        }
    )
    if snapshot.previous_close:
        live["return_1"] = round(
            (snapshot.price / snapshot.previous_close - 1) * 100, 12
        )
    else:
        live["return_1"] = None
    for window in (3, 5, 10, 20, 60, 120, 250):
        baseline = previous[window - 1].get("close") if len(previous) >= window else None
        live[f"return_{window}"] = (
            (snapshot.price / baseline - 1) * 100 if baseline else None
        )
    for window in (5, 10, 20, 30, 60, 120, 250):
        prior_closes = [row.get("close") for row in previous[: window - 1]]
        live[f"ma_{window}"] = (
            (snapshot.price + sum(prior_closes)) / window
            if len(prior_closes) == window - 1 and all(value is not None for value in prior_closes)
            else None
        )
    for window in (5, 20, 60):
        volumes = [row.get("volume") for row in previous[:window - 1]]
        live[f"volume_ma_{window}"] = (
            (snapshot.volume_shares + sum(volumes)) / window
            if len(volumes) == window - 1 and all(value is not None for value in volumes)
            else None
        )
    average_volume = live["volume_ma_20"]
    live["volume_ratio_20"] = (
        snapshot.volume_shares / average_volume if average_volume else None
    )
    return [live, *previous]
