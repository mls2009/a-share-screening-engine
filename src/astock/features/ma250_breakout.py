"""Two-year annual-MA breakout signals with verified closing-limit exemptions."""
import numpy as np
import pandas as pd

from astock.data.limit_colors import limit_state

METRIC = 'ma250_volume_breakout_2y'
HITS = 'ma250_volume_breakout_hits'


def uses_ma250_breakout(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if isinstance(value, dict):
        return value.get('metric') == METRIC or any(uses_ma250_breakout(v) for v in value.values())
    return isinstance(value, list) and any(uses_ma250_breakout(v) for v in value)


def _candidates(frame, boundary):
    if frame.empty:
        return []
    closing = frame['close'].astype(float)
    average = frame['ma_250'].astype(float)
    volume = frame['volume'].astype(float)
    volume_average = volume.where(volume >= 0).shift(1).rolling(20, min_periods=20).mean()
    amplitude = (frame['high'].astype(float) - frame['low'].astype(float)) / closing.shift(1) * 100
    cross = (closing > average) & (closing.shift(1) <= average.shift(1))
    cross &= (average > 0) & (average.shift(1) > 0) & (closing.shift(1) > 0)
    cross &= np.isfinite(closing) & np.isfinite(average) & np.isfinite(closing.shift(1)) & np.isfinite(average.shift(1))
    candidates = []
    for index in np.flatnonzero(cross.to_numpy()):
        day = str(pd.Timestamp(frame.iloc[index]['feature_date']).date())
        if day < str(boundary):
            continue
        mean, amount, width = volume_average.iloc[index], volume.iloc[index], amplitude.iloc[index]
        ratio = float(amount / mean) if np.isfinite(mean) and mean > 0 and np.isfinite(amount) else None
        candidates.append({
            'date': day, 'close': float(closing.iloc[index]), 'ma250': float(average.iloc[index]),
            'volume': float(amount) if np.isfinite(amount) else None,
            'volume_average_20': float(mean) if np.isfinite(mean) else None,
            'volume_ratio': ratio, 'amplitude': float(width) if np.isfinite(width) else None,
        })
    return candidates


def _select(candidates, limit_days):
    hits = []
    for row in candidates:
        limit = row['date'] in limit_days
        ordinary = (row['volume_ratio'] is not None and row['volume_ratio'] >= 2
                    and row['amplitude'] is not None and row['amplitude'] > 5 + 1e-9)
        if limit or ordinary:
            hits.append({**row, 'branch': '涨停突破' if limit else '放量突破'})
    return hits


def breakout_hits(frame, boundary, limit_days=()):
    return _select(_candidates(frame, boundary), set(limit_days))


def _confirmed_limit_days(con, symbol, days):
    if not days:
        return set()
    statuses = {str(day): upper for day, suspended, upper in con.execute(
        'select trade_date,is_suspended,limit_up from security_status '
        'where symbol=? and trade_date between ? and ?', [symbol, min(days), max(days)]
    ).fetchall() if not suspended and upper is not None}
    wanted = set(days) & statuses.keys()
    limits = set()
    for year in sorted({day[:4] for day in wanted}):
        path = con.path.parent / 'bars' / 'timeframe=1d' / f'year={year}' / f'{symbol}.parquet'
        if not path.exists():
            continue
        raw = pd.read_parquet(path, columns=['timestamp', 'adjustment', 'close', 'is_final'])
        for stamp, adjustment, close, final in raw.itertuples(index=False, name=None):
            day = str(stamp)[:10]
            if day in wanted and adjustment == 'none' and final and np.isfinite(close) and close > 0:
                if limit_state(close, statuses[day], None) == 'up':
                    limits.add(day)
    return limits


def attach_breakouts(con, histories, end, feature_version='v1', progress=None):
    boundary = (pd.Timestamp(end) - pd.DateOffset(years=2)).date()
    symbols = [symbol for symbol, rows in histories.items() if rows]
    for offset in range(0, len(symbols), 64):
        batch = symbols[offset:offset + 64]
        cursor = con.execute(
            """with history as (
                select symbol,feature_date,high,low,close,volume,ma_250,
                       lead(feature_date,20) over (partition by symbol order by feature_date) next_date
                from market_features where symbol in (select unnest(?)) and timeframe='1d'
                  and feature_version=? and feature_date<=?
            ) select symbol,feature_date,high,low,close,volume,ma_250 from history
              where feature_date>=? or next_date>=? or next_date is null order by symbol,feature_date""",
            [batch, feature_version, end, boundary, boundary])
        records = {symbol: [] for symbol in batch}
        for symbol, day, high, low, close, volume, average in cursor.fetchall():
            records[symbol].append(dict(feature_date=day, high=high, low=low, close=close, volume=volume, ma_250=average))
        for symbol, rows in records.items():
            candidates = _candidates(pd.DataFrame(rows), boundary)
            hits = _select(candidates, _confirmed_limit_days(con, symbol, [row['date'] for row in candidates]))
            histories[symbol][0].update({METRIC: bool(hits), HITS: hits})
        if progress:
            progress('计算年线放量／涨停突破', min(offset + 64, len(symbols)), len(symbols))
