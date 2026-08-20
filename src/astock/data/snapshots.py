from copy import deepcopy

from astock.domain.market import MarketSnapshot


def overlay_snapshot(history: list[dict], snapshot: MarketSnapshot) -> list[dict]:
    previous = deepcopy(history)
    live = dict(previous[0]) if previous else {}
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
    if snapshot.volume_ratio is not None:
        live["volume_ratio_20"] = snapshot.volume_ratio
    elif len(previous) >= 20:
        volumes = [row.get("volume") for row in previous[:20]]
        live["volume_ratio_20"] = (
            snapshot.volume_shares / (sum(volumes) / 20)
            if all(value is not None for value in volumes) and sum(volumes) > 0
            else None
        )
    return [live, *previous]
