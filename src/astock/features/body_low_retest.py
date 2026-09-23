"""Two-year independent body-bottom references and first wick-inclusive revisits."""
import math

import pandas as pd


def body_low_retest_features(rows):
    dates = [pd.Timestamp(r.get('feature_date', r.get('timestamp'))).date() for r in rows]
    bodies = [min(r['open'], r['close']) if r.get('open') is not None and r.get('close') is not None else float('nan') for r in rows]
    candidates, output = [], []
    for i, row in enumerate(rows):
        # Five right-hand bars must have closed BEFORE this observation bar.
        j = i - 6
        if j >= 5 and all(math.isfinite(v) for v in bodies[j-5:j+6]):
            if bodies[j] < min(bodies[j-5:j]) and bodies[j] <= min(bodies[j+1:j+6]):
                candidates.append(j)
        cutoff = (pd.Timestamp(dates[i]) - pd.DateOffset(years=2)).date()
        candidates = [k for k in candidates if dates[k] >= cutoff]
        independent = []
        for k in candidates:
            if not independent:
                independent.append(k)
                continue
            previous = independent[-1]
            between = bodies[previous+1:k]
            if between and max(between) > max(bodies[previous], bodies[k]) * 1.05:
                independent.append(k)
            elif bodies[k] < bodies[previous]:
                independent[-1] = k
        chosen = sorted(independent, key=lambda k:(bodies[k],k))[:2]
        levels = [dict(price=bodies[k],date=str(dates[k]),confirmed_date=str(dates[k+5]),
                       lower=bodies[k]*.95,upper=bodies[k]*1.05,rank=rank+1) for rank,k in enumerate(chosen)]
        hits = []
        if len(levels)==2 and i:
            for k, level in zip(chosen,levels,strict=True):
                previous = rows[i-1]
                # A full candle outside the band followed by overlap is a new visit.
                if i-1 > k+5 and (previous['low'] > level['upper'] or previous['high'] < level['lower']):
                    if row['low'] <= level['upper'] and row['high'] >= level['lower']:
                        hits.append(level)
        output.append(dict(body_low_retest=bool(hits) if len(levels)==2 else None,
                           body_low_retest_levels=levels,body_low_retest_hits=hits))
    return output
