"""Historical daily consolidation shapes; no breakout or volume requirement."""
import numpy as np
import pandas as pd

SHAPE_LABELS = {
    'shape_ascending_within_2y': '近两年上升三角形（20～120日，不要求突破）',
    'shape_descending_within_2y': '近两年下降三角形（20～120日，不要求突破）',
    'shape_range_within_2y': '近两年震荡区间（20～120日，不要求突破）',
}


def uses_shapes(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if isinstance(value, dict):
        return value.get('metric') in SHAPE_LABELS or any(uses_shapes(v) for v in value.values())
    return isinstance(value, list) and any(uses_shapes(v) for v in value)


def _boundary(values, indices, start, end, side, tolerance):
    """Choose a pivot-pair slope and move it outward to contain all wicks."""
    x = np.arange(end-start+1)
    best = None
    for a in range(len(indices)-1):
        for b in range(a+1, len(indices)):
            left, right = indices[a], indices[b]
            slope = (values[right, side]-values[left, side])/(right-left)
            residual = values[start:end+1, side]-slope*x
            intercept = float(max(residual) if side == 0 else min(residual))
            error = max(abs(values[k, side]-(intercept+slope*(k-start))) for k in indices)
            if error <= tolerance and (best is None or error < best[0]):
                best = (error, slope, intercept)
    return best


def _pattern(values, pivots, dates, confirmed):
    start, end = pivots[0][0], pivots[-1][0]
    length = end-start
    if not 20 <= length+1 <= 120:
        return None
    segment = values[start:end+1]
    if not np.isfinite(segment).all():
        return None
    height = float(max(segment[:, 0])-min(segment[:, 1]))
    if height <= 0:
        return None
    hp = [k for k, side in pivots if side == 0]
    lp = [k for k, side in pivots if side == 1]
    upper = _boundary(values, hp, start, end, 0, height*.15)
    lower = _boundary(values, lp, start, end, 1, height*.15)
    if upper is None or lower is None:
        return None
    _, hs, hi = upper
    _, ls, li = lower
    width = hi-li
    hmove, lmove = hs*length, ls*length
    final_width = width+hmove-lmove
    if min(width, final_width) <= 0:
        return None
    flat = height*.10
    kind = None
    if abs(hmove) <= flat and abs(lmove) <= flat:
        kind = 'range'
    elif abs(hmove) <= flat and lmove > flat and final_width < width:
        kind = 'ascending'
    elif abs(lmove) <= flat and hmove < -flat and final_width < width:
        kind = 'descending'
    if kind is None:
        return None
    return dict(kind=kind, start_date=str(dates[start]), end_date=str(dates[end]),
                confirmed_date=str(dates[confirmed]), bars=length+1,
                upper_start=float(hi), upper_end=float(hi+hmove),
                lower_start=float(li), lower_end=float(li+lmove),
                high_points=[dict(date=str(dates[k]), price=float(values[k, 0])) for k in hp],
                low_points=[dict(date=str(dates[k]), price=float(values[k, 1])) for k in lp])


def chart_shape_features(rows, target_dates=None):
    """Independent adaptation of Trendoscope's documented pivot-pair approach.

    Multiple confirmed swing scales, alternating 5/6 pivots, enclosing boundaries.
    No future breakout requirement; prior observation snapshots never mutate.
    """
    dates = [pd.Timestamp(r.get('feature_date', r.get('timestamp'))).date() for r in rows]
    values = np.array([[r.get('high'), r.get('low')] for r in rows], dtype=float)
    swings = {radius: [] for radius in (2, 5, 10, 20)}
    hits, output = [], []
    first = 0
    if target_dates:
        cutoff = (pd.Timestamp(min(target_dates))-pd.DateOffset(years=2)).date()
        first = next((i for i, d in enumerate(dates) if d >= cutoff), len(rows))
    for i, stamp in enumerate(dates):
        for radius, pivots in swings.items():
            j = i-radius
            if j < max(radius, first) or not np.isfinite(values[j-radius:i+1]).all():
                continue
            high = values[j, 0] > max(values[j-radius:j, 0]) and values[j, 0] >= max(values[j+1:i+1, 0])
            low = values[j, 1] < min(values[j-radius:j, 1]) and values[j, 1] <= min(values[j+1:i+1, 1])
            # An outside bar has no knowable intraday ordering of its two extremes.
            if high == low:
                continue
            side = 0 if high else 1
            if pivots and pivots[-1][1] == side:
                previous = pivots[-1][0]
                more_extreme = values[j, side] > values[previous, side] if high else values[j, side] < values[previous, side]
                if not more_extreme:
                    continue
                pivots[-1] = (j, side)
            else:
                pivots.append((j, side))
            del pivots[:-6]
            for count in (6, 5):
                if len(pivots) < count:
                    continue
                hit = _pattern(values, pivots[-count:], dates, i)
                if hit is None:
                    continue
                # Merge overlapping same-kind pieces only if the combined
                # boundaries still validate; never mutate prior snapshots.
                merged = False
                for n, old in enumerate(hits):
                    if old['kind'] != hit['kind'] or old['end_date'] < hit['start_date']:
                        continue
                    points = {(dates.index(pd.Timestamp(p['date']).date()), side)
                              for source in (old, hit) for side, key in ((0, 'high_points'), (1, 'low_points'))
                              for p in source[key]}
                    combined = _pattern(values, sorted(points), dates, i)
                    if combined is not None and combined['kind'] == hit['kind']:
                        hits[n] = combined
                    merged = True
                    break
                if not merged:
                    hits.append(hit)
                break
        cutoff = str((pd.Timestamp(stamp)-pd.DateOffset(years=2)).date())
        hits = [h for h in hits if h['start_date'] >= cutoff]
        result = {key: any(h['kind'] == key.split('_')[1] for h in hits) if i >= 23 else None for key in SHAPE_LABELS}
        result['chart_shape_hits'] = list(hits)
        output.append(result)
    return output
