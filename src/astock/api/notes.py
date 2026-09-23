"""Research notes: independent of market data and trading signals."""
import json
from threading import Lock
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from astock.storage.database import Database


class NoteInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default='', max_length=100000)
    group_id: UUID | None = None
    symbol: str | None = Field(default=None, max_length=32)
    chart: dict | None = None
    annotations: list[dict] = Field(default_factory=list, max_length=1000)
    revision: int | None = None


class GroupInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


def register_notes(app: FastAPI, database: Database):
    con = database.connection
    lock = Lock()
    con.execute('''create table if not exists research_note_groups (
        id varchar primary key, name varchar not null);
        create table if not exists research_notes (
        id varchar primary key, title varchar not null, body varchar not null,
        group_id varchar, symbol varchar, chart varchar, annotations varchar not null,
        revision integer not null default 1, updated_at timestamp default current_timestamp)''')

    def read(note_id):
        row = con.execute('select * from research_notes where id = ?', [str(note_id)]).fetchone()
        if row is None:
            raise HTTPException(404, '笔记不存在')
        keys = ['id', 'title', 'body', 'group_id', 'symbol', 'chart', 'annotations', 'revision', 'updated_at']
        result = dict(zip(keys, row))
        result['chart'] = json.loads(result['chart']) if result['chart'] else None
        result['annotations'] = json.loads(result['annotations'])
        return result

    @app.get('/api/notes/groups')
    def groups():
        return [dict(zip(['id', 'name'], row)) for row in con.execute('select id, name from research_note_groups order by name').fetchall()]

    @app.post('/api/notes/groups')
    def create_group(value: GroupInput):
        group_id = str(uuid4())
        con.execute('insert into research_note_groups values (?, ?)', [group_id, value.name])
        return {'id': group_id, 'name': value.name}

    @app.put('/api/notes/groups/{group_id}')
    def rename_group(group_id: UUID, value: GroupInput):
        if not con.execute('update research_note_groups set name = ? where id = ? returning id', [value.name, str(group_id)]).fetchone():
            raise HTTPException(404, '分组不存在')
        return {'id': str(group_id), 'name': value.name}

    @app.delete('/api/notes/groups/{group_id}', status_code=204)
    def delete_group(group_id: UUID):
        with lock:
            con.execute('begin transaction')
            try:
                con.execute('update research_notes set group_id = null, revision = revision + 1 where group_id = ?', [str(group_id)])
                con.execute('delete from research_note_groups where id = ?', [str(group_id)])
                con.execute('commit')
            except Exception:
                con.execute('rollback')
                raise

    @app.get('/api/notes')
    def notes(symbol: str | None = None):
        rows = con.execute('''select id, title, group_id, symbol, revision, updated_at,
            chart is not null as has_chart from research_notes
            where (? is null or symbol = ?) order by updated_at desc''', [symbol, symbol]).fetchall()
        return [dict(zip(['id', 'title', 'group_id', 'symbol', 'revision', 'updated_at', 'has_chart'], row)) for row in rows]

    def save(value, note_id=None):
        with lock:
            if value.group_id and not con.execute('select 1 from research_note_groups where id = ?', [str(value.group_id)]).fetchone():
                raise HTTPException(422, '笔记分组不存在，请重新选择')
            if note_id:
                old = read(note_id)
                if value.revision != old['revision']:
                    raise HTTPException(409, '笔记已在其他页面修改，请重新打开后编辑')
            chart = json.dumps(value.chart, ensure_ascii=False) if value.chart else None
            if chart and len(chart) > 12_000_000:
                raise HTTPException(413, '图表快照过大')
            fields = [value.title, value.body, str(value.group_id) if value.group_id else None,
                      value.symbol, chart, json.dumps(value.annotations, ensure_ascii=False)]
            if note_id:
                con.execute('''update research_notes set title=?, body=?, group_id=?, symbol=?, chart=?,
                    annotations=?, revision=revision+1, updated_at=current_timestamp where id=?''', [*fields, str(note_id)])
            else:
                note_id = str(uuid4())
                con.execute('insert into research_notes(id,title,body,group_id,symbol,chart,annotations) values (?,?,?,?,?,?,?)', [note_id, *fields])
            return read(note_id)

    @app.post('/api/notes')
    def create(value: NoteInput):
        return save(value)

    @app.get('/api/notes/{note_id}')
    def get(note_id: UUID):
        return read(note_id)

    @app.put('/api/notes/{note_id}')
    def update(note_id: UUID, value: NoteInput):
        return save(value, note_id)

    @app.delete('/api/notes/{note_id}', status_code=204)
    def delete(note_id: UUID):
        with lock:
            con.execute('delete from research_notes where id = ?', [str(note_id)])
