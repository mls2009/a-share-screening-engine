"""Verify only potential price breakouts against local raw bars and dated limits."""
from collections import defaultdict
from datetime import date

import pandas as pd

from astock.data.limit_colors import limit_state
from .strategies import valid


def attach_turtle_limits(con, bar_store, histories, window, *, latest=False):
    if bar_store is None:
        return
    candidates = defaultdict(dict)
    for symbol, rows in histories.items():
        indices = [len(rows)-1] if latest else range(window, len(rows))
        for i in indices:
            if i < window:
                continue
            row = rows[i]
            prices = [r.get('high') for r in rows[i-window:i]]
            if (valid(row.get('close')) and valid(rows[i-1].get('close'))
                    and all(valid(p) and p > 0 for p in prices)
                    and row['close'] > max(prices) and row['close'] > rows[i-1]['close']):
                candidates[symbol][row['date']] = row
    for symbol, days in candidates.items():
        statuses = {str(d): (suspended, upper) for d, suspended, upper in con.execute(
            'select trade_date,is_suspended,limit_up from security_status '
            'where symbol=? and trade_date between ? and ?',
            [symbol, min(days), max(days)]).fetchall()}
        for year in {date.fromisoformat(d).year for d in days}:
            path = bar_store.root / 'timeframe=1d' / f'year={year}' / f'{symbol}.parquet'
            if not path.exists():
                continue
            frame = pd.read_parquet(path, columns=['timestamp', 'adjustment', 'close', 'is_final'])
            for timestamp, adjustment, close, final in frame.itertuples(index=False, name=None):
                day = str(timestamp)[:10]
                suspended, upper = statuses.get(day, (True, None))
                if (day in days and adjustment == 'none' and final and not suspended
                        and valid(close) and close > 0 and valid(upper) and upper > 0):
                    days[day]['limit_state'] = limit_state(close, upper, None)
