from fastapi import FastAPI
from fastapi.testclient import TestClient
from astock.storage.database import Database
from astock.api.notes import register_notes


def test_notes_persist_chart_edit_and_group_delete(tmp_path):
    db = Database(tmp_path / 'notes.duckdb')
    app = FastAPI()
    register_notes(app, db)
    client = TestClient(app)
    group = client.post('/api/notes/groups', json={'name': '复盘'}).json()
    payload = {'title': '突破观察', 'body': '等待确认', 'group_id': group['id'],
               'symbol': '000012.SZ', 'chart': {'image': 'data:image/png;base64,AA==', 'timeframe': '1d'},
               'annotations': [{'id': 'a1', 'kind': 'text', 'x': 10, 'y': 20, 'text': '突破'}]}
    created = client.post('/api/notes', json=payload)
    assert created.status_code == 200
    note = created.json()
    assert client.get('/api/notes?symbol=000012.SZ').json()[0]['id'] == note['id']
    assert 'chart' not in client.get('/api/notes').json()[0]
    payload['body'] = '修改后的判断'
    updated = client.put('/api/notes/' + note['id'], json={**payload, 'revision': note['revision']})
    assert updated.status_code == 200
    assert client.put('/api/notes/' + note['id'], json={**payload, 'revision': note['revision']}).status_code == 409
    client.delete('/api/notes/groups/' + group['id'])
    saved = client.get('/api/notes/' + note['id']).json()
    assert saved['group_id'] is None
    assert saved['body'] == '修改后的判断'
    assert saved['chart'] == payload['chart']
    assert saved['annotations'] == payload['annotations']
    client.delete('/api/notes/' + note['id'])
    assert client.get('/api/notes/' + note['id']).status_code == 404
    db.connection.close()


def test_notes_survive_reopen_and_reject_missing_group(tmp_path):
    path = tmp_path / 'persistent.duckdb'
    db = Database(path)
    app = FastAPI()
    register_notes(app, db)
    client = TestClient(app)
    assert client.post('/api/notes', json={'title': '测试', 'group_id': '00000000-0000-0000-0000-000000000001'}).status_code == 422
    note = client.post('/api/notes', json={'title': '重启后保留', 'body': '原始分析'}).json()
    db.connection.close()
    reopened = Database(path)
    app2 = FastAPI()
    register_notes(app2, reopened)
    assert TestClient(app2).get('/api/notes/' + note['id']).json()['body'] == '原始分析'
    reopened.connection.close()
