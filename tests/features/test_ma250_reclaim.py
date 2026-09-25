from datetime import date

import pandas as pd
import pytest

from astock.features.ma250_reclaim import reclaim_hits


def frame(closes, averages=None):
    return pd.DataFrame({'feature_date': pd.bdate_range('2025-01-01', periods=len(closes)),
                         'close': closes, 'ma_250': averages or [10.] * len(closes)})


@pytest.mark.parametrize('closes,days', [([11, 9, 11, 12], 1), ([11, 9, 9, 11], 2), ([11, 9, 10, 11], 2)])
def test_first_recovery_within_two_sessions(closes, days):
    hits = reclaim_hits(frame(closes), date(2025, 1, 1))
    assert len(hits) == 1
    assert hits[0]['recovery_days'] == days
    assert hits[0]['start_date'] == '2025-01-02'


@pytest.mark.parametrize('closes', [[9, 9, 11], [10, 9, 11], [11, 10, 11], [11, 9, 9, 9, 11], [11, 9, 10], [11, 9], [None, 9, 11]])
def test_no_false_breaks_or_late_recovery(closes):
    assert reclaim_hits(frame(closes), date(2025, 1, 1)) == []


def test_each_close_uses_its_own_average_and_all_hits_are_preserved():
    hits = reclaim_hits(frame([11, 9, 9.5, 8, 9], [10, 10, 9, 9, 8.5]), date(2025, 1, 1))
    assert len(hits) == 2
    assert reclaim_hits(frame([11, 9, 11]), date(2025, 1, 3)) == []


def test_store_boundary_asof_and_chart_evidence(tmp_path):
    from astock.storage.database import Database
    from astock.features.store import MarketFeatureStore
    from astock.features.ma250_reclaim import MA250_RECLAIM_METRIC, MA250_RECLAIM_HITS
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
    db.connection.close()
