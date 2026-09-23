from datetime import date,timedelta
import math
from astock.features.chart_shapes import chart_shape_features


def fixture(kind):
    rows=[]
    for i in range(65):
        top=20-(.045*i if kind=='descending' else 0)
        bottom=10+(.045*i if kind=='ascending' else 0)
        price=bottom+(top-bottom)*(1+math.cos(i*math.pi/5))/2
        rows.append(dict(feature_date=date(2025,1,1)+timedelta(days=i),open=price,close=price,high=price+.05,low=price-.05))
    return rows


def test_all_three_shapes_without_breakout_and_merge_duplicates():
    for kind in ('ascending','descending','range'):
        result=chart_shape_features(fixture(kind))[-1]
        assert result[f'shape_{kind}_within_2y'] is True
        hits=[h for h in result['chart_shape_hits'] if h['kind']==kind]
        assert len(hits)==1
        assert 20<=hits[0]['bars']<=120
        assert len(hits[0]['high_points'])>=3 and len(hits[0]['low_points'])>=3


def test_future_breakout_does_not_remove_shape_or_change_past():
    rows=fixture('ascending');before=chart_shape_features(rows)
    rows.append(dict(feature_date=date(2025,3,7),open=30,close=31,high=32,low=29))
    after=chart_shape_features(rows)
    assert after[:-1]==before
    assert after[-1]['shape_ascending_within_2y'] is True


def test_flat_and_one_way_prices_are_not_oscillation():
    for prices in ([10]*80,list(range(10,90))):
        rows=[dict(feature_date=date(2025,1,1)+timedelta(days=i),open=p,close=p,high=p+.1,low=p-.1) for i,p in enumerate(prices)]
        assert not chart_shape_features(rows)[-1]['chart_shape_hits']


def test_unknown_short_history_and_expired_shapes():
    assert chart_shape_features(fixture('range')[:10])[-1]['shape_range_within_2y'] is None
    rows=fixture('range')
    rows.append(dict(feature_date=date(2028,1,1),open=30,close=31,high=32,low=29))
    assert chart_shape_features(rows)[-1]['chart_shape_hits']==[]


def test_distinct_nonoverlapping_shapes_are_retained():
    first=fixture('range')
    gap=[dict(feature_date=date(2025,1,1)+timedelta(days=65+i),open=30+i,close=30+i,high=31+i,low=29+i) for i in range(130)]
    second=fixture('range')
    second=[{**r,'feature_date':date(2025,1,1)+timedelta(days=195+i)} for i,r in enumerate(second)]
    hits=chart_shape_features(first+gap+second)[-1]['chart_shape_hits']
    assert len([h for h in hits if h['kind']=='range'])>=2


def test_parallel_sloping_channel_is_not_a_triangle_or_range():
    rows=fixture('range')
    rows=[{**r,**{key:r[key]+i*.15 for key in ('open','high','low','close')}} for i,r in enumerate(rows)]
    assert not chart_shape_features(rows)[-1]['chart_shape_hits']


def test_five_alternating_pivots_are_enough():
    # Starts and ends at a peak: three highs, two lows, no breakout.
    rows=fixture('range')[:28]
    hits=chart_shape_features(rows)[-1]['chart_shape_hits']
    assert any(len(h['high_points'])+len(h['low_points'])==5 for h in hits)


def test_boundaries_enclose_every_candle():
    rows=fixture('ascending')
    for hit in chart_shape_features(rows)[-1]['chart_shape_hits']:
        inside=[r for r in rows if hit['start_date']<=str(r['feature_date'])<=hit['end_date']]
        for i,r in enumerate(inside):
            fraction=i/(len(inside)-1)
            upper=hit['upper_start']+fraction*(hit['upper_end']-hit['upper_start'])
            lower=hit['lower_start']+fraction*(hit['lower_end']-hit['lower_start'])
            assert r['high']<=upper+1e-8
            assert r['low']>=lower-1e-8
