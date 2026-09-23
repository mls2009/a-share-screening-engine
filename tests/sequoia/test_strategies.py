from datetime import date, timedelta

from astock.sequoia.strategies import evaluate, placement_dates, rps_scores


def bars(n=121):
    return [
        {
            "date": str(date(2025, 1, 1) + timedelta(days=i)),
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.0,
            "volume": 100.0,
            "amount": 2e8,
        }
        for i in range(n)
    ]


def test_turtle_excludes_signal_day_from_high_and_marks_reference_window():
    rows = bars(21)
    rows[-1].update(close=11.0, high=12.0, volume=200)
    result = evaluate("turtle", rows)
    assert result["result"] == "true"
    assert result["checks"][0]["actual"] == 11
    assert result["checks"][0]["expected"] == 10.5
    assert result["checks"][0]["mark"]["startDate"] == rows[0]["date"]
    rows[-1]["close"] = 10.5
    assert evaluate("turtle", rows)["result"] == "false"


def test_missing_and_zero_denominators_are_unknown_not_false_or_infinity():
    assert evaluate("ma_volume", bars(20))["result"] == "unknown"
    rows = bars()
    rows[-1]["volume"] = None
    assert evaluate("ma_volume", rows)["result"] == "unknown"
    rows[-2]["close"] = 0
    assert evaluate("shakeout", rows)["result"] == "unknown"


def test_original_fixed_limit_thresholds_and_no_rebound_requirement():
    rows = bars()
    rows[-2].update(close=11.0, high=11.0)
    rows[-1].update(open=12.0, close=11.5, low=11.0, volume=201.0)
    assert evaluate("shakeout", rows)["result"] == "true"
    rows[-1]["volume"] = 200
    assert evaluate("shakeout", rows)["result"] == "false"
    rows = bars()
    for row in rows[-21:-1]:
        row.update(close=12.0, high=12.0)
    rows[-1].update(close=10.8, volume=400.0)
    assert evaluate("trend_drop", rows)["result"] == "true"


def test_rps_ranks_full_eligible_population_with_average_ties():
    histories = {str(i): bars() for i in range(10)}
    for i, rows in enumerate(histories.values()):
        rows[-1]["close"] = 10 + i
    scores = rps_scores(histories)
    assert scores["8"] == 90
    assert scores["9"] == 100
    assert evaluate("rps", histories["8"], rps=scores["8"])["result"] == "true"
    histories["8"][-1]["close"] = 19
    assert rps_scores(histories)["8"] == 95
    histories["9"][0]["close"] = 0
    assert "9" not in rps_scores(histories)


def test_placement_uses_issuance_date_not_future_or_public_issuance():
    records = [
        {"股票代码": "600001", "发行日期": d, "发行方式": kind}
        for d, kind in [
            ("2026-09-10", "定向增发"),
            ("2026-09-15", "定向增发"),
            ("2026-09-14", "公开增发"),
        ]
    ]
    assert placement_dates(records, date(2026, 9, 14), 7) == {"600001": "2026-09-10"}


def test_ma_volume_strict_cross_and_high_flag_exact_windows():
    rows = bars(21)
    rows[-6:-1] = [{**r, "close": 9} for r in rows[-6:-1]]
    rows[-1].update(close=16.0, volume=200.0)
    assert evaluate("ma_volume", rows)["result"] == "true"
    rows = bars(40)
    rows[0]["low"] = 5
    for row in rows[-10:]:
        row.update(low=10.0, high=10.5)
    rows[-1]["volume"] = 50
    assert evaluate("high_flag", rows)["result"] == "true"
    rows[-1]["volume"] = 60
    assert evaluate("high_flag", rows)["result"] == "false"


def test_fixed_percentage_boundary_matches_original_price_comparison():
    rows = bars(3)
    rows[-2]["close"] = 10.95
    rows[-1].update(open=12, close=11.5, low=10.95, volume=250)
    assert evaluate("shakeout", rows)["result"] == "true"


def test_event_mark_uses_first_trading_day_on_or_after_issue():
    rows = bars(10)
    result = evaluate("placement", rows, issuance=rows[2]["date"])
    assert result["checks"][0]["mark"]["date"] == rows[2]["date"]


def test_missing_close_cannot_leak_nan_into_a_flag_match_snapshot():
    rows = bars(40)
    rows[-1]["close"] = float("nan")
    assert evaluate("high_flag", rows)["result"] == "unknown"


def test_event_after_last_trading_day_has_no_fabricated_candle_mark():
    result = evaluate("placement", bars(3), issuance="2025-01-04")
    assert result["result"] == "true"
    assert "mark" not in result["checks"][0]


def test_turtle_relative_volume_ignores_amount_and_excludes_today():
    rows = bars(21)
    rows[-1].update(close=11, high=11, volume=150, amount=1000)
    result=evaluate('turtle', rows)
    assert result['result']=='true'
    assert result['checks'][1]['actual']==1.5
    rows[-1].update(volume=149, amount=1e10)
    assert evaluate('turtle', rows)['result']=='false'
    for row in rows[:-1]:
        row['volume']=0
    assert evaluate('turtle', rows)['result']=='unknown'


def test_turtle_price_and_volume_windows_are_independent():
    rows=bars(31)
    rows[0]['high']=100
    rows[-1].update(close=11, high=11, volume=200)
    assert evaluate('turtle',rows,{'window':5,'volume_window':30})['result']=='true'


def test_turtle_verified_limit_close_exempts_volume_and_one_word_body():
    rows = bars(21)
    rows[-1].update(open=11, close=11, high=11, volume=1, limit_state='up')
    assert evaluate('turtle', rows)['result'] == 'true'
    rows[-1]['limit_state'] = None  # Intraday touch / missing verification is not enough.
    assert evaluate('turtle', rows)['result'] == 'false'
    rows[-1].update(limit_state='up', close=10.5)
    assert evaluate('turtle', rows)['result'] == 'false'


def test_turtle_limit_branch_does_not_require_volume_history():
    rows = bars(3)
    rows[-1].update(open=11, close=11, high=11, volume=None, limit_state='up')
    assert evaluate('turtle', rows, {'window': 2, 'volume_window': 20})['result'] == 'true'


def test_turtle_never_uses_partial_price_window_even_when_limit_up():
    for count in range(1, 21):
        rows = bars(count)
        rows[-1].update(open=10, close=11, high=11, volume=10000)
        assert evaluate('turtle', rows)['result'] == 'unknown'
        rows[-1]['limit_state'] = 'up'
        assert evaluate('turtle', rows)['result'] == 'unknown'
