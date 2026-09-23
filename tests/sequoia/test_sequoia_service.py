import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from astock.sequoia.api import register_sequoia
from astock.sequoia.service import AddRequest, RunRequest, SequoiaService, today
from astock.storage.database import Database


@pytest.fixture
def service(tmp_path):
    db = Database(tmp_path / "sequoia.duckdb")
    db.migrate()
    for symbol in ["600001.SH", "600002.SH", "600003.SH"]:
        db.connection.execute(
            "insert into symbols(symbol,name,exchange) values (?,?,'SH')", [symbol, symbol]
        )
        for i in range(121):
            # Third stock stale. Second stronger, so first RPS must remain 50 even in a singleton watchlist.
            if symbol == "600003.SH" and i == 120:
                continue
            close = (11 if symbol == "600001.SH" else 12) if i == 120 else 10
            db.connection.execute(
                """insert into market_features(symbol,timeframe,feature_date,feature_version,open,high,low,close,volume,amount)
                 values (?,'1d',?,'v1',10,?,9.5,?,?,200000000)""",
                [symbol, date(2026, 1, 1) + timedelta(days=i), max(close, 10.5), close, 200 if i == 120 else 100],
            )
    instance = SequoiaService(db, placement_loader=list)
    yield instance
    db.connection.close()


def run(service, **kwargs):
    config = RunRequest(as_of=date(2026, 5, 1), strategies=["turtle"], **kwargs)
    record = service.start(config)
    service.run(record["run_id"])
    return service.get(record["run_id"])


def test_run_snapshots_group_checks_marks_and_stale_diagnostics(service):
    result = run(service)
    assert result["status"] == "completed"
    assert result["match_count"] == 2
    assert result["groups"][0]["unknown"] == 1
    assert result["matches"][0]["source"]["tree"]["children"][0]["label"] == "海龟突破"
    assert result["matches"][0]["source"]["marks"][0]["date"] == "2026-05-01"
    assert "matches" not in service.history()[0]


def test_add_is_idempotent_preserves_existing_sources_and_groups(service):
    result = run(service)
    con = service.con
    con.execute(
        "insert into watchlist values ('600001.SH','旧名','[{\"run_id\":\"older\"}]',current_timestamp)"
    )
    con.execute(
        "insert into watchlist_groups values ('00000000-0000-0000-0000-000000000001','原分组')"
    )
    con.execute(
        "insert into watchlist_group_members values ('00000000-0000-0000-0000-000000000001','600001.SH')"
    )
    payload = AddRequest(symbols=["600001.SH"], by_strategy=True)
    service.add_watchlist(result["run_id"], payload)
    service.add_watchlist(result["run_id"], payload)
    sources = json.loads(
        con.execute("select sources from watchlist where symbol='600001.SH'").fetchone()[0]
    )
    assert len(sources) == 2 and sources[0]["run_id"] == "older"
    assert sources[1]["marks"] and sources[1]["groups"][0]["name"] == "海龟突破"
    assert (
        con.execute(
            "select count(*) from watchlist_group_members where symbol='600001.SH'"
        ).fetchone()[0]
        == 2
    )
    with pytest.raises(HTTPException):
        service.add_watchlist(result["run_id"], AddRequest(symbols=["600001.SH", "600003.SH"]))
    assert con.execute("select count(*) from watchlist").fetchone()[0] == 1


def test_rps_keeps_market_denominator_under_watchlist_scope(service):
    service.con.execute("insert into watchlist(symbol,name) values ('600001.SH','一')")
    config = RunRequest(as_of=date(2026, 5, 1), strategies=["rps"], scope="watchlist")
    record = service.start(config)
    service.run(record["run_id"])
    result = service.get(record["run_id"])
    assert result["rps_universe_size"] == 2
    assert result["match_count"] == 0


def test_api_validates_future_unknown_parameters_and_memberships(service):
    app = FastAPI()
    # Reuse already initialized service through a DB-like wrapper.
    register_sequoia(app, SimpleNamespace(database=SimpleNamespace(connection=service.con)))
    client = TestClient(app)
    response = client.post(
        "/api/sequoia/runs", json={"as_of": "2026-05-01", "strategies": ["turtle"]}
    )
    assert response.status_code == 202
    identifier = response.json()["run_id"]
    assert client.get(f"/api/sequoia/runs/{identifier}").json()["match_count"] == 2
    assert (
        client.post(
            f"/api/sequoia/runs/{identifier}/watchlist",
            json={"symbols": ["600001.SH"], "group_id": "bad"},
        ).status_code
        == 422
    )
    for config in [
        {"strategies": ["bad"]},
        {"strategies": ["turtle"], "parameters": {"turtle": {"window": 1}}},
        {"strategies": ["turtle"], "as_of": str(today() + timedelta(days=1))},
        {"strategies": ["placement"], "as_of": "2025-01-01"},
    ]:
        assert client.post("/api/sequoia/runs", json=config).status_code == 422


def test_failed_event_feed_is_partial_and_other_groups_still_run(service):
    def broken():
        raise RuntimeError("feed offline")

    service.placement_loader = broken
    record = service.start(RunRequest(strategies=["turtle", "placement"]))
    service.run(record["run_id"])
    result = service.get(record["run_id"])
    assert result["status"] == "partial"
    assert result["match_count"] == 2
    assert result["groups"][1]["error"]
    assert result["groups"][1]["unknown"] == 3


def test_json_nonfinite_or_conflicting_destinations_rejected():
    with pytest.raises(ValidationError):
        RunRequest(strategies=["turtle"], parameters={"turtle": {"amount": float("nan")}})
    with pytest.raises(ValidationError):
        AddRequest(symbols=["x"], by_strategy=True, group_id="y")


def test_historical_range_keeps_multiple_dates_and_watchlist_marks(service):
    service.con.execute("update market_features set open=10, high=12, close=12, volume=200 where symbol='600001.SH' and feature_date='2026-04-29'")
    service.con.execute("update market_features set open=10, high=13, close=13 where symbol='600001.SH' and feature_date='2026-05-01'")
    result = run(service, period='1y')
    assert result['status'] == 'completed'
    match = next(m for m in result['matches'] if m['symbol']=='600001.SH')
    assert [h['date'] for h in match['groups'][0]['occurrences']] == ['2026-04-29','2026-05-01']
    assert {m['date'] for m in match['source']['marks']} == {'2026-04-29','2026-05-01'}
    assert result['range_start']=='2025-05-01'
    service.add_watchlist(result['run_id'], AddRequest(symbols=['600001.SH'], by_strategy=True))
    source=json.loads(service.con.execute("select sources from watchlist where symbol='600001.SH'").fetchone()[0])[0]
    assert len(source['groups'][0]['occurrences'])==2


def test_placement_rejects_historical_period():
    with pytest.raises(ValidationError):
        RunRequest(strategies=['placement'], period='2y')


def test_historical_rps_uses_each_days_full_market(service):
    service.con.execute("insert into watchlist(symbol,name) values ('600001.SH','一')")
    config=RunRequest(as_of=date(2026,5,1), period='2y', strategies=['rps'], scope='watchlist')
    record=service.start(config)
    service.run(record['run_id'])
    result=service.get(record['run_id'])
    assert result['status']=='completed'
    assert result['range_start']=='2024-05-01'
    assert result['match_count']==0  # One-stock watchlist must not turn RPS 50 into 100.


def test_historical_asof_uses_no_future_bars_and_excludes_outside_range(service):
    config=RunRequest(as_of=date(2026,4,30), period='1y', strategies=['turtle'])
    record=service.start(config);service.run(record['run_id'])
    assert service.get(record['run_id'])['match_count']==0
    config=RunRequest(as_of=today(), period='1y', strategies=['turtle'])
    from astock.sequoia.history import scan_history
    # A narrow requested history still gets pre-window warmup, but cannot emit old hits.
    config=config.model_copy(update={'as_of':date(2027,5,2)})
    result=scan_history(service.con,config,date(2027,5,2),lambda *_:None)
    assert result['matches']==[]


def test_turtle_consecutive_matches_are_one_episode_then_restart(service):
    for day, price, volume in [('2026-04-27',11,200),('2026-04-28',12,220),('2026-04-29',13,250),('2026-04-30',10,100),('2026-05-01',14,300)]:
        service.con.execute("update market_features set open=10,high=?,close=?,volume=? where symbol='600001.SH' and feature_date=?",[price,price,volume,day])
    result=run(service,period='2y')
    match=next(m for m in result['matches'] if m['symbol']=='600001.SH')
    hits=match['groups'][0]['occurrences']
    assert [(h['date'],h['end_date'],h['days']) for h in hits]==[('2026-04-27','2026-04-29',3),('2026-05-01','2026-05-01',1)]
    assert len(match['source']['marks'])==2
    assert all(m['date']==m['startDate'] and m['periods']==1 for m in match['source']['marks'])


def test_turtle_pullback_and_low_volume_do_not_restart_until_fixed_level_breaks(service):
    sequence=[('2026-04-24',11,200),('2026-04-25',12,220),('2026-04-26',11.2,80),
              ('2026-04-27',10.5,80),('2026-04-28',13,250),('2026-04-29',10.4,100),
              ('2026-04-30',14,300),('2026-05-01',13,80)]
    for day,price,volume in sequence:
        service.con.execute("update market_features set open=10,high=?,close=?,volume=? where symbol='600001.SH' and feature_date=?",[price,price,volume,day])
    result=run(service,period='2y')
    match=next(m for m in result['matches'] if m['symbol']=='600001.SH')
    hits=match['groups'][0]['occurrences']
    assert len(hits)==2
    assert hits[0]['date']=='2026-04-24' and hits[0]['breakout_level']==10.5
    assert hits[0]['end_date']=='2026-04-28' and hits[0]['ended_on']=='2026-04-29'
    assert hits[1]['date']=='2026-04-30' and hits[1]['breakout_level']==13
    assert hits[1]['end_date']=='2026-05-01' and hits[1]['active'] is True
    assert len(match['source']['marks'])==2


@pytest.mark.parametrize('period', ['latest', '1y'])
def test_limit_breakout_uses_raw_close_and_dated_limit(service, tmp_path, period):
    import pandas as pd
    from astock.storage.bars import BarStore
    service.bar_store = BarStore(tmp_path / 'bars')
    path = service.bar_store.root / 'timeframe=1d' / 'year=2026' / '600001.SH.parquet'
    path.parent.mkdir(parents=True)
    # QFQ price 11 must be checked against RAW close 22, not raw limit 22 directly.
    pd.DataFrame([dict(timestamp='2026-05-01T15:00:00+08:00', adjustment='none',
                       close=22.0, is_final=True)]).to_parquet(path)
    service.con.execute("update market_features set open=11,volume=1 where symbol='600001.SH' and feature_date='2026-05-01'")
    service.con.execute("insert into security_status values ('600001.SH','2026-05-01','main',false,false,20,22,18)")
    result = run(service, period=period)
    assert result['status'] == 'completed'
    match = next(m for m in result['matches'] if m['symbol']=='600001.SH')
    assert any('收盘真实涨停' in c['label'] for c in match['groups'][0]['checks'])
    # Touching the limit but closing below it cannot use the exemption.
    pd.DataFrame([dict(timestamp='2026-05-01T15:00:00+08:00', adjustment='none',
                       close=21.99, is_final=True)]).to_parquet(path)
    result = run(service, period=period)
    assert all(m['symbol'] != '600001.SH' for m in result['matches'])


def test_minimum_strategy_matches_validates_selected_count():
    assert RunRequest(strategies=['turtle', 'rps'], minimum_matches=2).minimum_matches == 2
    with pytest.raises(ValidationError):
        RunRequest(strategies=['turtle', 'rps'], minimum_matches=3)
    with pytest.raises(ValidationError):
        RunRequest(strategies=['turtle'], minimum_matches=0)


def test_latest_requires_two_strategies_on_same_market_day(service):
    config = RunRequest(as_of=date(2026, 5, 1), strategies=['turtle', 'rps'], minimum_matches=2)
    record = service.start(config)
    service.run(record['run_id'])
    result = service.get(record['run_id'])
    assert result['status'] == 'completed'
    assert [m['symbol'] for m in result['matches']] == ['600002.SH']
    assert {g['id'] for g in result['matches'][0]['groups']} == {'turtle', 'rps'}
    assert result['config']['minimum_matches'] == 2
    assert result['matches'][0]['source']['tree']['logic'] == 'at_least'
    assert result['matches'][0]['source']['tree']['minimumMatches'] == 2


def test_latest_can_require_three_selected_strategies(service):
    service.con.execute("update market_features set close=9.9 where symbol='600002.SH' and feature_date between '2026-04-26' and '2026-04-30'")
    config = RunRequest(as_of=date(2026, 5, 1), strategies=['turtle', 'ma_volume', 'rps'], minimum_matches=3)
    record = service.start(config)
    service.run(record['run_id'])
    result = service.get(record['run_id'])
    assert result['status'] == 'completed'
    assert [m['symbol'] for m in result['matches']] == ['600002.SH']
    assert {g['id'] for g in result['matches'][0]['groups']} == {'turtle', 'ma_volume', 'rps'}


def test_history_combines_only_strategies_matching_the_same_day(service):
    service.con.execute("update market_features set open=10,high=12,close=12,volume=200 where symbol='600001.SH' and feature_date='2026-05-01'")
    service.con.execute("update market_features set high=11,close=11 where symbol='600002.SH' and feature_date='2026-05-01'")
    service.con.execute("""insert into market_features(symbol,timeframe,feature_date,feature_version,open,high,low,close,volume,amount)
        values ('600001.SH','1d','2026-05-02','v1',10,13,9.5,13,200,200000000)""")
    config = RunRequest(as_of=date(2026, 5, 2), period='1y', strategies=['turtle', 'rps'], minimum_matches=2)
    record = service.start(config)
    service.run(record['run_id'])
    result = service.get(record['run_id'])
    assert result['status'] == 'completed'
    assert [m['symbol'] for m in result['matches']] == ['600001.SH']
    match = result['matches'][0]
    assert match['confluence_dates'] == ['2026-05-01', '2026-05-02']
    assert {g['id'] for g in match['groups']} == {'turtle', 'rps'}
    assert [h['date'] for g in match['groups'] if g['id']=='turtle' for h in g['occurrences']] == ['2026-05-01']


def test_history_does_not_combine_different_days_to_meet_threshold(service):
    service.con.execute("insert into watchlist(symbol,name) values ('600001.SH','一')")
    service.con.execute("""insert into market_features(symbol,timeframe,feature_date,feature_version,open,high,low,close,volume,amount)
        values ('600001.SH','1d','2026-05-02','v1',10.5,10.6,10,10.5,100,100000000)""")
    config = RunRequest(as_of=date(2026, 5, 2), period='1y', scope='watchlist', strategies=['turtle', 'rps'], minimum_matches=2)
    record = service.start(config)
    service.run(record['run_id'])
    result = service.get(record['run_id'])
    assert result['status'] == 'completed'
    assert result['matches'] == []
