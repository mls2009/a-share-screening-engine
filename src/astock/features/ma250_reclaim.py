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
