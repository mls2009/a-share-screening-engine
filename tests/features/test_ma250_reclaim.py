from datetime import date

import pandas as pd
import pytest

from astock.features.ma250_reclaim import MA250_RECLAIM_METRIC, MA250_RECLAIM_EXTENDED_METRIC, reclaim_hits


def frame(closes, averages=None):
    return pd.DataFrame({'feature_date': pd.bdate_range('2025-01-01', periods=len(closes)),
                         'close': closes, 'ma_250': averages or [10.] * len(closes)})


@pytest.mark.parametrize('closes,days', [([11, 9, 11, 12], 1), ([11, 9, 9, 11], 2), ([11, 9, 10, 11], 2)])
def test_original_recovery_within_two_sessions(closes, days):
    hits = reclaim_hits(frame(closes), date(2025, 1, 1))
    assert len(hits) == 1
    assert hits[0]['recovery_days'] == days
    assert hits[0]['start_date'] == '2025-01-02'


@pytest.mark.parametrize('closes', [[9, 9, 11], [10, 9, 11], [11, 10, 11], [11, 9, 9, 9, 9, 11], [11, 9, 10], [11, 9], [None, 9, 11]])
def test_no_false_breaks_or_late_recovery(closes):
    assert reclaim_hits(frame(closes), date(2025, 1, 1)) == []


def test_extended_recovery_allows_third_session_without_changing_original():
    rows = frame([11, 9, 9, 9, 11])
    assert reclaim_hits(rows, date(2025, 1, 1)) == []
    assert reclaim_hits(rows, date(2025, 1, 1), max_days=3)[0]['recovery_days'] == 3


def test_original_and_extended_metrics_are_separate_catalog_conditions():
    from astock.screening.catalog import DEFAULT_CATALOG
    from astock.features.ma250_reclaim import uses_ma250_reclaim
    metrics = {metric.key: metric for metric in DEFAULT_CATALOG.all()}
    assert MA250_RECLAIM_METRIC in metrics
    assert MA250_RECLAIM_EXTENDED_METRIC in metrics
    assert '1～2' in metrics[MA250_RECLAIM_METRIC].label
    assert '1～3' in metrics[MA250_RECLAIM_EXTENDED_METRIC].label
    for metric in (MA250_RECLAIM_METRIC, MA250_RECLAIM_EXTENDED_METRIC):
        assert uses_ma250_reclaim({'kind':'condition','metric':metric})


def test_each_close_uses_its_own_average_and_all_hits_are_preserved():
    hits = reclaim_hits(frame([11, 9, 9.5, 8, 9], [10, 10, 9, 9, 8.5]), date(2025, 1, 1))
    assert len(hits) == 2
    assert reclaim_hits(frame([11, 9, 11]), date(2025, 1, 3)) == []


def test_store_boundary_asof_and_chart_evidence(tmp_path):
    from astock.storage.database import Database
    from astock.features.store import MarketFeatureStore
    from astock.features.ma250_reclaim import MA250_RECLAIM_METRIC, MA250_RECLAIM_HITS, MA250_RECLAIM_EXTENDED_METRIC, MA250_RECLAIM_EXTENDED_HITS
    from astock.domain.market import Timeframe
    from astock.screening.annotations import condition_marks, entry_histories

    db = Database(tmp_path / 'reclaim.duckdb')
    db.migrate()
    db.connection.executemany(
        "insert into market_features(symbol,timeframe,feature_date,feature_version,close,ma_250) values ('000001.SZ','1d',?,'v1',?,10)",
        [('2023-01-02', 11), ('2023-01-03', 9), ('2023-01-04', 11), ('2025-01-03', 12)])
    store = MarketFeatureStore(db)
    history = store.read_history('000001.SZ', Timeframe.DAY, date(2025, 1, 3), 1, enrich=False, include_ma250_reclaim=True)
    assert history[0][MA250_RECLAIM_METRIC] is True
    assert history[0][MA250_RECLAIM_EXTENDED_METRIC] is True
    assert history[0][MA250_RECLAIM_HITS][0]['start_date'] == '2023-01-03'
    tree = dict(kind='condition', metric=MA250_RECLAIM_METRIC, timeframe='1d', operator='eq', right=dict(kind='constant', value=True, unit='boolean'))
    marks = condition_marks(tree, {'result': 'true'}, {Timeframe.DAY: history})
    assert len(marks) == 1
    assert marks[0]['startDate'] == '2023-01-03'
    assert marks[0]['date'] == '2023-01-04'
    frozen = entry_histories({Timeframe.DAY: [{}]}, 'close', date(2025, 1, 3), history[0])
    assert condition_marks(tree, {'result': 'true'}, frozen) == marks
    earlier = store.read_histories(['000001.SZ'], Timeframe.DAY, date(2023, 1, 3), 1, enrich=False, include_ma250_reclaim=True)
    assert earlier['000001.SZ'][0][MA250_RECLAIM_METRIC] is False
    later = store.read_history('000001.SZ', Timeframe.DAY, date(2025, 1, 4), 1, enrich=False, include_ma250_reclaim=True)
    assert later[0][MA250_RECLAIM_METRIC] is False
    # Five newer market sessions exclude an old hit even if this stock has no new rows.
    db.connection.executemany(
        "insert into market_features(symbol,timeframe,feature_date,feature_version,close,ma_250) values ('000002.SZ','1d',?,'v1',12,10)",
        [(day.date(),) for day in pd.bdate_range('2023-01-05', periods=5)])
    stale = store.read_history('000001.SZ', Timeframe.DAY, date(2025, 1, 3), 1, enrich=False, include_ma250_reclaim=True)
    assert stale[0][MA250_RECLAIM_METRIC] is True
    assert stale[0][MA250_RECLAIM_EXTENDED_METRIC] is False
    assert stale[0][MA250_RECLAIM_EXTENDED_HITS] == []
    db.connection.close()


def test_single_and_double_shadow_support_without_prior_supports():
    from astock.features.ma250_reclaim import shadow_support_hits
    rows = frame([10.4, 10.45])
    rows['open'] = [10.4, 10.05]
    rows['low'] = [10., 10.04]
    hits = shadow_support_hits(rows, date(2025,1,1))
    assert hits[0]['types'] == ['单K']
    assert hits[1]['types'] == ['双K']
    assert hits[1]['start_date'] == '2025-01-01'
    rows['low'] = 10.3
    assert shadow_support_hits(rows, date(2025,1,1)) == []
    rows['close'] = 9.9
    assert shadow_support_hits(rows, date(2025,1,1)) == []


def test_shadow_support_marks_its_actual_two_candle_span():
    from astock.screening.annotations import condition_marks
    from astock.domain.market import Timeframe
    from astock.features.ma250_reclaim import MA250_RECLAIM_EXTENDED_METRIC, MA250_RECLAIM_EXTENDED_HITS, shadow_support_hits
    rows = frame([10.05,10.45])
    rows['open'] = [10.4,10.05]
    rows['low'] = [10.,10.04]
    hits = shadow_support_hits(rows,date(2025,1,1))
    marks = condition_marks({'kind':'condition','metric':MA250_RECLAIM_EXTENDED_METRIC,'timeframe':'1d'},
                            {'result':'true'}, {Timeframe.DAY:[{MA250_RECLAIM_EXTENDED_HITS:hits}]})
    assert len(marks) == 1
    assert marks[0]['startDate'] == '2025-01-01'
    assert marks[0]['date'] == '2025-01-02'
    assert '年线下影支撑·双K' in marks[0]['label']
