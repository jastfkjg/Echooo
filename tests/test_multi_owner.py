"""Provision real accounts and exercise workspace boundaries through HTTP/WS."""
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from echooo import database as db
from echooo.auth import Auth, AuthError, check_password
from echooo.voice_ownership import register_voice, visible_voices
from test_product import app, client, domain, memory, session


@pytest.fixture
def other(app):
    app.state.auth.create_owner('judge-demo', 'dedicated-demo-password')
    second = TestClient(app)
    try:
        assert second.post('/api/auth/login', json={
            'name': 'judge-demo', 'password': 'dedicated-demo-password'}).status_code == 200
        yield second
    finally:
        second.close()


def test_provision_is_atomic_and_preserves_existing_sessions(client, app):
    existing = client.get('/api/domains').json()
    token = client.cookies.get('echooo_owner')
    user = app.state.auth.create_owner('judge-demo', 'dedicated-demo-password')
    assert app.state.auth.resolve(token, 'owner')['name'] == 'owner'
    assert client.get('/api/domains').json() == existing
    with app.state.store.scope(user['id']) as r:
        assert [d['name'] for d in r.list(db.domains)] == ['default']
        assert r.list(db.memories) == []
    with pytest.raises(AuthError, match='already exists'):
        app.state.auth.create_owner('judge-demo', 'replacement-password')
    with app.state.store.engine.connect() as c:
        row = c.execute(select(db.users).where(db.users.c.id == user['id'])).mappings().one()
        assert check_password('dedicated-demo-password', row['password'])
        assert len(c.execute(select(db.users)).all()) == 2
        assert len(c.execute(select(db.tokens).where(db.tokens.c.owner_id == user['id'])).all()) == 0
    assert client.post('/api/auth/setup', json={
        'name': 'public-signup', 'password': 'password'}).status_code == 401


def test_knowledge_upload_chat_export_and_mutations_are_isolated(client, other):
    d = domain(client, 'Personal project')
    fact = memory(client, d['id'], 'Private fact', 'PERSONAL_PRIVATE_CONTENT', 'private')
    source = client.post(f"/api/domains/{d['id']}/upload", files={
        'file': ('private.txt', b'PERSONAL_UPLOADED_CONTENT', 'text/plain')}).json()
    chat = session(client, d['id'], [fact], mode='private')
    assert client.post(f"/api/sessions/{chat['id']}/messages", json={'content': 'PERSONAL_CHAT'}).status_code == 200
    assert [x['name'] for x in other.get('/api/domains').json()] == ['default']
    assert other.get('/api/sessions').json() == []
    assert 'PERSONAL_' not in other.get('/api/export').text
    requests = [
        ('get', f"/api/domains/{d['id']}/sources", {}),
        ('get', f"/api/memories/{fact['id']}/versions", {}),
        ('delete', f"/api/memories/{fact['id']}", {}),
        ('post', f"/api/sources/{source['id']}/extract", {}),
        ('delete', f"/api/sources/{source['id']}", {}),
        ('get', f"/api/sessions/{chat['id']}", {}),
        ('post', f"/api/sessions/{chat['id']}/messages", {'json': {'content': 'attack'}}),
        ('delete', f"/api/sessions/{chat['id']}", {}),
        ('delete', f"/api/domains/{d['id']}", {}),
    ]
    for method, url, kwargs in requests:
        assert getattr(other, method)(url, **kwargs).status_code == 404, url
    assert other.post(f"/api/domains/{d['id']}/upload", files={
        'file': ('foreign.txt', b'attack', 'text/plain')}).status_code == 404
    own = domain(other, 'Personal project')  # Same names are allowed in different workspaces.
    assert own['id'] != d['id']
    assert client.get(f"/api/domains/{own['id']}/memories").status_code == 404
    assert 'PERSONAL_CHAT' in client.get(f"/api/sessions/{chat['id']}").text
    with pytest.raises(WebSocketDisconnect):
        with other.websocket_connect(f"/ws/sessions/{chat['id']}") as ws:
            ws.receive_json()


def test_meetings_audio_and_live_connections_are_isolated(client, other):
    m = client.post('/api/meetings', json={'title': 'Personal meeting'}).json()
    path = f"/api/meetings/{m['id']}"
    with client.websocket_connect(f"/ws/meetings/{m['id']}") as ws:
        assert ws.receive_json()['type'] == 'warning'
        rid = ws.receive_json()['recording']['id']
        ws.send_bytes(b'\x01\x00' * 160)
        assert ws.receive_json()['type'] == 'saved'
        ws.send_text('stop')
        assert ws.receive_json()['type'] == 'stopped'
    audio = f'{path}/recordings/{rid}/audio'
    assert client.get(audio).status_code == 200
    assert other.get('/api/meetings').json() == []
    for url in [path, path + '/knowledge', path + '/debug', path + '/export', path + '/events', audio]:
        assert other.get(url).status_code == 404, url
    assert other.patch(path, json={'title': 'attack'}).status_code == 404
    assert other.delete(path).status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with other.websocket_connect(f"/ws/meetings/{m['id']}") as ws:
            ws.receive_json()
    assert client.get(audio).status_code == 200
    assert other.post('/api/meetings', json={'title': 'Demo meeting'}).status_code == 201
    assert len(client.get('/api/meetings').json()) == 1
    assert len(other.get('/api/meetings').json()) == 1


def test_logout_does_not_revoke_another_account(client, other):
    assert other.post('/api/auth/logout').status_code == 200
    assert other.get('/api/domains').status_code == 401
    assert client.get('/api/domains').status_code == 200


def test_legacy_and_new_custom_voice_ownership(client, other, app):
    primary = client.get('/api/auth').json()['user']['id']
    second = other.get('/api/auth').json()['user']['id']
    voices = [{'id': 'legacy', 'status': 'OK'}, {'id': 'demo', 'status': 'OK'}]
    register_voice(app.state.store, second, 'demo')
    assert visible_voices(app.state.store, primary, voices) == voices[:1]
    assert visible_voices(app.state.store, second, voices) == voices[1:]
    settings = app.state.service.ai.settings
    settings.tts_provider = 'dashscope'
    settings.dashscope_api_key = 'test-key'
    manager = AsyncMock()
    manager.list_voices.return_value = voices
    manager.cached_voices = voices
    manager.known_voice_ids = {'legacy', 'demo'}
    app.state.voice_manager = manager
    assert other.get('/api/tts/voices').json()['custom_voices'] == voices[1:]
    assert client.get('/api/tts/voices').json()['custom_voices'] == voices[:1]
    assert other.delete('/api/tts/voices/legacy').status_code == 404
    assert client.delete('/api/tts/voices/demo').status_code == 404
    manager.delete_voice.assert_not_awaited()
    assert 'legacy' not in other.get('/api/settings/assistant-voice').text
    assert other.put('/api/settings/assistant-voice', json={
        'provider': 'dashscope', 'voice': 'legacy'}).status_code == 422
    own_chat = other.post('/api/sessions/quick-chat').json()
    assert other.patch(f"/api/sessions/{own_chat['id']}/voice", json={
        'dashscope_voice': 'legacy'}).status_code == 422
    assert other.patch(f"/api/sessions/{own_chat['id']}/voice", json={
        'dashscope_voice': 'demo'}).status_code == 200
    for voice in ['legacy', ['invalid']]:
        assert other.post('/api/sessions', json={
            'title': 'Demo', 'mode': 'private', 'voice': {'dashscope_voice': voice}}).status_code == 422


def test_provision_command_keeps_first_only_default_and_hides_passwords(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location('create_owner',
        Path(__file__).resolve().parents[1] / 'deploy/cloud/create_owner.py')
    command = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(command)
    from echooo.config import Settings
    settings = Settings(database_url=f'sqlite:///{tmp_path}/accounts.db')
    monkeypatch.setattr(command.Settings, 'load', lambda: settings)
    monkeypatch.setattr('builtins.input', lambda _: 'first')
    monkeypatch.setattr(command, 'getpass', lambda _: 'interactive-password')
    command.main([])
    with pytest.raises(SystemExit, match='--additional'):
        command.main([])
    monkeypatch.setattr('builtins.input', lambda _: 'judge-demo')
    command.main(['--additional'])
    with pytest.raises(SystemExit, match='already exists'):
        command.main(['--additional'])
    store = db.Store(settings.database_url)
    try:
        auth = Auth(store)
        assert auth.login('first', 'interactive-password', 'first')[0]['name'] == 'first'
        assert auth.login('judge-demo', 'interactive-password', 'second')[0]['name'] == 'judge-demo'
    finally:
        store.close()
    assert 'interactive-password' not in capsys.readouterr().out


def test_failed_workspace_provision_rolls_back_account(client, app, monkeypatch):
    def fail(*args):
        raise RuntimeError('simulated domain provisioning failure')
    monkeypatch.setattr('echooo.auth.ensure_default_domain', fail)
    with pytest.raises(RuntimeError, match='provisioning failure'):
        app.state.auth.create_owner('failed-demo', 'dedicated-demo-password')
    with app.state.store.engine.connect() as c:
        assert c.execute(select(db.users).where(db.users.c.name == 'failed-demo')).first() is None
    assert client.get('/api/domains').status_code == 200


def test_additional_account_cannot_take_over_guest_conversation(client, other, app):
    d = domain(client, 'Delegation')
    chat = session(client, d['id'], [])
    assert other.post(f"/api/sessions/{chat['id']}/invite").status_code == 404
    token = client.post(f"/api/sessions/{chat['id']}/invite").json()['token']
    guest = TestClient(app)
    try:
        assert guest.post('/api/guest/join', json={'token': token}).status_code == 200
        own = other.post('/api/sessions/quick-chat').json()
        assert guest.get(f"/api/guest/sessions/{own['id']}").status_code == 403
        assert guest.get(f"/api/guest/sessions/{chat['id']}").status_code == 200
        assert guest.get('/api/export').status_code == 401
    finally:
        guest.close()
