"""Same-day Sequoia confluence with MA120, over two calendar years."""
from math import isfinite
from types import SimpleNamespace

import pandas as pd

from astock.sequoia.history import scan_history
from astock.storage.bars import BarStore

METRIC = 'sequoia_triple_ma120_within_2y'
HITS = 'sequoia_triple_ma120_hits'
METRIC_NO_RPS = 'sequoia_double_ma120_within_2y'
HIT_KEYS = {METRIC: HITS, METRIC_NO_RPS: 'sequoia_double_ma120_hits'}


def ma120_branch(opening, close, average):
    if not all(isinstance(v, (int, float)) and isfinite(v) and v > 0
               for v in (opening, close, average)):
        return None
    if opening <= average < close:
        return '实体上穿'
    if average < opening <= average * 1.10:
        return '开盘在MA120上方10%以内'
    return None


def select_hits(dates, quotes, as_of):
    start = str((pd.Timestamp(as_of) - pd.DateOffset(years=2)).date())
    hits = []
    for day in sorted(set(dates)):
        row = quotes.get(day, {})
        branch = ma120_branch(row.get('open'), row.get('close'), row.get('ma_120'))
        if start <= day <= str(as_of) and branch:
            hits.append({'date': day, 'open': row['open'], 'close': row['close'],
                             'ma120': row['ma_120'], 'branch': branch})
    return hits


def attach_confluence(con, histories, as_of, progress, metric=METRIC):
    strategies = ['turtle', 'ma_volume'] + (['rps'] if metric == METRIC else [])
    config = SimpleNamespace(as_of=as_of, period='2y', scope='market', group_id=None,
                             strategies=strategies,
                             minimum_matches=len(strategies), parameters={
                                 'turtle': {'volume_multiple': 2},
                                 'ma_volume': {'volume_multiple': 2}})
    data = scan_history(con, config, as_of, progress,
                        BarStore(con.path.parent / 'bars'), scope_symbols=set(histories), strict_volume=True)
    candidates = {m['symbol']: m['confluence_dates'] for m in data['matches']}
    rows = con.execute('''select symbol,feature_date,open,close,ma_120
        from market_features where timeframe='1d' and feature_version='v1'
        and symbol in (select unnest(?)) and feature_date between ? and ?''',
        [list(candidates), data['range_start'], as_of]).fetchall()
    quotes = {}
    for symbol, day, opening, close, ma120 in rows:
        quotes.setdefault(symbol, {})[str(day)] = {'open': opening, 'close': close, 'ma_120': ma120}
    for symbol, history in histories.items():
        if history:
            hits = select_hits(candidates.get(symbol, []), quotes.get(symbol, {}), as_of)
            history[0][HIT_KEYS[metric]] = hits
            history[0][metric] = bool(hits)
