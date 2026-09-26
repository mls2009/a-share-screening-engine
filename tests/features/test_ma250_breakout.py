from datetime import date

import pandas as pd
import pytest

from astock.features.ma250_breakout import breakout_hits


def prices(count=21):
    frame = pd.DataFrame({
        'feature_date': pd.bdate_range('2025-01-01', periods=count),
        'close': [9.] * (count - 1) + [10.5],
        'high': [9.2] * (count - 1) + [10.7],
        'low': [8.8] * (count - 1) + [9.6],
        'volume': [100.] * (count - 1) + [200.],
        'ma_250': [10.] * count,
    })
    return frame


def test_uses_twenty_preceding_volumes_and_preserves_historical_hits():
    frame = prices()
    hits = breakout_hits(frame, date(2025, 1, 1))
    assert len(hits) == 1
    assert hits[0]['volume_ratio'] == 2
    assert hits[0]['volume_average_20'] == 100
    assert hits[0]['branch'] == '放量突破'
    assert hits[0]['date'] == str(frame.iloc[-1].feature_date.date())
    frame.loc[len(frame)] = [pd.Timestamp('2025-02-03'), 11, 11.1, 10.5, 500, 10]
    assert breakout_hits(frame, date(2025, 1, 1)) == hits


@pytest.mark.parametrize('volume,expected', [(199.9, False), (200., True), (201., True)])
def test_volume_boundary(volume, expected):
    frame = prices()
    frame.loc[20, 'volume'] = volume
    assert bool(breakout_hits(frame, date(2025, 1, 1))) is expected


def test_amplitude_is_strictly_above_five_percent():
    frame = prices()
    frame.loc[19, 'close'] = 10
    frame.loc[20, ['high', 'low', 'close']] = [10.5, 10, 10.4]
    assert breakout_hits(frame, date(2025, 1, 1)) == []
    frame.loc[20, 'high'] = 10.51
    assert len(breakout_hits(frame, date(2025, 1, 1))) == 1


def test_confirmed_limit_exempts_volume_and_amplitude_but_requires_crossing():
    frame = prices()
    day = str(frame.iloc[-1].feature_date.date())
    frame.loc[20, ['high', 'low', 'close', 'volume']] = [10.5, 10.5, 10.5, 10]
    assert breakout_hits(frame, date(2025, 1, 1)) == []
    assert breakout_hits(frame, date(2025, 1, 1), {day})[0]['branch'] == '涨停突破'
    frame.loc[19, 'close'] = 10.1
    assert breakout_hits(frame, date(2025, 1, 1), {day}) == []
    frame.loc[19, 'close'] = 9
    frame.loc[20, 'ma_250'] = 10.5
    assert breakout_hits(frame, date(2025, 1, 1), {day}) == []


def test_insufficient_volume_history_and_window_boundary():
    frame = prices(20)
    assert breakout_hits(frame, date(2025, 1, 1)) == []
    frame = prices()
    day = frame.iloc[-1].feature_date.date()
    assert breakout_hits(frame, day)
    assert breakout_hits(frame, day + pd.Timedelta(days=1)) == []
    frame.loc[0, 'volume'] = None
    assert breakout_hits(frame, date(2025, 1, 1)) == []
