from datetime import date, timedelta
from itertools import product

from astock.features.price_action import price_action_features, price_action_tree
from astock.screening.models import GroupNode
from astock.screening.evaluator import evaluate_tree
from astock.domain.market import Timeframe


def rows(values):
    return [dict(feature_date=date(2025, 1, 1) + timedelta(days=i), open=o, high=h, low=l, close=c)
            for i, (o, h, l, c) in enumerate(values)]


def test_pinbar_strict_boundary_and_no_secondary_shadow_limit():
    output = price_action_features(rows([(3, 4, 1, 3), (3.1, 4, 1, 3.2), (2, 4, 1, 1.8), (2, 2, 2, 2)]))
    assert output[0]['pa_bull_pinbar'] is False  # exactly 2/3
    assert output[1]['pa_bull_pinbar'] is True  # opposite wick > 10% accepted
    assert output[2]['pa_bear_pinbar'] is False
    assert output[3]['pa_bull_pinbar'] is False


def test_local_low_left_eye_and_prominence():
    data = rows([(10, 11, 9, 10)] * 20 + [(12, 13, 10, 12), (11, 12, 9, 11), (10, 11, 8, 10), (9, 10, 4, 9.5)])
    latest = price_action_features(data)[-1]
    assert latest['pa_bull_local_extreme'] is True
    assert latest['pa_left_eye'] is True
    assert latest['pa_prominent'] is True


def test_append_future_does_not_change_history():
    data = rows([(10 + i % 5, 16 + i % 4, 6 + i % 3, 11 + i % 5) for i in range(160)])
    full = price_action_features(data)
    for end in (4, 20, 40, 100, 159):
        assert full[:end] == price_action_features(data[:end])


def test_two_of_four_tree_has_exact_truth_table():
    tree = GroupNode.model_validate(price_action_tree('bull'))
    for bits in product((False, True), repeat=4):
        row = dict(feature_date=date(2026, 9, 16), pa_bull_pinbar=True, pa_bull_key_level=True, pa_bull_local_extreme=True)
        row.update(dict(zip(('pa_prominent', 'pa_bull_false_break', 'pa_left_eye', 'pa_bull_trend'), bits)))
        result = evaluate_tree(tree, {Timeframe.DAY: [row]})
        assert str(result.result) == ('true' if sum(bits) >= 2 else 'false')


def test_false_break_uses_frozen_support_and_bear_is_mirror():
    data = major_week_rows([12]*14 + [11,10,8,10,12,12,12,11])
    data.extend([dict(feature_date=date(2025,6,9)+timedelta(days=i), open=o, high=h, low=l, close=c)
                 for i,(o,h,l,c) in enumerate([(10,11,9,10),(9,10,8.5,9),(8.7,9.5,8,8.7),(8.5,9,6,8.8)])])
    bull = price_action_features(data)[-1]
    assert bull['pa_bull_key_level'] is True
    assert bull['pa_bull_false_break'] is True
    mirrored = [{**r, 'open': 30-r['open'], 'high': 30-r['low'], 'low': 30-r['high'], 'close': 30-r['close']} for r in data]
    bear = price_action_features(mirrored)[-1]
    for field in ('pinbar', 'key_level', 'false_break', 'local_extreme'):
        assert bear[f'pa_bear_{field}'] is True
    # A wide bar fully below the frozen band has no qualifying key-level touch.
    data[-1].update(open=3, high=4, low=1, close=3.5)
    assert price_action_features(data)[-1]['pa_bull_key_level'] is False


def test_unknown_detail_does_not_block_two_known_true_details():
    tree = GroupNode.model_validate(price_action_tree('bull'))
    row = dict(pa_bull_pinbar=True, pa_bull_key_level=True, pa_bull_local_extreme=True,
               pa_prominent=True, pa_left_eye=True, pa_bull_false_break=False, pa_bull_trend=None)
    assert str(evaluate_tree(tree, {Timeframe.DAY: [row]}).result) == 'true'
    row['pa_left_eye'] = False
    assert str(evaluate_tree(tree, {Timeframe.DAY: [row]}).result) == 'unknown'
    row['pa_bull_key_level'] = False
    assert str(evaluate_tree(tree, {Timeframe.DAY: [row]}).result) == 'false'


def test_completed_week_trend_uses_confirmed_pivots_only():
    import pandas as pd
    centers = [10, 11, 15, 12, 11, 8, 10, 12, 17, 14, 12, 10, 12, 13, 14, 13]
    dates = pd.bdate_range('2025-01-06', periods=len(centers)*5)
    data = [dict(feature_date=d.date(), open=centers[i//5], high=centers[i//5]+1,
                 low=centers[i//5]-1, close=centers[i//5]) for i, d in enumerate(dates)]
    result = price_action_features(data)
    assert result[14*5]['pa_bull_trend'] is True
    # Changing the current week's prices must not change the earlier-week trend input.
    data[14*5].update(open=2, high=3, low=1, close=2)
    assert price_action_features(data)[14*5]['pa_bull_trend'] is True


def major_week_rows(centers):
    import pandas as pd
    dates = pd.bdate_range('2025-01-06', periods=len(centers)*5)
    return [dict(feature_date=d.date(), open=centers[i//5], high=centers[i//5]+.5,
                 low=centers[i//5]-.5, close=centers[i//5]) for i,d in enumerate(dates)]


def test_minor_repeated_daily_levels_are_not_strategy_levels():
    data = major_week_rows([10]*22)
    data.append(dict(feature_date=date(2025,6,9), open=10, high=10.1, low=8, close=10))
    assert price_action_features(data)[-1]['pa_bull_key_level'] is False


def test_single_major_weekly_reversal_can_be_support():
    data = major_week_rows([12]*14 + [11,10,8,10,12,12,12,11])
    data.append(dict(feature_date=date(2025,6,9), open=9, high=9.5, low=7.5, close=9))
    result=price_action_features(data)[-1]
    assert result['pa_bull_key_level'] is True
    assert result['pa_bull_zone']['anchor_date'] == '2025-04-28'
    assert result['pa_bull_zone']['source'] == 'annual_boundary'


def test_middle_resistance_does_not_become_bottom_support():
    data=major_week_rows([8]*14 + [9,10,12,10,8,13,14,14])
    data.append(dict(feature_date=date(2025,6,9),open=13,high=13.5,low=12.4,close=13))
    result=price_action_features(data)[-1]
    assert result['pa_bull_key_level'] is False


def test_major_level_waits_for_reaction_and_right_hand_weeks():
    data=major_week_rows([12]*14 + [11,10,8,8.1,8.2])
    data.append(dict(feature_date=date(2025,5,19),open=8,high=8.5,low=7.5,close=8))
    assert price_action_features(data)[-1]['pa_bull_key_level'] is False


def test_major_level_expires_outside_one_year_and_is_causal():
    import pandas as pd
    data=major_week_rows([12]*14 + [11,10,8,10,12,12,12,11])
    data.append(dict(feature_date=date(2025,6,9),open=9,high=9.5,low=7.5,close=9))
    signal=price_action_features(data)[-1]
    assert signal['pa_bull_key_level'] is True
    future=[dict(feature_date=d.date(),open=12,high=12.5,low=11.5,close=12)
            for d in pd.bdate_range('2025-06-10',periods=260)]
    extended=data+future
    assert price_action_features(extended)[len(data)-1] == signal
    extended.append(dict(feature_date=date(2026,6,10),open=9,high=9.5,low=7.5,close=9))
    assert price_action_features(extended)[-1]['pa_bull_key_level'] is False


def test_year_range_rejects_middle_reversal():
    from astock.features.price_action import _major_levels
    import numpy as np
    import pandas as pd
    data=major_week_rows([10]*14+[8,6,3,6,10,12,15,12,10,8,10,12,14,12])
    vals=np.array([[r[k] for k in ('open','high','low','close')] for r in data])
    levels=_major_levels(vals,[pd.Timestamp(r['feature_date']) for r in data],(2025,40))
    assert all((z['lower']+z['upper'])/2 < 6 or (z['lower']+z['upper'])/2 > 12 for z in levels)
    assert len([z for z in levels if z['role']=='support']) <= 1
    assert len([z for z in levels if z['role']=='resistance']) <= 1


def test_year_signals_keep_every_date_and_expire():
    from astock.features.price_action import attach_year_signals
    data=rows([(10,11,9,10)]*260)
    features=[dict(pa_bull_pinbar=False) for _ in data]
    for i in (2,8):
        features[i]=dict(pa_bull_pinbar=True,pa_bull_key_level=True,pa_bull_local_extreme=True,
                         pa_prominent=True,pa_left_eye=True,pa_bull_false_break=False,pa_bull_trend=None,
                         pa_bull_zone={'lower':9,'upper':10})
    attach_year_signals(data,features)
    assert [h['date'] for h in features[250]['pa_bull_year_hits']] == [str(data[i]['feature_date']) for i in (2,8)]
    assert len(features[252]['pa_bull_year_hits']) == 1
    assert features[258]['pa_bull_within_250'] is False
    assert features[250]['pa_bull_within_250'] is True


def test_year_scan_keeps_repeated_real_signals_and_all_chart_marks():
    import pandas as pd
    from astock.screening.annotations import condition_marks
    data=major_week_rows([12]*14 + [11,10,8,10,12,12,12,11])
    shape=[(10,11,9,10),(9,10,8.5,9),(8.7,9.5,8,8.7),(8.5,9,6,8.8)]*2
    data += [dict(feature_date=d.date(),open=o,high=h,low=l,close=c)
             for d,(o,h,l,c) in zip(pd.bdate_range('2025-06-09',periods=8),shape,strict=True)]
    output=price_action_features(data,{data[-1]['feature_date']},include_year=True)
    hits=output[-1]['pa_bull_year_hits']
    assert [hit['date'] for hit in hits if hit['bars']==1] == ['2025-06-12','2025-06-18']
    node=dict(kind='condition',metric='pa_bull_within_250',timeframe='1d',operator='eq',right=dict(kind='constant',value=True,unit='boolean'))
    marks=condition_marks(node,dict(result='true',actual=True,expected=True),{Timeframe.DAY:[{**data[-1],**output[-1]}]})
    assert [m['date'] for m in marks if 'Pinbar' in m['label']] == [hit['date'] for hit in hits]
    pair_marks=[m for m in marks if '双K合成' in m['label']]
    assert pair_marks == []  # Previously accepted pair does not engulf the first body.
    assert len([m for m in marks if 'priceLow' in m]) == len(hits)
    # Truncation must retain the first signal with its own frozen key level.
    earlier=price_action_features(data[:-4],include_year=True)[-1]['pa_bull_year_hits']
    assert earlier == [hit for hit in hits if hit['date']=='2025-06-12']


def test_two_bar_pinbar_merges_ohlc_and_uses_context_before_pair():
    data=rows([(10,11,9,10)]*22+[(10,10.5,6,6.5),(6.5,10.5,6,10.1)])
    feature=price_action_features(data)[-1]
    assert feature['pa_bull_pinbar'] is False
    assert feature['pa2_bull_pinbar'] is True
    assert feature['pa2_prominent'] is True
    assert feature['pa2_left_eye'] is True
    mirrored=[{**r,'open':20-r['open'],'close':20-r['close'],'high':20-r['low'],'low':20-r['high']} for r in data]
    assert price_action_features(mirrored)[-1]['pa2_bear_pinbar'] is True
    assert price_action_features(data[:-1])[-1]['pa2_bull_pinbar'] is False
    assert price_action_features(data+rows([(1,2,0,1)]))[len(data)-1] == feature


def test_year_signals_do_not_mix_single_and_pair_conditions():
    from astock.features.price_action import attach_year_signals
    data=rows([(10,11,9,10)]*2)
    f=dict(pa_bull_pinbar=True,pa_bull_key_level=False,pa_bull_local_extreme=True,
           pa_prominent=True,pa_left_eye=True,pa_bull_false_break=False,pa_bull_trend=False,
           pa2_bull_pinbar=False,pa2_bull_key_level=True,pa2_bull_local_extreme=True,
           pa2_prominent=True,pa2_left_eye=True,pa2_bull_false_break=False,pa2_bull_trend=False)
    features=[dict(pa_bull_pinbar=False),f]
    attach_year_signals(data,features)
    assert not features[-1]['pa_bull_year_hits']
    f['pa2_bull_pinbar']=True
    attach_year_signals(data,features)
    hit=features[-1]['pa_bull_year_hits'][0]
    assert hit['bars']==2 and hit['start_date']==str(data[0]['feature_date'])


def test_complete_pair_signal_is_confirmed_on_second_bar_and_marked_as_pair():
    import pandas as pd
    data=major_week_rows([12]*14 + [11,10,8,10,12,12,12,11])
    shape=[(10,11,9,10),(9,10,8.5,9),(8.7,9.5,8,8.7),(8.5,9,6,6.5),(6.5,8.9,6,8.8)]
    data += [dict(feature_date=d.date(),open=o,high=h,low=l,close=c)
             for d,(o,h,l,c) in zip(pd.bdate_range('2025-06-09',periods=5),shape,strict=True)]
    result=price_action_features(data,include_year=True)
    assert result[-1]['pa_bull_pinbar'] is False
    assert result[-1]['pa2_bull_pinbar'] is True
    tree=GroupNode.model_validate(price_action_tree('bull',bars=2))
    assert evaluate_tree(tree,{Timeframe.DAY:[{**data[-1],**result[-1]}]}).result.value=='true'
    pair=[h for h in result[-1]['pa_bull_year_hits'] if h['bars']==2 and h['date']=='2025-06-13']
    assert len(pair)==1 and pair[0]['start_date']=='2025-06-12'
    from astock.screening.annotations import condition_marks
    node=dict(kind='condition',metric='pa_bull_within_250',timeframe='1d',operator='eq',right=dict(kind='constant',value=True,unit='boolean'))
    marks=condition_marks(node,dict(result='true',actual=True,expected=True),{Timeframe.DAY:[{**data[-1],**result[-1]}]})
    pair_marks=[m for m in marks if '双K合成' in m['label']]
    assert pair_marks[0]['startDate']=='2025-06-12' and pair_marks[0]['periods']==2

    assert not any(h['date']=='2025-06-13' for h in price_action_features(data[:-1],include_year=True)[-1]['pa_bull_year_hits'])


def test_pair_requires_opposite_bodies_and_full_engulfing():
    # Opening equality is allowed for continuous prices; closing must pass first open.
    cases = [
        ((10,10.5,6,7),(7,10.5,6.5,10.1), True),
        ((10,10.5,6,7),(6.9,10.5,6.5,10.1), True),
        ((10,10.5,6,7),(7.1,10.5,6.5,10.1), False),
        ((10,10.5,6,7),(7,10.5,6.5,9.9), False),
        ((10,10.5,6,7),(7,10.5,6.5,10), False),
        ((10,10.5,6,10.1),(10.1,10.5,6.5,10.2), False),
        ((10,10.5,6,10),(10,10.5,6.5,10.1), False),
    ]
    for first, second, expected in cases:
        data=rows([first,second])
        assert price_action_features(data)[-1]['pa2_bull_pinbar'] is expected
        inverse=[{**r,'open':20-r['open'],'close':20-r['close'],'high':20-r['low'],'low':20-r['high']} for r in data]
        assert price_action_features(inverse)[-1]['pa2_bear_pinbar'] is expected


def test_300364_august_pair_is_not_full_bearish_engulfing():
    data=rows([(32,37.15,31.7,35.59),(35.24,35.9,32.31,32.35)])
    assert price_action_features(data)[-1]['pa2_bear_pinbar'] is False


def test_key_level_requires_main_wick_contact_for_single_and_combined_bars(monkeypatch):
    import astock.features.price_action as pa
    zone = dict(lower=20.3, upper=21.25, role='support')
    monkeypatch.setattr(pa, '_major_levels', lambda *args: [zone])
    # 688589.SH 2026-06-05: only the upper wick reaches the old support.
    signal = (19.99097639, 20.32930053, 18.87649687, 19.88151858)
    for count in (1, 2):
        for candle, expected in ((signal, False), ((20.4, 20.6, 18.8, 20.5), True),
                                 ((21.4, 21.6, 21.3, 21.5), False)):
            data = rows([(22, 23, 21, 22)] * 25 + [candle] * count)
            bull = pa._daily_features(data, signal_bars=count)[-1]
            assert bull['pa_bull_key_level'] is expected
            mirror = [{**r, 'open':50-r['open'], 'high':50-r['low'],
                       'low':50-r['high'], 'close':50-r['close']} for r in data]
            zone.update(lower=28.75, upper=29.7, role='resistance')
            bear = pa._daily_features(mirror, signal_bars=count)[-1]
            assert bear['pa_bear_key_level'] is expected
            zone.update(lower=20.3, upper=21.25, role='support')


def test_weekly_context_uses_calendar_months_and_260_week_window(monkeypatch):
    import pandas as pd
    import astock.features.price_action as pa
    stamps = pd.bdate_range('2017-01-02', '2026-06-12')
    daily = [dict(feature_date=d.date(),open=10,high=11,low=9,close=10) for d in stamps]
    weekly = [dict(feature_date=d.date(),open=10,high=11,low=9,close=10)
              for d in pd.date_range('2017-01-06','2026-06-12',freq='W-FRI')]
    seen = []
    original = pa._major_levels
    def capture(values, dates, signal_week, monthly=False):
        seen.append((dates[0],dates[-1],signal_week,monthly))
        return original(values, dates, signal_week, monthly=monthly)
    monkeypatch.setattr(pa,'_major_levels',capture)
    output = pa.weekly_price_action_features(weekly,daily,{weekly[-1]['feature_date']})
    assert 'pw_bull_within_156' in output[-1]
    assert all(monthly for _,_,_,monthly in seen)
    # The last single-bar context precedes the entire June 8–12 signal week.
    contexts = [v for v in seen if v[1].date()==date(2026,6,5)]
    assert contexts and contexts[0][2] == (2026,6)
    assert contexts[0][0].date() == weekly[-261]['feature_date'] - timedelta(days=4)
    # Appending daily prices after the signal cannot change its context or result.
    extended = daily + [dict(feature_date=date(2026,6,15),open=90,high=100,low=1,close=95)]
    assert output == pa.weekly_price_action_features(weekly,extended,{weekly[-1]['feature_date']})


def test_weekly_recent_signal_window_expires_after_156_bars():
    from astock.features.price_action import attach_year_signals
    data = rows([(10,11,9,10)]*158)
    features = [dict(pa_bull_pinbar=False) for _ in data]
    features[0] = dict(pa_bull_pinbar=True,pa_bull_key_level=True,pa_bull_local_extreme=True,
                       pa_prominent=True,pa_left_eye=True,pa_bull_false_break=False,pa_bull_trend=False)
    attach_year_signals(data,features,window=156)
    assert features[155]['pa_bull_within_250'] is True
    assert features[156]['pa_bull_within_250'] is False


def test_weekly_backtest_timestamps_with_timezone_are_supported():
    import pandas as pd
    from astock.features.price_action import weekly_price_action_features
    weekly = [dict(timestamp=d,open=10,high=11,low=9,close=10) for d in pd.date_range('2024-01-05',periods=110,freq='W-FRI',tz='Asia/Shanghai')]
    daily = [dict(timestamp=d,open=10,high=11,low=9,close=10) for d in pd.bdate_range('2024-01-01','2026-02-06',tz='Asia/Shanghai')]
    result=weekly_price_action_features(weekly,daily,{weekly[-1]['timestamp'].date()})
    assert result[-1]['pw_bull_within_156'] is None


def test_weekly_single_and_double_signals_both_produce_annual_marks(monkeypatch):
    import pandas as pd
    import astock.features.price_action as pa
    monkeypatch.setattr(pa,'_major_levels',lambda *args,**kwargs:[{'role':'support','lower':9,'upper':10,'anchor_date':'2023-01-01'}])
    dates=pd.date_range('2022-01-07',periods=170,freq='W-FRI')
    for candles in ([(10,11,5,10.5)],[(10,10.2,5,9.8),(9.8,10.7,9.7,10.5)]):
        prices=[(10,11,9,10)]*(170-len(candles)-3)+[(12,13,9,12),(11,12,9,11),(10,12,9,10)]+candles
        weekly=[dict(feature_date=d.date(),open=o,high=h,low=l,close=c) for d,(o,h,l,c) in zip(dates,prices)]
        daily=[dict(feature_date=d.date(),open=10,high=11,low=9,close=10) for d in pd.bdate_range('2022-01-01',dates[-1])]
        result=pa.weekly_price_action_features(weekly,daily,{weekly[-1]['feature_date']})[-1]
        assert result['pw_bull_within_156'] is True
        assert any(hit['bars']==len(candles) and hit['date']==str(dates[-1].date()) for hit in result['pw_bull_year_hits'])
