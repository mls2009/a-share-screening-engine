import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from astock.api.result_reviews import register_result_reviews
from astock.storage.database import Database


def test_review_is_persistent_scoped_idempotent_and_reversible(tmp_path):
    db = Database(tmp_path / 'reviews.duckdb')
    db.migrate()
    con = db.connection
    first, second = uuid4(), uuid4()
    for run in [first, second]:
        con.execute("insert into screen_matches(run_id,symbol,match_rank,feature_snapshot,explanation) values (?,'000001.SZ',1,'{}','{}')", [run])
    con.execute('create table sequoia_runs(run_id varchar,payload json)')
    con.execute('insert into sequoia_runs values (?,?)', [str(first), json.dumps({'matches':[{'symbol':'000001.SZ'}]})])
    app = FastAPI()
    register_result_reviews(app, db)
    client = TestClient(app)
    root = f'/api/result-reviews/screen/{first}'
    try:
        for _ in range(2):
            assert client.put(root+'/000001.SZ', json={'failed':True}).status_code == 200
        assert client.get(root).json() == ['000001.SZ']
        assert client.get(f'/api/result-reviews/screen/{second}').json() == []
        assert client.get(f'/api/result-reviews/sequoia/{first}').json() == []
        assert client.put(root+'/999999.SZ', json={'failed':True}).status_code == 404
        assert client.put(root+'/000001.SZ', json={'failed':'no'}).status_code == 422
        assert client.put(f'/api/result-reviews/sequoia/{first}/000001.SZ', json={'failed':True}).status_code == 200
        client.put(root+'/000001.SZ', json={'failed':False})
        assert client.get(root).json() == []
        assert client.get(f'/api/result-reviews/sequoia/{first}').json() == ['000001.SZ']
    finally:
        db.connection.close()


def test_same_conditions_inherit_legacy_failure_and_undo_across_runs(tmp_path):
    db = Database(tmp_path / 'inherit.duckdb')
    db.migrate()
    con = db.connection
    ids = [uuid4() for _ in range(3)]
    for index, run in enumerate(ids):
        tree = {'kind':'condition','metric':'close','timeframe':'1d','operator':'gt',
                'right':{'kind':'constant','value':10 if index < 2 else 11,'unit':'price'}}
        con.execute("insert into screen_runs(run_id,mode,feature_version,condition_tree,status) values (?,'close','v1',?,'completed')", [run,json.dumps(tree)])
        con.execute("insert into screen_matches(run_id,symbol,match_rank,feature_snapshot,explanation) values (?,'000001.SZ',1,'{}','{}')", [run])
    con.execute("insert into result_reviews(source,run_id,symbol) values ('screen',?,'000001.SZ')",[ids[0]])
    app = FastAPI()
    register_result_reviews(app,db)
    client = TestClient(app)
    endpoint = lambda run: f'/api/result-reviews/screen/{run}'
    assert client.get(endpoint(ids[1])).json() == ['000001.SZ']
    assert client.get(endpoint(ids[2])).json() == []
    assert client.put(endpoint(ids[1])+'/000001.SZ',json={'failed':False}).status_code == 200
    assert client.get(endpoint(ids[0])).json() == []
    db.connection.close()


def test_sequoia_same_parameters_ignore_date_and_order_but_not_threshold(tmp_path):
    db = Database(tmp_path / 'sequoia-reviews.duckdb')
    db.migrate()
    con = db.connection
    con.execute('create table sequoia_runs(run_id varchar,payload json)')
    ids = [uuid4() for _ in range(3)]
    for index, run in enumerate(ids):
        config = {'strategies':['turtle','ma_volume'] if index == 0 else ['ma_volume','turtle'],
                  'as_of':f'2026-09-{20+index}', 'period':'2y', 'minimum_matches':2,
                  'parameters':{'turtle':{'volume_ratio': 2 if index < 2 else 3}}}
        con.execute('insert into sequoia_runs values (?,?)', [str(run),json.dumps({'config':config,'matches':[{'symbol':'000001.SZ'}]})])
    app = FastAPI()
    register_result_reviews(app, db)
    client = TestClient(app)
    endpoint = lambda run: f'/api/result-reviews/sequoia/{run}'
    assert client.put(endpoint(ids[0])+'/000001.SZ',json={'failed':True}).status_code == 200
    assert client.get(endpoint(ids[1])).json() == ['000001.SZ']
    assert client.get(endpoint(ids[2])).json() == []
    client.put(endpoint(ids[1])+'/000001.SZ',json={'failed':False})
    assert client.get(endpoint(ids[0])).json() == []
    db.connection.close()
