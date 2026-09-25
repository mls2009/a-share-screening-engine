"""Historical Sequoia signals, using bounded windows and each day's universe."""
from bisect import bisect_right
from collections import defaultdict

import pandas as pd

from .strategies import BY_ID, evaluate, rps_scores, valid


def scan_history(con, config, end, progress, bar_store=None, *, scope_symbols=None, strict_volume=False):
    start = (pd.Timestamp(config.as_of)-pd.DateOffset(years=int(config.period[0]))).date()
    securities = con.execute("""select symbol,name,listed_on,delisted_on,is_listed
        from symbols where instrument_type='stock'""").fetchall()
    securities = {s: (name, listed, delisted, active) for s, name, listed, delisted, active in securities}
    scope = set(securities)
    if config.scope == 'watchlist':
        scope &= {r[0] for r in con.execute('select symbol from watchlist').fetchall()}
        if config.group_id:
            scope &= {r[0] for r in con.execute('select symbol from watchlist_group_members where cast(group_id as varchar)=?', [config.group_id]).fetchall()}
    if scope_symbols is not None:
        scope &= set(scope_symbols)
    # RPS always needs the full market; other strategies only load the requested scope.
    read_symbols = list(securities if 'rps' in config.strategies else scope)
    histories = defaultdict(list)
    dates = set()
    keys = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
    rows = con.execute("""select symbol,feature_date,open,high,low,close,volume,amount from (
        select *,row_number() over(partition by symbol order by feature_date desc) as rn
        from market_features where timeframe='1d' and feature_version='v1'
          and symbol in (select unnest(?)) and feature_date < ?)
        where rn<=251
        union all
        select symbol,feature_date,open,high,low,close,volume,amount from market_features
        where timeframe='1d' and feature_version='v1' and symbol in (select unnest(?))
          and feature_date between ? and ? order by symbol,feature_date""",
        [read_symbols, start, read_symbols, start, end]).fetchall()
    for symbol, day, *values in rows:
        histories[symbol].append(dict(zip(keys, [day.isoformat(), *values])))
        if day >= start:
            dates.add(day.isoformat())
    del rows
    if 'turtle' in config.strategies:
        from .limits import attach_turtle_limits
        attach_turtle_limits(con, bar_store, histories,
                             int(config.parameters.get('turtle', {}).get('window', 20)))
    stamps = {s: [r['date'] for r in history] for s, history in histories.items()}
    stats = {s: dict(id=s, name=BY_ID[s]['name'], matched=0, rejected=0, unknown=0, examples=[]) for s in config.strategies}
    matches, seen = {}, set()
    active_turtle = {}
    days = sorted(dates)
    for number, day in enumerate(days):
        current = {}
        for symbol, history in histories.items():
            _, listed, delisted, active = securities[symbol]
            if (listed and str(listed)>day) or (delisted and str(delisted)<=day) or (not active and not delisted):
                continue
            index = bisect_right(stamps[symbol], day)
            if index and history[index-1]['date']==day:
                current[symbol] = history[max(0,index-251):index]
        scores = rps_scores(current) if 'rps' in config.strategies else {}
        for symbol in scope & current.keys():
            seen.add(symbol)
            history = current[symbol]
            matched = []
            for strategy in config.strategies:
                result = evaluate(strategy, history, config.parameters.get(strategy), rps=scores.get(symbol), strict_volume=strict_volume)
                key = {'true':'matched', 'false':'rejected', 'unknown':'unknown'}[result['result']]
                stats[strategy][key] += 1
                if key == 'matched':
                    matched.append(result)
                if key == 'unknown' and len(stats[strategy]['examples'])<5:
                    stats[strategy]['examples'].append(dict(symbol=symbol, reason=f"{day}：{result['reason']}"))
            turtle_continuation = symbol in active_turtle
            if turtle_continuation:
                episode = active_turtle[symbol]
                close = history[-1]['close']
                if valid(close) and close > 0:
                    if close < episode['breakout_level']:
                        episode.update(active=False, ended_on=day)
                        active_turtle.pop(symbol)
                    else:
                        episode.update(end_date=day, days=episode['days']+1)
                # A missing quote cannot establish a close below the fixed level.
            if len(matched) < config.minimum_matches:
                continue
            match = matches.setdefault(symbol, dict(symbol=symbol, name=securities[symbol][0], groups=[]))
            if config.minimum_matches > 1:
                match.setdefault('confluence_dates', []).append(day)
            match['last_match_date'] = day
            for result in matched:
                strategy = result['id']
                if strategy == 'turtle' and turtle_continuation:
                    continue
                group = next((g for g in match['groups'] if g['id']==strategy), None)
                if group is None:
                    group = dict(id=strategy, name=result['name'], checks=[], occurrences=[])
                    match['groups'].append(group)
                occurrence = dict(date=day, checks=result['checks'])
                if strategy == 'turtle':
                    occurrence.update(end_date=day, days=1, active=True,
                                      breakout_level=result['checks'][0]['expected'])
                    active_turtle[symbol] = occurrence
                group['occurrences'].append(occurrence)
                group['checks'] = result['checks']
        if number % 10 == 0 or number == len(days)-1:
            progress(10+int(85*(number+1)/max(1,len(days))), f"历史逐日识别 {day} · {number+1}/{len(days)} 个交易日")
    for strategy, stat in stats.items():
        stat['signal_count'] = sum(len(g['occurrences']) for m in matches.values() for g in m['groups'] if g['id'] == strategy)
    for symbol, match in matches.items():
        history = histories[symbol]
        close = history[-1]['close']
        previous = history[-2]['close'] if len(history)>1 else None
        match.update(close=close, change_percent=(close/previous-1)*100 if close and previous else None,
                     quote_date=history[-1]['date'], hit_count=sum(len(g['occurrences']) for g in match['groups']))
    return dict(matches=sorted(matches.values(), key=lambda m:m['symbol']), groups=list(stats.values()),
                match_count=len(matches), universe_size=len(seen), range_start=str(start),
                observation_days=len(days), statistics_unit='股票×交易日',
                listing_date_unknown=sum(securities[s][1] is None for s in seen))
