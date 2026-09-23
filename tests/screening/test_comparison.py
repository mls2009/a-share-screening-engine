import json
from datetime import datetime,timedelta
from uuid import uuid4
from astock.storage.database import Database
from astock.screening.comparison import previous_run_comparison


def test_previous_same_definition_scope_and_pagination(tmp_path):
    db=Database(tmp_path/'c.duckdb');db.migrate();con=db.connection
    tree={'kind':'condition','metric':'close','timeframe':'1d','operator':'gt','right':{'kind':'constant','value':10,'unit':'price'}}
    def run(n,symbols,scope=None,status='completed'):
        identifier=uuid4();stamp=datetime(2026,9,22,10)+timedelta(minutes=n)
        con.execute('insert into screen_runs(run_id,mode,as_of_date,feature_version,condition_tree,status,created_at,finished_at,diagnostics) values (?,\'close\',\'2026-09-21\',\'v1\',?,?,?,?,?)',[identifier,json.dumps(tree),status,stamp,stamp+timedelta(seconds=1),json.dumps({'scope':scope or {'scope':'market'}})])
        for i,symbol in enumerate(symbols):con.execute('insert into screen_matches(run_id,symbol,match_rank,feature_snapshot,explanation) values (?,?,?,\'{}\',\'{}\')',[identifier,symbol,i])
        return identifier
    first=run(0,['A']);assert previous_run_comparison(con,first) is None
    run(1,['B'],{'scope':'watchlist'})
    run(2,['B'],status='failed')
    current=run(3,['A','B'])
    result=previous_run_comparison(con,current)
    assert result['run_id']==str(first) and result['entered']==['B']
    assert result['finished_at']=='2026-09-22T10:00:01'
    run(4,['A','B'])
    assert previous_run_comparison(con,current)==result
