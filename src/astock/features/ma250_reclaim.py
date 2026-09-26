"""日线收盘跌破年线后，在随后一至三个交易日内收复。"""
import numpy as np
import pandas as pd

MA250_RECLAIM_METRIC = 'ma250_reclaim_2d_2y'
MA250_RECLAIM_HITS = 'ma250_reclaim_2d_hits'


def uses_ma250_reclaim(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if isinstance(value, dict):
        return value.get('metric') == MA250_RECLAIM_METRIC or any(uses_ma250_reclaim(v) for v in value.values())
    return isinstance(value, list) and any(uses_ma250_reclaim(v) for v in value)


def reclaim_hits(frame, boundary):
    """升序日线，跌破日在两年范围内；允许读取边界前一根确认跌破。"""
    if frame.empty:
        return []
    closing = frame['close'].to_numpy(dtype=float)
    average = frame['ma_250'].to_numpy(dtype=float)
    valid = np.isfinite(closing) & np.isfinite(average) & (average > 0)
    dates = [str(pd.Timestamp(d).date()) for d in frame['feature_date']]
    hits = []
    for start in range(1, len(frame)):
        if dates[start] < str(boundary) or not (valid[start-1] and valid[start]):
            continue
        if not (closing[start-1] > average[start-1] and closing[start] < average[start]):
            continue
        for end in range(start + 1, min(start + 4, len(frame))):
            if not valid[end]:
                break
            if closing[end] > average[end]:
                hits.append({'start_date': dates[start], 'date': dates[end],
                             'recovery_days': end - start, 'break_close': float(closing[start]),
                             'break_ma250': float(average[start]), 'close': float(closing[end]),
                             'ma250': float(average[end])})
                break
    return hits


def shadow_support_hits(frame, boundary):
    """沿用年线宽松下影规则；无需此前两次支撑，同日单K/双K合并记录。"""
    if frame.empty:
        return []
    dates = [str(pd.Timestamp(d).date()) for d in frame['feature_date']]
    opening = frame['open'].to_numpy(dtype=float)
    closing = frame['close'].to_numpy(dtype=float)
    lows = frame['low'].to_numpy(dtype=float)
    average = frame['ma_250'].to_numpy(dtype=float)
    hits = []
    for end in range(len(frame)):
        if not (np.isfinite(average[end]) and average[end] > 0 and closing[end] > average[end]):
            continue
        matches = []
        for size in (1, 2):
            start = end - size + 1
            if start < 0 or dates[start] < str(boundary):
                continue
            if not np.isfinite(lows[start:end+1]).all() or not np.isfinite(opening[start]) or not np.isfinite(closing[end]):
                continue
            low_index = start + int(np.argmin(lows[start:end+1]))
            ma = average[low_index]
            lower = min(opening[start], closing[end]) - lows[low_index]
            body = abs(closing[end] - opening[start])
            if np.isfinite(ma) and ma > 0 and abs(lows[low_index] / ma - 1) <= .02 + 1e-12 and lower > 0 and lower + 1e-12 >= body:
                matches.append((size, start))
        if matches:
            hits.append({'kind': 'shadow_support', 'date': dates[end],
                         'start_date': dates[min(start for _, start in matches)],
                         'types': ['单K' if size == 1 else '双K' for size, _ in matches],
                         'periods': max(size for size, _ in matches),
                         'close': float(closing[end]), 'ma250': float(average[end])})
    return hits
