from datetime import date, timedelta
from astock.features.body_low_retest import body_low_retest_features


def rows(prices):
    return [dict(feature_date=date(2025,1,1)+timedelta(days=i),open=p,close=p+.1,high=p+.2,low=p-.2) for i,p in enumerate(prices)]


def sample():
    return rows([14]*6+[10]+[12]*6+[11]+[13]*7+[10.4])


def test_independent_body_lows_and_wick_only_return():
    data=sample();data[-1].update(open=12,close=12.1,high=12.2,low=10.4)
    result=body_low_retest_features(data)[-1]
    assert result['body_low_retest'] is True
    assert [p['price'] for p in result['body_low_retest_levels']]==[10,11]
    assert result['body_low_retest_hits'][0]['price']==10
    # Staying in the band is not a fresh revisit.
    data.append({**data[-1],'feature_date':data[-1]['feature_date']+timedelta(days=1)})
    assert body_low_retest_features(data)[-1]['body_low_retest'] is False


def test_left_boundary_rising_price_is_not_a_pivot_and_no_future_leak():
    data=sample();data[0].update(open=1,close=1.1,low=.9,high=1.2)
    full=body_low_retest_features(data)
    assert [p['price'] for p in full[-1]['body_low_retest_levels']]==[10,11]
    for end in range(1,len(data)):
        assert body_low_retest_features(data[:end])==full[:end]


def test_same_base_without_five_percent_separation_is_merged():
    data=rows([12]*6+[10]+[10.4]*6+[10.1]+[12]*7+[10.2])
    result=body_low_retest_features(data)[-1]
    assert len(result['body_low_retest_levels'])==1
    assert result['body_low_retest'] is None


def test_five_percent_edge_counts_but_above_edge_does_not():
    data=sample();data[-1].update(open=12,close=12.1,high=12.2,low=10.5)
    assert any(x['price']==10 for x in body_low_retest_features(data)[-1]['body_low_retest_hits'])
    data[-1]['low']=10.501
    assert not any(x['price']==10 for x in body_low_retest_features(data)[-1]['body_low_retest_hits'])


def test_reference_older_than_two_calendar_years_expires():
    data=sample();data[-1]['feature_date']=date(2027,2,1)
    assert body_low_retest_features(data)[-1]['body_low_retest_levels']==[]


def test_low_is_not_available_before_five_following_bars_close():
    data=sample()
    result=body_low_retest_features(data)
    # Second low at index 13; five following bars close at index 18.
    assert len(result[18]['body_low_retest_levels'])==1
    assert len(result[19]['body_low_retest_levels'])==2
