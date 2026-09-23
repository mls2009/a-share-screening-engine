"""Daily Pinbar context from completed bars; no entry or risk/reward filters."""
from itertools import combinations

import numpy as np
import pandas as pd

from astock.features.body_low_retest import body_low_retest_features

PA_LABELS = {
    'pa_bull_within_250': '裸K：近250交易日内看涨Pinbar完整条件成立（单K/双K）',
    'pa_bear_within_250': '裸K：近250交易日内看跌Pinbar完整条件成立（单K/双K）',
    'pa_bull_pinbar': '裸K：看涨Pinbar（下影占比>2/3）',
    'pa_bear_pinbar': '裸K：看跌Pinbar（上影占比>2/3）',
    'pa_bull_key_level': '裸K：下影触及一年大区间底部支撑带且实体不低于带下沿',
    'pa_bear_key_level': '裸K：上影触及一年大区间顶部压力带且实体不高于带上沿',
    'pa_bull_local_extreme': '裸K：下行后的局部低点',
    'pa_bear_local_extreme': '裸K：上行后的局部高点',
    'pa_prominent': '裸K：信号明显（振幅≥前20根中位数1.5倍）',
    'pa_bull_false_break': '裸K：假跌破支撑并收回',
    'pa_bear_false_break': '裸K：假突破压力并回落',
    'pa_left_eye': '裸K：实体在左眼范围内且振幅更大',
    'pa_bull_trend': '裸K：此前已结束周线高低点抬高',
    'pa_bear_trend': '裸K：此前已结束周线高低点降低',
}
SINGLE_METRICS = {key for key in PA_LABELS if not key.endswith('within_250')}
PA_LABELS.update({key.replace('pa_', 'pa2_', 1): label.replace('裸K：', '裸K：双K合成·吞没·')
                  for key, label in list(PA_LABELS.items()) if key in SINGLE_METRICS})
for key in SINGLE_METRICS:
    PA_LABELS[key] = PA_LABELS[key].replace('裸K：', '裸K：单K·')
PA_LABELS['pw_bull_within_156'] = '裸K：近156周内看涨Pinbar（单K/双K，260周历史月线支撑）'
PA_LABELS['body_low_retest'] = '两年独立实体最低/次低点：离开后首次回访±5%（含影线）'
PA_METRICS = set(PA_LABELS)


def uses_price_action(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    if isinstance(value, dict):
        return value.get('metric') in PA_METRICS or any(uses_price_action(v) for v in value.values())
    return isinstance(value, list) and any(uses_price_action(v) for v in value)


def price_action_tree(direction, bars=1):
    if direction not in ('bull', 'bear'):
        raise ValueError('direction must be bull or bear')

    def condition(key):
        if bars == 2:
            key = key.replace('pa_', 'pa2_', 1)
        return dict(kind='condition', metric=key, timeframe='1d', operator='eq',
                    right=dict(kind='constant', value=True, unit='boolean'))

    details = ['pa_prominent', f'pa_{direction}_false_break', 'pa_left_eye', f'pa_{direction}_trend']
    return dict(kind='group', logic='and', children=[
        *[condition(f'pa_{direction}_{name}') for name in ('pinbar', 'key_level', 'local_extreme')],
        dict(kind='group', logic='or', children=[dict(kind='group', logic='and',
             children=[condition(a), condition(b)]) for a, b in combinations(details, 2)]),
    ])


def _major_levels(values, dates, signal_week, monthly=False):
    """Only completed weeks inside the prior 250 daily observations form levels."""
    weeks = []
    for index, ((o, h, l, c), stamp) in enumerate(zip(values, dates, strict=True)):
        key = (stamp.year, stamp.month) if monthly else stamp.date().isocalendar()[:2]
        if key == signal_week:
            continue
        if not weeks or weeks[-1]['key'] != key:
            weeks.append(dict(key=key, high=h, low=l, close=c, start=index, end=index,
                              high_index=index, low_index=index))
        else:
            week = weeks[-1]
            if h > week['high']:
                week.update(high=h, high_index=index)
            if l < week['low']:
                week.update(low=l, low_index=index)
            week.update(close=c, end=index)
    # Discard the first potentially partial week of the rolling daily window.
    weeks = weeks[1:]
    if len(weeks) < 17:
        return None
    tr = [max(w['high'] - w['low'], abs(w['high'] - weeks[j-1]['close']),
              abs(w['low'] - weeks[j-1]['close'])) if j else w['high'] - w['low']
          for j, w in enumerate(weeks)]
    levels = []
    for j in range(13, len(weeks) - 2):
        week = weeks[j]
        atr = float(np.mean(tr[j-13:j+1]))
        if atr <= 0:
            continue
        for kind, field in (('support', 'low'), ('resistance', 'high')):
            price = week[field]
            neighborhood = [w[field] for w in weeks[j-2:j+3]]
            # First occurrence of a plateau only, with a genuine turn on both sides.
            if kind == 'support':
                pivot = price < min(neighborhood[:2]) and price <= min(neighborhood[3:])
                reactions = [w['high'] - price for w in weeks[j+1:]]
            else:
                pivot = price > max(neighborhood[:2]) and price >= max(neighborhood[3:])
                reactions = [price - w['low'] for w in weeks[j+1:]]
            if not pivot:
                continue
            reaction = next((j+1+k for k, value in enumerate(reactions) if value >= 2*atr), None)
            if reaction is None:
                continue
            confirmed = weeks[max(j+2, reaction)]['end']
            anchor = week[f'{field}_index']
            context = values[max(0, anchor-14):anchor+1]
            daily_tr = np.maximum(context[1:,1]-context[1:,2],
                                  np.maximum(abs(context[1:,1]-context[:-1,3]), abs(context[1:,2]-context[:-1,3])))
            tolerance = max(price*.005, float(np.mean(daily_tr))*.5)
            lower, upper = float(price-tolerance), float(price+tolerance)
            levels.append(dict(lower=lower, upper=upper, role=kind, original_kind=kind,
                               anchor_date=str(dates[anchor].date()), confirmed_date=str(dates[confirmed].date()),
                               switched_date=None, weekly_atr=atr, reaction=2*atr, source='annual_boundary'))
    floor = float(np.quantile(values[:, 2], .02))
    ceiling = float(np.quantile(values[:, 1], .98))
    span = ceiling - floor
    if span <= 0:
        return []
    selected = []
    for kind, edge in (('support', floor), ('resistance', ceiling)):
        candidates = [z for z in levels if z['role'] == kind
                      and abs((z['lower'] + z['upper'])/2 - edge) <= span*.2]
        if candidates:
            zone = min(candidates, key=lambda z: abs((z['lower']+z['upper'])/2-edge))
            selected.append({**zone, 'range_low': floor, 'range_high': ceiling, 'edge_fraction': .2})
    return selected


def _daily_features(rows, target_dates=None, signal_only_dates=None, signal_bars=1, higher_context=None):
    if not rows:
        return []
    values = np.array([[r.get(k, np.nan) for k in ('open', 'high', 'low', 'close')] for r in rows], dtype=float)
    dates = [pd.Timestamp(r.get('feature_date', r.get('timestamp'))) for r in rows]
    ranges = values[:, 1] - values[:, 2]
    output = []
    weeks = []
    weekly_highs, weekly_lows = [], []
    week_key = None
    current_week = None
    weekly_trends = (None, None)
    trends = []
    for i, (o, h, l, c) in enumerate(values):
        key = dates[i].date().isocalendar()[:2]
        if key != week_key:
            if current_week is not None:
                weeks.append(current_week)
            week_key = key
            current_week = [h, l]
            if len(weeks) >= 5:
                recent = np.array(weeks[-5:])
                if np.isfinite(recent).all():
                    if recent[2, 0] == max(recent[:, 0]):
                        weekly_highs.append(recent[2, 0])
                    if recent[2, 1] == min(recent[:, 1]):
                        weekly_lows.append(recent[2, 1])
            weekly_trends = ((bool(weekly_highs[-1] > weekly_highs[-2] and weekly_lows[-1] > weekly_lows[-2]),
                              bool(weekly_highs[-1] < weekly_highs[-2] and weekly_lows[-1] < weekly_lows[-2]))
                             if len(weekly_highs) >= 2 and len(weekly_lows) >= 2 else (None, None))
        else:
            current_week = [max(current_week[0], h), min(current_week[1], l)]
        trends.append(weekly_trends)
        result = dict.fromkeys(SINGLE_METRICS)
        output.append(result)
        if target_dates is not None and dates[i].date() not in target_dates:
            continue
        begin = i - signal_bars + 1
        if begin < 0 or not np.isfinite(values[begin:i+1]).all():
            continue
        o, h, l, c = values[begin, 0], max(values[begin:i+1, 1]), min(values[begin:i+1, 2]), values[i, 3]
        width = h - l
        result.update(pa_bull_pinbar=bool(width > 0 and 3 * (min(o, c) - l) > 2 * width),
                      pa_bear_pinbar=bool(width > 0 and 3 * (h - max(o, c)) > 2 * width),
                      pa_bull_trend=trends[begin][0], pa_bear_trend=trends[begin][1])
        if signal_bars == 2:
            first_open, first_close = values[begin, 0], values[begin, 3]
            second_open, second_close = values[i, 0], values[i, 3]
            # Book PDF pp.29,63: opposite bodies, second engulfs first.
            # Equal adjoining close/open is allowed; no near-equality tolerance.
            bullish_engulfing = (first_close < first_open and second_close > second_open
                                 and second_open <= first_close and second_close > first_open)
            bearish_engulfing = (first_close > first_open and second_close < second_open
                                 and second_open >= first_close and second_close < first_open)
            result['pa_bull_pinbar'] = bool(result['pa_bull_pinbar'] and bullish_engulfing)
            result['pa_bear_pinbar'] = bool(result['pa_bear_pinbar'] and bearish_engulfing)
        if begin and np.isfinite(values[begin-1]).all():
            result['pa_left_eye'] = bool(values[begin-1, 2] <= min(o, c) <= max(o, c) <= values[begin-1, 1]
                                         and width > ranges[begin-1])
        if begin >= 3 and np.isfinite(values[begin-3:begin]).all():
            previous = values[begin-3:begin]
            result['pa_bull_local_extreme'] = bool(np.all(np.diff(previous[:, 3]) < 0) and l < min(previous[:, 2]))
            result['pa_bear_local_extreme'] = bool(np.all(np.diff(previous[:, 3]) > 0) and h > max(previous[:, 1]))
        if begin >= 20 and np.isfinite(ranges[begin-20:begin]).all():
            reference = np.median(ranges[begin-20:begin])
            result['pa_prominent'] = bool(reference > 0 and width >= 1.5 * reference)
        if signal_only_dates is not None and dates[i].date() in signal_only_dates and not any(result.get(f'pa_{d}_pinbar') and result.get(f'pa_{d}_local_extreme') is not False for d in ('bull', 'bear')):
            continue
        start = max(0, begin-250)
        if begin < 20 or not np.isfinite(values[start:begin]).all():
            continue
        if higher_context is None:
            levels = _major_levels(values[start:begin], dates[start:begin], dates[begin].date().isocalendar()[:2])
        else:
            levels, bull_trend, bear_trend = higher_context(begin)
            result.update(pa_bull_trend=bull_trend, pa_bear_trend=bear_trend)
        if levels is None:
            continue
        previous_close = values[begin-1, 3]
        for direction, role in (('bull', 'support'), ('bear', 'resistance')):
            touched = [zone for zone in levels if zone['role'] == role
                       and (l <= zone['upper'] and min(o, c) >= zone['lower'] if direction == 'bull'
                            else h >= zone['lower'] and max(o, c) <= zone['upper'])]
            result[f'pa_{direction}_key_level'] = bool(touched)
            result[f'pa_{direction}_false_break'] = False
            if touched:
                zone = min(touched, key=lambda z: abs((z['lower']+z['upper'])/2 - (l if direction == 'bull' else h)))
                a, b = zone['lower'], zone['upper']
                result[f'pa_{direction}_false_break'] = bool(
                    previous_close >= b and l < a and c >= b if direction == 'bull'
                    else previous_close <= a and h > b and c <= a)
                result[f'pa_{direction}_zone'] = zone
    return output


def attach_year_signals(rows, features, window=250):
    """Evaluate the whole conjunction on each date, never mix criteria across dates."""
    for direction in ('bull', 'bear'):
        hits, unknown = [], []
        for i, (row, feature) in enumerate(zip(rows, features, strict=True)):
            uncertain = False
            for prefix, count in (('pa', 1), ('pa2', 2)):
                if prefix == 'pa2' and f'pa2_{direction}_pinbar' not in feature:
                    continue
                required = [feature.get(f'{prefix}_{direction}_{name}') for name in ('pinbar', 'key_level', 'local_extreme')]
                detail_keys = (f'{prefix}_prominent', f'{prefix}_{direction}_false_break', f'{prefix}_left_eye', f'{prefix}_{direction}_trend')
                details = [feature.get(key) for key in detail_keys]
                enough = sum(v is True for v in details) >= 2
                impossible = any(v is False for v in required) or sum(v is not False for v in details) < 2
                if all(v is True for v in required) and enough:
                    stamp = str(row.get('feature_date', row.get('timestamp')))[:10]
                    first = rows[max(0, i-count+1)]
                    hits.append((i, dict(date=stamp, start_date=str(first.get('feature_date', first.get('timestamp')))[:10],
                                         bars=count, zone=feature.get(f'{prefix}_{direction}_zone'),
                                         details={key:feature.get(key) for key in detail_keys})))
                elif not impossible:
                    uncertain = True
            if uncertain:
                unknown.append(i)
            hits = [(index, hit) for index, hit in hits if index > i-window]
            unknown = [index for index in unknown if index > i-window]
            feature[f'pa_{direction}_within_250'] = True if hits else None if unknown or i < window-1 else False
            feature[f'pa_{direction}_year_hits'] = [hit for _, hit in hits]


def price_action_features(rows, target_dates=None, include_year=False):
    wanted = target_dates
    signal_only = None
    if include_year and target_dates is not None:
        dates = [pd.Timestamp(row.get('feature_date', row.get('timestamp'))).date() for row in rows]
        indices = [i for i,d in enumerate(dates) if d in target_dates]
        wanted = set(dates[max(0,min(indices)-249):max(indices)+1]) if indices else set()
        signal_only = wanted - target_dates
    features = _daily_features(rows, wanted, signal_only)
    pairs = _daily_features(rows, wanted, signal_only, signal_bars=2)
    for feature, pair in zip(features, pairs, strict=True):
        feature.update({key.replace('pa_', 'pa2_', 1): value for key, value in pair.items()})
    if include_year:
        attach_year_signals(rows, features)
    for feature, retest in zip(features, body_low_retest_features(rows), strict=True):
        feature.update(retest)
    return features


def weekly_price_action_features(rows, daily_rows, target_dates=None):
    """Completed weekly signals with prior completed calendar-month context."""
    if not rows:
        return []
    dates = [pd.Timestamp(r.get('feature_date', r.get('timestamp'))).tz_localize(None) for r in rows]
    daily_dates = pd.DatetimeIndex([r.get('feature_date', r.get('timestamp')) for r in daily_rows]).tz_localize(None)
    daily_values = np.array([[r[k] for k in ('open', 'high', 'low', 'close')] for r in daily_rows])
    wanted = target_dates
    if wanted is not None:
        indices = [i for i, d in enumerate(dates) if d.date() in wanted]
        wanted = {d.date() for d in dates[max(0,min(indices)-155):max(indices)+1]} if indices else set()
    cache = {}

    def context(begin):
        if begin in cache:
            return cache[begin]
        # Start of the first signal week: no days from either signal candle.
        end = dates[begin].to_period('W-FRI').start_time
        start = dates[max(0, begin-260)].to_period('W-FRI').start_time
        mask = (daily_dates >= start) & (daily_dates < end)
        values, stamps = daily_values[mask], daily_dates[mask]
        if not len(values):
            return None, None, None
        levels = _major_levels(values, stamps, (end.year,end.month), monthly=True)
        months = {}
        for v, d in zip(values, stamps, strict=True):
            key = (d.year,d.month)
            if key == (end.year,end.month):
                continue
            if key not in months:
                months[key] = [v[1],v[2]]
            else:
                months[key] = [max(months[key][0],v[1]),min(months[key][1],v[2])]
        monthly = list(months.values())[1:]
        highs, lows = [], []
        for i in range(2,len(monthly)-2):
            nearby = monthly[i-2:i+3]
            if monthly[i][0] == max(v[0] for v in nearby):
                highs.append(monthly[i][0])
            if monthly[i][1] == min(v[1] for v in nearby):
                lows.append(monthly[i][1])
        trends = (bool(highs[-1]>highs[-2] and lows[-1]>lows[-2]),
                  bool(highs[-1]<highs[-2] and lows[-1]<lows[-2])) if len(highs)>=2 and len(lows)>=2 else (None,None)
        cache[begin] = (levels,*trends)
        return cache[begin]

    features = _daily_features(rows, wanted, signal_bars=1, higher_context=context)
    pairs = _daily_features(rows, wanted, signal_bars=2, higher_context=context)
    for feature, pair in zip(features,pairs,strict=True):
        feature.update({key.replace('pa_','pa2_',1):value for key,value in pair.items()})
    attach_year_signals(rows,features,window=156)
    for feature in features:
        feature['pw_bull_within_156'] = feature.pop('pa_bull_within_250')
        feature['pw_bull_year_hits'] = feature.pop('pa_bull_year_hits')
    return features
