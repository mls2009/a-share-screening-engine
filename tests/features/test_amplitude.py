from datetime import date, datetime
from types import SimpleNamespace
from astock.features.amplitude import amplitude_summary


def bar(day, close=10, high=11, low=9, volume=100):
    return SimpleNamespace(timestamp=datetime.fromisoformat(day), close=close, high=high, low=low, volume_shares=volume, is_final=True)


def test_uses_previous_close_before_two_year_boundary_and_excludes_future():
    result = amplitude_summary([bar('2023-09-25',close=20),bar('2023-09-26'),bar('2025-09-26'),bar('2025-09-27',high=100)], date(2025,9,26))
    assert result['two_years']['value'] == 15
    assert result['two_years']['count'] == 2
    assert result['days20']['count'] == 2
    assert result['data_date'] == '2025-09-26'


def test_missing_previous_close_and_suspended_days_not_zero_samples():
    result = amplitude_summary([bar('2025-01-01'),bar('2025-01-02',volume=0),bar('2025-01-03')],date(2025,1,3))
    assert result['days20']['value'] == 20
    assert result['days20']['count'] == 1
    assert amplitude_summary([],date(2025,1,3))['days20']['value'] is None
