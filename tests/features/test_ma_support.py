import pandas as pd
from astock.features.ma_support import support_hits


def frame():
    rows = pd.DataFrame({'feature_date': pd.date_range('2025-01-01', periods=90),
                         'open': 11., 'high': 11.2, 'close': 11., 'low': 10.5,
                         'ma_120': 10., 'ma_250': 20.})
    rows.loc[20, 'low'] = 10
    rows.loc[45, 'low'] = 10
    rows.loc[70, ['open', 'close', 'low']] = [10.3, 10.4, 10.]
    return rows


def test_first_support_does_not_require_pinbar():
    hits = support_hits(frame())
    hit = next(h for h in hits if h['date'] == '2025-03-12')
    assert hit['first_date'] == '2025-01-21'
    assert hit['supports'][1]['confirmation_end'] == '2025-03-07'
    assert '单K' in hit['types']


def test_close_below_ma_invalidates_first_support_but_intraday_dip_does_not():
    rows = frame()
    rows.loc[30, 'low'] = 9
    assert any(h['date'] == '2025-03-12' for h in support_hits(rows))
    rows.loc[30, 'close'] = 9.9
    assert not any(h['date'] == '2025-03-12' for h in support_hits(rows))


def test_double_bar_uses_combined_body_and_low():
    rows = frame()
    rows.loc[69, ['open', 'close', 'low']] = [10.4, 10.05, 10.]
    rows.loc[70, ['open', 'close', 'low']] = [10.05, 10.45, 10.04]
    hit = next(h for h in support_hits(rows) if h['date'] == '2025-03-12')
    assert hit['types'] == ['双K']
    assert hit['start_date'] == '2025-03-11'


def test_confirmation_must_finish_before_second_pattern():
    rows = frame()
    rows.loc[20, ['open', 'close', 'low']] = [10.3, 10.4, 10.]
    assert not any(h['date'] == '2025-01-21' for h in support_hits(rows))


def test_store_and_marks_include_both_supports_and_confirmation(tmp_path):
    from astock.storage.database import Database
    from astock.features.store import MarketFeatureStore
    from astock.features.ma_support import MA_SUPPORT_METRIC, MA_SUPPORT_HITS
    from astock.domain.market import Timeframe
    from astock.screening.annotations import condition_marks
    db = Database(tmp_path / 'support.duckdb')
    db.migrate()
    rows = frame()
    db.connection.executemany(
        "insert into market_features (symbol,timeframe,feature_date,feature_version,open,high,close,low,ma_120,ma_250) values ('000001.SZ','1d',?,'v1',?,?,?,?,?,?)",
        [(r.feature_date.date(), r.open, r.high, r.close, r.low, r.ma_120, r.ma_250) for r in rows.itertuples()])
    history = MarketFeatureStore(db).read_history('000001.SZ', Timeframe.DAY, rows.iloc[-1].feature_date.date(), 1,
                                                 enrich=False, include_ma_support=True)
    assert history[0][MA_SUPPORT_METRIC] is True
    tree = dict(kind='condition', metric=MA_SUPPORT_METRIC, timeframe='1d', operator='eq')
    marks = condition_marks(tree, {'result': 'true'}, {Timeframe.DAY: history})
    assert len(marks) == 5 * len(history[0][MA_SUPPORT_HITS])
    assert any('本次命中' in m['label'] and m['date'] == '2025-03-12' for m in marks)
    assert any('20日收盘站稳' in m['label'] and m['startDate'] == '2025-01-22' for m in marks)
    db.connection.close()


def test_initial_twenty_rows_cannot_count_and_broken_support_resets():
    rows = frame()
    rows.loc[20, 'low'] = 10.5
    rows.loc[0, 'low'] = 10
    assert support_hits(rows) == []
    rows = frame()
    rows.loc[42, 'close'] = 9.9
    assert support_hits(rows) == []
    rows = frame()
    rows.loc[67, 'close'] = 10
    assert support_hits(rows) == []


def test_touch_inside_confirmation_cannot_be_second_support():
    rows = frame()
    rows.loc[45, 'low'] = 10.5
    rows.loc[30, 'low'] = 10
    assert support_hits(rows) == []


def test_can_requalify_after_break_and_does_not_use_future_confirmation():
    rows = pd.concat([frame(), frame().iloc[:60]], ignore_index=True)
    rows['feature_date'] = pd.date_range('2025-01-01', periods=len(rows))
    rows.loc[71:, ['open', 'close', 'low']] = [11., 11., 10.5]
    rows.loc[72, 'close'] = 9.9
    rows.loc[[75, 100], 'low'] = 10
    rows.loc[125, ['open', 'close', 'low']] = [10.3, 10.4, 10.]
    hits = support_hits(rows)
    later = next(h for h in hits if h['date'] == str(rows.loc[125, 'feature_date'].date()))
    assert later['first_date'] == str(rows.loc[75, 'feature_date'].date())
    before = support_hits(rows.iloc[:121])
    assert all(h['date'] <= str(rows.loc[70, 'feature_date'].date()) for h in before)


def test_ma120_requires_candle_to_cross_average_while_ma250_keeps_two_percent():
    rows = frame()
    rows['high'] = 11.2
    rows.loc[20, 'low'] = 10.1
    assert support_hits(rows) == []

    rows.loc[20, 'low'] = 9.9
    assert any(hit['ma'] == 120 for hit in support_hits(rows))

    annual = frame()
    annual['high'] = 11.2
    annual['ma_120'] = 20.
    annual['ma_250'] = 10.
    annual.loc[[20, 45, 70], 'low'] = 10.1
    assert any(hit['ma'] == 250 for hit in support_hits(annual))


def test_ma120_rejects_both_second_support_and_final_visit_above_average():
    rows = frame()
    rows['high'] = 11.2
    rows.loc[45, 'low'] = 10.1
    assert support_hits(rows) == []

    rows.loc[45, 'low'] = 10.
    rows.loc[70, 'low'] = 10.1
    assert support_hits(rows) == []
