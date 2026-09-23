from datetime import date, timedelta
from astock.features.vacuum import vacuum_features


def sample():
    prices = [(20.2, 19.8, 20.)] * 120 + [
        (40., 38., 39.), (35., 32., 33.), (31., 29., 30.),
        (30., 28.7, 29.5), (29.6, 28., 28.8), (29., 27., 27.5),
        (28., 26., 27.), (28., 26., 27.), (28., 26., 27.), (30., 28., 29.5),
    ]
    return [dict(feature_date=date(2026,1,1)+timedelta(days=i),high=h,low=l,close=c,volume=1000 if i<120 else 500)
            for i,(h,l,c) in enumerate(prices)]


def test_slow_tail_excluded_and_far_departure_required():
    result = vacuum_features(sample())
    assert result[122]['vacuum_lower'] is None
    assert result[123]['vacuum_lower'] == 29
    assert result[128]['vacuum_lower'] == 29
    assert result[-1]['vacuum_reentry'] is True
    assert result[-1]['vacuum_days'] == 3
    assert round(result[-1]['vacuum_drop'], 8) == 27.5
    assert result[-1]['vacuum_break_age'] == 4


def test_no_future_leak():
    rows=sample(); full=vacuum_features(rows)
    for end in range(119,len(rows)+1):
        assert vacuum_features(rows[:end]) == full[:end]


def test_exact_25_rejected():
    rows=sample(); rows[120]['high']=29/.75
    assert not vacuum_features(rows)[-1]['vacuum_reentry']


def test_immediate_return_rejected():
    rows=sample()[:126]+[sample()[-1]]
    assert not vacuum_features(rows)[-1]['vacuum_reentry']


def test_five_days_outside_but_not_far_enough_rejected():
    rows=sample()
    for row in rows[125:129]: row.update(high=29.,low=28.,close=28.5)
    assert not vacuum_features(rows)[-1]['vacuum_reentry']


def test_far_departure_less_than_three_days_rejected():
    rows=sample()
    for row in rows[124:128]: row.update(high=29.,low=28.,close=28.5)
    assert not vacuum_features(rows)[-1]['vacuum_reentry']


def test_fewer_than_five_consecutive_days_outside_rejected():
    rows=sample();rows[125].update(high=30.,low=28.,close=29.2)
    assert not vacuum_features(rows)[-1]['vacuum_reentry']


def test_twentieth_allowed_twenty_first_expired():
    rows=sample()
    for days,expected in [(20,True),(21,False)]:
        candidate=rows[:129]+[dict(rows[128]) for _ in range(days-4)]+[rows[-1]]
        assert vacuum_features(candidate)[-1]['vacuum_reentry'] is expected


def test_250_day_window_and_same_day_ma():
    rows=sample()+[dict(high=40.2,low=39.8,close=40.) for _ in range(250)]
    result=vacuum_features(rows)
    assert result[378]['vacuum_reentry_ma120_within_250'] is True
    assert result[379]['vacuum_reentry_ma120_within_250'] is False
    for row in rows[:120]:row.update(high=31.2,low=30.8,close=31.)
    assert vacuum_features(rows)[-1]['vacuum_year_hits'] == []


def test_five_bar_cap_does_not_follow_later_falls():
    rows=sample()[:123]+[dict(high=29.,low=27.,close=28.,volume=500),dict(high=27.,low=25.,close=26.,volume=500),dict(high=25.,low=23.,close=24.,volume=500)]
    result=vacuum_features(rows)
    assert result[124]['vacuum_days'] == 5
    assert result[125]['vacuum_lower'] == 25



def test_volume_filter_rejects_heavy_selloff_and_accepts_point_eight():
    rows=sample()
    for row in rows[120:123]:row["volume"]=801
    assert vacuum_features(rows)[-1]["vacuum_reentry"] is False
    for row in rows[120:123]:row["volume"]=800
    result=vacuum_features(rows)[-1]
    assert result["vacuum_reentry"] is True
    assert result["vacuum_volume_ratio"] == .8


def test_missing_volume_is_unknown_not_vacuum():
    rows=sample();rows[120].pop("volume")
    assert vacuum_features(rows)[-1]["vacuum_reentry"] is None
