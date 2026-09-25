from datetime import date

import pytest

from astock.screening.sequoia_confluence import ma120_branch, select_hits


@pytest.mark.parametrize('opening,close,average,expected', [
    (100, 101, 100, '实体上穿'), (99, 101, 100, '实体上穿'),
    (101, 99, 100, '开盘在MA120上方10%以内'),
    (110, 111, 100, '开盘在MA120上方10%以内'),
    (110.01, 111, 100, None), (99, 100, 100, None),
    (99, 99, 100, None), (100, 101, None, None),
    (100, 101, float('nan'), None),
])
def test_ma120_boundaries(opening, close, average, expected):
    assert ma120_branch(opening, close, average) == expected


def test_only_same_day_confluence_within_calendar_two_years():
    quotes = {d: {'open': 100, 'close': 101, 'ma_120': 100}
              for d in ['2024-09-23', '2024-09-24', '2025-03-04', '2026-09-24', '2026-09-25']}
    hits = select_hits(list(quotes), quotes, date(2026, 9, 24))
    assert [h['date'] for h in hits] == ['2024-09-24', '2025-03-04', '2026-09-24']
    assert select_hits(['2025-01-01'], quotes, date(2026, 9, 24)) == []


def test_double_volume_preserves_limit_up_exemption():
    from astock.sequoia.strategies import evaluate
    rows = [{'date': f'2026-01-{i+1:02}', 'open': 10, 'high': 10, 'low': 10,
                 'close': 10, 'volume': 100} for i in range(21)]
    rows[-1].update(open=11, high=11, close=11, limit_state='up', volume=199)
    assert evaluate('turtle', rows, {'volume_multiple': 2})['result'] == 'true'
    assert evaluate('turtle', rows, {'volume_multiple': 2}, strict_volume=True)['result'] == 'true'
    rows[-1].pop('limit_state')
    rows[-1]['open'] = 10
    assert evaluate('turtle', rows, {'volume_multiple': 2}, strict_volume=True)['result'] == 'false'
    rows[-1]['volume'] = 200
    assert evaluate('turtle', rows, {'volume_multiple': 2}, strict_volume=True)['result'] == 'true'


def test_ma_volume_includes_exact_double():
    from astock.sequoia.strategies import evaluate
    rows = [{'date': f'2026-01-{i+1:02}', 'close': 10, 'volume': 18} for i in range(21)]
    for row in rows[-6:-1]:
        row['close'] = 9
    rows[-1].update(close=20, volume=38)  # (19*18 + 38)/20 = 19
    assert evaluate('ma_volume', rows, {'volume_multiple': 2})['result'] == 'false'
    assert evaluate('ma_volume', rows, {'volume_multiple': 2}, strict_volume=True)['result'] == 'true'


def test_saved_evidence_marks_every_hit_without_rescanning():
    from astock.screening.annotations import condition_marks, entry_histories
    from astock.screening.sequoia_confluence import HITS, METRIC
    hits = [{'date': d, 'open': 100, 'close': 101, 'ma120': 100, 'branch': '实体上穿'}
            for d in ['2025-03-04', '2026-09-24']]
    tree = {'kind': 'condition', 'metric': METRIC, 'timeframe': '1d', 'operator': 'eq',
                'right': {'kind': 'constant', 'value': True, 'unit': 'boolean'}}
    histories = entry_histories({}, 'close', date(2026, 9, 24), {HITS: hits})
    marks = condition_marks(tree, {'result': 'true'}, histories)
    assert [m['date'] for m in marks] == [h['date'] for h in hits]
    assert all('MA120' in m['label'] for m in marks)


def test_attach_reuses_strict_scanner_and_freezes_ma_values(tmp_path, monkeypatch):
    from astock.screening import sequoia_confluence as module
    from astock.storage.database import Database
    db = Database(tmp_path / 'test.duckdb')
    db.migrate()
    try:
        db.connection.execute("""insert into market_features
            (symbol,timeframe,feature_date,feature_version,open,close,ma_120)
            values ('600001.SH','1d','2026-01-05','v1',100,101,100)""")
        def scan(con, config, end, progress, bars, **kwargs):
            assert kwargs == {'scope_symbols': {'600001.SH'}, 'strict_volume': True}
            assert config.parameters == {'turtle': {'volume_multiple': 2}, 'ma_volume': {'volume_multiple': 2}}
            assert config.minimum_matches == 3
            return {'matches': [{'symbol': '600001.SH', 'confluence_dates': ['2026-01-05']}], 'range_start': '2024-09-24'}
        monkeypatch.setattr(module, 'scan_history', scan)
        histories = {'600001.SH': [{'feature_date': date(2026, 9, 24)}]}
        module.attach_confluence(db.connection, histories, date(2026, 9, 24), lambda *_: None)
        assert histories['600001.SH'][0][module.METRIC] is True
        assert histories['600001.SH'][0][module.HITS][0]['ma120'] == 100
    finally:
        db.connection.close()


def test_real_historical_scan_keeps_market_rps_when_scope_is_one_stock(tmp_path):
    from datetime import timedelta

    from astock.screening.sequoia_confluence import METRIC, attach_confluence
    from astock.storage.database import Database
    db = Database(tmp_path / 'market.duckdb')
    db.migrate()
    end = date(2026, 1, 1)
    try:
        for symbol, final in [('600001.SH', 20), ('600002.SH', 21)]:
            db.connection.execute("insert into symbols(symbol,name,exchange,instrument_type) values (?,?,'SH','stock')", [symbol,symbol])
            values = []
            for i in range(121):
                close = final if i == 120 else 9 if 115 <= i < 120 else 10
                values.append([symbol, end - timedelta(days=120-i), 10, max(10.5,close), 9, close, 500 if i == 120 else 100, 1000, 10])
            db.connection.executemany("""insert into market_features
                (symbol,timeframe,feature_date,feature_version,open,high,low,close,volume,amount,ma_120)
                values (?,'1d',?,'v1',?,?,?,?,?,?,?)""", values)
        for symbol, expected in [('600001.SH',False),('600002.SH',True)]:
            histories = {symbol: [{'feature_date':end}]}
            attach_confluence(db.connection, histories, end, lambda *_: None)
            assert histories[symbol][0][METRIC] is expected
    finally:
        db.connection.close()
