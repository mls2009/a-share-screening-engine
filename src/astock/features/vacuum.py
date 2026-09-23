"""Causal daily price-vacuum detection. No future bars enter a day's signal."""
import numpy as np
import pandas as pd

VACUUM_METRICS = {
    "vacuum_reentry", "vacuum_lower", "vacuum_upper", "vacuum_drop",
    "vacuum_days", "vacuum_efficiency", "vacuum_break_age",
    "vacuum_reentry_ma120_within_250", "vacuum_volume_ratio",
}


def uses_vacuum(value) -> bool:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return value.get("metric") in VACUUM_METRICS or any(uses_vacuum(v) for v in value.values())
    return isinstance(value, list) and any(uses_vacuum(v) for v in value)


def vacuum_features(rows: list[dict]) -> list[dict]:
    """Input is chronological OHLC; output has matching order, one snapshot per bar."""
    n = len(rows)
    if not n:
        return []
    high, low, close = (np.array([r.get(key, np.nan) for r in rows], dtype=float)
                        for key in ("high", "low", "close"))
    highs = pd.Series(high)
    lows = pd.Series(low)
    peak = highs.rolling(20).max().to_numpy()
    volume = np.array([r.get("volume", r.get("volume_shares", np.nan)) for r in rows], dtype=float)
    unknown_candidates = set()
    candidates = {}
    for start in range(19, n):
        if not np.isfinite(peak[start]) or high[start] < peak[start]:
            continue
        end = start
        while end + 1 < n and end - start + 1 < 5 and close[end + 1] <= close[end] * .98:
            end += 1
        span = end - start + 1
        if span < 3:
            continue
        # A short segment needs the next closed bar to establish its endpoint.
        confirmed = end if span == 5 else end + 1
        if confirmed >= n:
            continue
        distance = np.abs(np.diff(close[start:end + 1])).sum()
        drop = (high[start] - low[end]) / high[start]
        efficiency = (close[start] - close[end]) / distance if distance > 0 else 0
        if drop <= .25 or efficiency < .8 or low[end] >= low[start:end].min():
            continue
        if any(high[i:i + 3].max() / low[i:i + 3].min() - 1 <= .03
               for i in range(start, end - 1)):
            continue
        reference = volume[max(0, start - 20):start]
        segment = volume[start:end + 1]
        if len(reference) < 20 or not np.isfinite(reference).all() or not np.isfinite(segment).all() or reference.mean() <= 0:
            unknown_candidates.add(confirmed)
            continue
        volume_ratio = float(segment.mean() / reference.mean())
        if volume_ratio > .8:
            continue
        candidates.setdefault(confirmed, []).append(dict(
            start=start, end=end, confirmed=confirmed, upper=float(high[start]), lower=float(low[end]),
            drop=float(drop * 100), efficiency=float(efficiency * 100), days=span,
            broken=None, below=0, volume_ratio=volume_ratio))
    ma120 = pd.Series(close).rolling(120).mean().to_numpy()
    active = []
    annual_hits = []
    unknown_days = []
    output = []
    missing_candidate_seen = False
    for index, row in enumerate(rows):
        missing_candidate_seen = missing_candidate_seen or index in unknown_candidates
        matched = []
        remaining = []
        # The confirmation bar is outside the frozen segment and may start the departure.
        active.extend(candidates.get(index, []))
        for zone in active:
            if index <= zone["end"]:
                remaining.append(zone)
                continue
            below_before = zone["below"]
            zone["below"] = below_before + 1 if close[index] < zone["lower"] else 0
            if zone["broken"] is None and close[index] <= zone["lower"] * .95:
                zone["broken"] = index
            broken = zone["broken"]
            if broken is None:
                remaining.append(zone)
                continue
            age = index - broken
            if age > 20 or close[index] >= zone["upper"]:
                continue
            if close[index - 1] <= zone["lower"] < close[index] < zone["upper"]:
                if age >= 3 and below_before >= 5:
                    matched.append(zone)
                # Any return consumes this departure, including an immediate bounce.
                continue
            remaining.append(zone)
        active = remaining
        selected = max(matched or active, key=lambda z: z["confirmed"], default=None)
        result = {key: None for key in VACUUM_METRICS}
        result["vacuum_reentry"] = True if matched else (None if index < 22 or missing_candidate_seen else False)
        if selected:
            result.update(vacuum_volume_ratio=selected["volume_ratio"], vacuum_lower=selected["lower"], vacuum_upper=selected["upper"],
                          vacuum_drop=selected["drop"], vacuum_days=selected["days"],
                          vacuum_efficiency=selected["efficiency"],
                          vacuum_break_age=index - selected["broken"] if selected["broken"] is not None else None)
            stamp = lambda i: str(rows[i].get("feature_date", rows[i].get("timestamp")))[:10]
            result["vacuum_zone"] = {"start": stamp(selected["start"]), "end": stamp(selected["end"]),
                                     "confirmed": stamp(selected["confirmed"]), "upper": selected["upper"],
                                     "lower": selected["lower"], "volume_ratio": selected["volume_ratio"], "method": "daily_volume_proxy", "break_date": stamp(selected["broken"]) if selected["broken"] is not None else None}
        signal = result["vacuum_reentry"]
        if signal is None or (signal and not np.isfinite(ma120[index])):
            unknown_days.append(index)
        if signal and np.isfinite(ma120[index]) and close[index] > ma120[index]:
            # Freeze the signal-day area and MA value for historical chart evidence.
            annual_hits.append({"index": index, "date": str(row.get("feature_date", row.get("timestamp")))[:10],
                                "close": float(close[index]), "ma120": float(ma120[index]),
                                "zone": dict(result["vacuum_zone"])})
        annual_hits = [hit for hit in annual_hits if hit["index"] > index - 250]
        unknown_days = [day for day in unknown_days if day > index - 250]
        result["vacuum_reentry_ma120_within_250"] = True if annual_hits else (
            None if index < 249 or unknown_days else False)
        result["vacuum_year_hits"] = [{k: v for k, v in hit.items() if k != "index"} for hit in annual_hits]
        output.append(result)
    return output
