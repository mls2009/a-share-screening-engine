"""同一长期均线连续两次20日确认后，识别第三次起的下影回访。"""
import numpy as np
import pandas as pd

MA_SUPPORT_METRIC = 'ma120_250_repeat_support_2y'
MA_SUPPORT_HITS = 'ma120_250_repeat_support_hits'


def uses_ma_support(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if isinstance(value, dict):
        return value.get('metric') == MA_SUPPORT_METRIC or any(uses_ma_support(v) for v in value.values())
    return isinstance(value, list) and any(uses_ma_support(v) for v in value)


def support_hits(frame):
    """仅传入两年窗口内升序日线；跳过前20根，不读取未来数据。"""
    dates = [str(pd.Timestamp(d).date()) for d in frame['feature_date']]
    opening = frame['open'].to_numpy(dtype=float)
    highs = frame['high'].to_numpy(dtype=float)
    closing = frame['close'].to_numpy(dtype=float)
    lows = frame['low'].to_numpy(dtype=float)
    hits = []
    for window in (120, 250):
        ma = frame[f'ma_{window}'].to_numpy(dtype=float)
        if window == 120:
            touch = np.isfinite(ma) & (ma > 0) & (lows <= np.round(ma, 2)) & (highs >= np.round(ma, 2))
        else:
            touch = np.isfinite(ma) & (ma > 0) & (np.abs(lows / ma - 1) <= .02 + 1e-12)
        above = np.isfinite(closing) & np.isfinite(ma) & (closing > ma)
        confirmed = []
        pending = None
        for end in range(20, len(frame)):
            if not above[end]:
                confirmed = []
                pending = None
                continue
            if pending is not None:
                if end == pending + 20:
                    confirmed.append(pending)
                    pending = None
                # A confirmation-day touch cannot begin another support.
                continue
            if len(confirmed) < 2:
                if touch[end]:
                    pending = end
                continue
            ready = confirmed[1] + 20
            matches = []
            for size in (1, 2):
                start = end - size + 1
                if start <= ready:
                    continue
                low_index = start + int(np.argmin(lows[start:end+1]))
                lower = min(opening[start], closing[end]) - lows[low_index]
                body = abs(closing[end] - opening[start])
                if touch[low_index] and lower > 0 and lower + 1e-12 >= body:
                    matches.append((size, start))
            if matches:
                supports = [{'date': dates[i], 'confirmation_start': dates[i+1],
                             'confirmation_end': dates[i+20]} for i in confirmed]
                hits.append({'date': dates[end], 'start_date': dates[min(m[1] for m in matches)],
                             'first_date': dates[confirmed[0]], 'supports': supports, 'ma': window,
                             'types': ['单K' if m[0] == 1 else '双K' for m in matches]})
    return sorted(hits, key=lambda h: (h['date'], h['ma']))
