"""Manual review flags, shared by source and equivalent screening conditions."""
import json
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, StrictBool


class ReviewRequest(BaseModel):
    failed: StrictBool


def _definition(con, source, run_id):
    if source == 'screen':
        from astock.screening.comparison import _tree
        row = con.execute('select mode,condition_tree from screen_runs where run_id=?', [run_id]).fetchone()
        return (row[0], _tree(row[1])) if row else None
    row = con.execute('select payload from sequoia_runs where run_id=?', [str(run_id)]).fetchone()
    config = json.loads(row[0]).get('config') if row else None
    if config is None:
        return None
    from astock.sequoia.strategies import BY_ID
    parameters = {}
    for strategy in config['strategies']:
        defaults = {key: spec['default'] for key, spec in BY_ID[strategy]['parameters'].items()}
        defaults.update(config.get('parameters', {}).get(strategy, {}))
        parameters[strategy] = defaults
    return (sorted(config['strategies']), parameters, config.get('period', 'latest'), config.get('minimum_matches', 1))


def _review_run_ids(con, source, run_id):
    definition = _definition(con, source, run_id)
    ids = [str(run_id)]
    if definition is not None:
        candidates = con.execute('select distinct run_id from result_reviews where source=? and run_id<>?', [source, run_id]).fetchall()
        ids.extend(str(row[0]) for row in candidates if _definition(con, source, row[0]) == definition)
    return ids


def reviewed_symbols(con, source, run_id):
    ids = _review_run_ids(con, source, run_id)
    failed = {row[0] for row in con.execute(
        'select symbol from result_reviews where source=? and cast(run_id as varchar) in (select unnest(?))',
        [source, ids]).fetchall()}
    if source == 'screen':
        current = {row[0] for row in con.execute('select symbol from screen_matches where run_id=?', [run_id]).fetchall()}
    else:
        row = con.execute('select payload from sequoia_runs where run_id=?', [str(run_id)]).fetchone()
        current = {match['symbol'] for match in json.loads(row[0]).get('matches', [])} if row else set()
    return sorted(failed & current)


def register_result_reviews(app, database):
    con = database.connection

    @app.get('/api/result-reviews/{source}/{run_id}')
    def reviews(source: Literal['screen', 'sequoia'], run_id: UUID):
        return reviewed_symbols(con, source, run_id)

    @app.put('/api/result-reviews/{source}/{run_id}/{symbol}')
    def save(source: Literal['screen', 'sequoia'], run_id: UUID, symbol: str, payload: ReviewRequest):
        if source == 'screen':
            exists = con.execute('select 1 from screen_matches where run_id=? and symbol=?', [run_id, symbol]).fetchone()
        else:
            row = con.execute('select payload from sequoia_runs where run_id=?', [str(run_id)]).fetchone()
            exists = row and any(m['symbol'] == symbol for m in json.loads(row[0]).get('matches', []))
        if not exists:
            raise HTTPException(404, '股票不在该次筛选结果中')
        if payload.failed:
            con.execute('insert into result_reviews(source,run_id,symbol) values (?,?,?) on conflict do nothing', [source, run_id, symbol])
        else:
            con.execute('delete from result_reviews where source=? and cast(run_id as varchar) in (select unnest(?)) and symbol=?',
                        [source, _review_run_ids(con, source, run_id), symbol])
        return {'symbol': symbol, 'failed': payload.failed}
