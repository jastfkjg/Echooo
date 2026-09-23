"""Independent participant lifecycle, transport identity and durable audio."""
import base64
import logging
import time
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from echooo import database as db
from echooo.app import create_app
from echooo.config import Settings
from echooo.meeting_bots import meeting_platform, BotRecording, MediaTokenFilter, MeetingBots
from test_product import client


class Connector:
    def __init__(self):
        self.payloads = []
        self.result = {'id': 'bot_Test123', 'state': 'joining'}
        self.create_error = None
        self.leave_error = None
        self.leaves = 0
        self.lookups = []
        self.chats = []

    async def chat_messages(self, *_):
        return []

    async def send_chat(self, provider_id, text, recipient=None):
        self.chats.append((text, recipient))
        return {}

    async def create(self, payload):
        self.payloads.append(payload)
        if self.create_error:
            raise self.create_error
        return self.result

    async def get(self, _):
        return self.result

    async def find(self, key):
        self.lookups.append(key)
        return self.result

    async def leave(self, _):
        self.leaves += 1
        if self.leave_error:
            raise self.leave_error
        self.result = {**self.result, 'state': 'leaving'}
        return self.result


@pytest.fixture
def app(tmp_path):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/test.db', stt_provider='mock',
        llm_provider='mock', tts_provider='browser', attendee_base_url='http://connector/api/v1',
        attendee_api_key='private-key', attendee_callback_url='wss://echooo-gateway:8443'))
    app.state.meeting_bots.client = Connector()
    return app


def meeting(client):
    result = client.post('/api/meetings', json={'title': 'Independent participant'})
    assert result.status_code == 201
    return '/api/meetings/' + result.json()['id']


def invite(client, base, url='https://meet.google.com/abc-defg-hij'):
    return client.post(base + '/bot', json={'meeting_url': url, 'bot_name': 'Echooo'})


def reconcile(client, app):
    manager = app.state.meeting_bots
    client.portal.call(manager.reconcile, manager.rows()[0])


@pytest.mark.parametrize('url,platform', [
    ('https://meet.google.com/abc-defg-hij', 'google_meet'),
    ('https://us02web.zoom.us/j/123456789?pwd=secret', 'zoom'),
    ('https://teams.microsoft.com/l/meetup-join/19%3Ameeting?context=x', 'teams'),
    ('https://teams.live.com/meet/123456789?p=x', 'teams'),
])
def test_supported_links(url, platform):
    assert meeting_platform(url) == platform


@pytest.mark.parametrize('url', ['http://meet.google.com/abc-defg-hij',
    'https://meet.google.com.evil.test/abc-defg-hij', 'https://user:pass@zoom.us/j/123',
    'https://127.0.0.1/j/123', 'https://zoom.us:8443/j/123', 'https://zoom.us/settings',
    'https://meet.google.com/abc-\ndefg-hij', 'https://zoom.us/j/123#fragment'])
def test_reject_non_meeting_targets(url):
    with pytest.raises(ValueError):
        meeting_platform(url)


def test_join_is_owned_durable_single_and_silent(client, app):
    base = meeting(client)
    result = invite(client, base)
    assert result.status_code == 202
    assert result.json()['bot']['state'] == 'joining'
    assert result.json()['bot']['bot_name'] == 'Echooo · AI'
    connector = app.state.meeting_bots.client
    payload = connector.payloads[0]
    assert payload['recording_settings'] == {'format': 'none', 'record_participant_speech_start_stop_events': True}
    assert payload['transcription_settings'] == {'meeting_closed_captions': {}}
    assert payload['websocket_settings']['audio']['sample_rate'] == 16000
    assert 'token=' in payload['websocket_settings']['audio']['url']
    assert 'private-key' not in result.text and 'callback_hash' not in result.text
    assert invite(client, base).status_code == 409
    assert invite(client, meeting(client)).status_code == 409
    assert len(connector.payloads) == 1
    assert client.post(base + '/end').status_code == 409
    assert client.delete(base).status_code == 409
    anonymous = TestClient(app)
    assert anonymous.get(base + '/bot').status_code == 401


def test_zoom_uses_web_captions_without_second_stt_provider(client, app):
    assert invite(client, meeting(client), 'https://zoom.us/j/123456789').status_code == 202
    assert app.state.meeting_bots.client.payloads[0]['zoom_settings'] == {'sdk': 'web'}


def test_uncertain_create_recovers_without_another_participant(client, app):
    base = meeting(client)
    connector = app.state.meeting_bots.client
    connector.create_error = httpx.ReadTimeout('response lost')
    assert invite(client, base).json()['bot']['state'] == 'unknown'
    assert invite(client, base).status_code == 409
    reconcile(client, app)
    assert client.get(base + '/bot').json()['bot']['state'] == 'joining'
    assert connector.lookups == [connector.payloads[0]['deduplication_key']]
    assert len(connector.payloads) == 1


def test_connection_failure_allows_safe_retry(client, app):
    base = meeting(client)
    connector = app.state.meeting_bots.client
    connector.create_error = httpx.ConnectError('offline')
    assert invite(client, base).json()['bot']['state'] == 'not_created'
    connector.create_error = None
    assert invite(client, base).json()['bot']['state'] == 'joining'


@pytest.mark.parametrize('status,detail,expected', [
    (400, {'error': 'Zoom App credentials are required to create a Zoom bot. Please add Zoom credentials at https://private.test'}, 'Zoom App credentials are missing'),
    (401, {'error': 'secret diagnostic'}, 'could not authenticate to Attendee'),
    (400, {'meeting_url': ['private meeting link']}, 'did not accept this meeting link'),
    (400, {'error': 'secret diagnostic'}, 'Attendee rejected the join request'),
])
def test_rejection_explains_setup_without_exposing_raw_provider_details(client, app, status, detail, expected):
    base = meeting(client)
    response = httpx.Response(status, json=detail, request=httpx.Request('POST', 'http://connector/api/v1/bots'))
    app.state.meeting_bots.client.create_error = httpx.HTTPStatusError('rejected', request=response.request, response=response)
    result = invite(client, base, 'https://zoom.us/j/123456789').json()['bot']
    assert result['state'] == 'not_created'
    assert expected in result['error']
    assert 'private.test' not in result['error'] and 'secret diagnostic' not in result['error']


def test_leave_failure_revokes_audio_but_never_claims_bot_left(client, app):
    base = meeting(client)
    invite(client, base)
    connector = app.state.meeting_bots.client
    connector.leave_error = httpx.ReadTimeout('offline')
    result = client.post(base + '/bot/leave').json()
    assert result['bot']['desired_state'] == 'left'
    assert result['bot']['state'] == 'joining'
    assert result['bot']['error']
    assert client.post(base + '/end').status_code == 409
    path = urlsplit(connector.payloads[0]['websocket_settings']['audio']['url'])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path.path + '?' + path.query):
            pass
    connector.leave_error = None
    connector.result['state'] = 'ended'
    reconcile(client, app)
    assert client.post(base + '/end').status_code == 200


def wait_saved(client, base, count, samples):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        detail = client.get(base).json()
        if len(detail['recordings']) == count and detail['recordings'][-1]['samples'] == samples:
            return detail
        time.sleep(.01)
    pytest.fail('Audio was not persisted')


def test_authenticated_audio_survives_callback_disconnect(client, app):
    base = meeting(client)
    invite(client, base)
    url = urlsplit(app.state.meeting_bots.client.payloads[0]['websocket_settings']['audio']['url'])
    path = url.path + '?' + url.query
    pcm = b'\x01\x00' * 1600
    frame = {'trigger': 'realtime_audio.mixed', 'bot_id': 'bot_Test123',
        'data': {'sample_rate': 16000, 'chunk': base64.b64encode(pcm).decode(), 'timestamp_ms': 123456}}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url.path + '?token=incorrect'):
            pass
    for count in (1, 2):
        with client.websocket_connect(path) as ws:
            ws.send_json(frame)
            detail = wait_saved(client, base, count, 1600)
            assert detail['connector']['audio_connected'] is True
            assert client.post(base + '/end').status_code == 409
        deadline = time.monotonic() + 3
        while client.get(base + '/bot').json()['audio_connected'] and time.monotonic() < deadline:
            time.sleep(.01)
    assert len(client.get(base).json()['recordings']) == 2
    rid = detail['recordings'][-1]['id']
    audio = client.get(base + '/recordings/' + rid + '/audio')
    assert audio.status_code == 200 and audio.content.endswith(pcm)
    assert client.get(base + '/bot').json()['bot']['state'] == 'joining'


def test_stream_cannot_impersonate_another_bot(client, app):
    base = meeting(client)
    invite(client, base)
    url = urlsplit(app.state.meeting_bots.client.payloads[0]['websocket_settings']['audio']['url'])
    with client.websocket_connect(url.path + '?' + url.query) as ws:
        ws.send_json({'trigger': 'realtime_audio.mixed', 'bot_id': 'bot_Wrong',
            'data': {'sample_rate': 16000, 'chunk': 'AAAA'}})
        assert ws.receive()['type'] == 'websocket.close'
    assert client.get(base).json()['recordings'] == []


def test_tiny_audio_frames_are_coalesced_without_inventing_samples(client, app):
    base = meeting(client)
    invite(client, base)
    manager = app.state.meeting_bots
    sink = BotRecording(manager, manager.rows()[0])
    class Live:
        def repair_bounds(self): return None
        def __init__(self):
            self.frames = []
        def feed(self, pcm, samples):
            self.frames.append((pcm, samples))
        async def finish(self):
            pass
    sink.live = Live()
    pcm = b'\x01\x02' * 147  # Observed Attendee chunks are about 9 ms.
    for _ in range(11):
        sink.feed(pcm)
    assert [(len(p), n) for p, n in sink.live.frames] == [(3200, 1600)]
    client.portal.call(sink.finish)
    assert [(len(p), n) for p, n in sink.live.frames] == [(3200, 1600), (34, 1617)]
    assert b''.join(p for p, _ in sink.live.frames) == pcm * 11
    assert client.get(base).json()['recordings'][0]['samples'] == 1617


def test_callback_bearer_is_redacted_from_uvicorn_access_log():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0,
        '%s - "WebSocket %s" [accepted]', ('client', '/ws/meeting-bots/id?token=secret-token'), None)
    MediaTokenFilter().filter(record)
    assert 'secret-token' not in record.getMessage()
    assert '/ws/meeting-bots/id?[redacted]' in record.getMessage()


def test_connector_stt_uses_stream_rate_independently_of_browser_settings(client, app, monkeypatch):
    base = meeting(client)
    invite(client, base)
    manager = app.state.meeting_bots
    manager.settings.stt_provider = 'assemblyai'
    manager.settings.assemblyai_sample_rate = 48000
    observed = []
    monkeypatch.setattr('echooo.meeting_bots.create_stt', lambda settings: observed.append(settings.assemblyai_sample_rate))
    sink = client.portal.call(lambda: BotRecording(manager, manager.rows()[0]))
    sink.live.factory()
    assert observed == [16000]
    assert manager.settings.assemblyai_sample_rate == 48000
    client.portal.call(sink.finish)


def test_restart_reads_existing_participant_and_deadline_requests_leave(client, app):
    base = meeting(client)
    invite(client, base)
    previous = app.state.meeting_bots
    resumed = MeetingBots(previous.store, previous.settings, previous.transcriptions, previous.captures)
    resumed.client = previous.client
    row = resumed.rows()[0]
    resumed.update(row, deadline=time.time() - 1)
    client.portal.call(resumed.reconcile, row)
    assert resumed.client.leaves == 1
    assert len(resumed.client.payloads) == 1
    assert resumed.row(row['owner_id'], row['meeting_id'])['desired_state'] == 'left'


def test_status_and_leave_cannot_cross_owner_boundary(client, app):
    from sqlalchemy import insert
    from echooo.auth import hash_password
    base = meeting(client)
    invite(client, base)
    who = db.uid()
    with app.state.store.engine.begin() as c:
        c.execute(insert(db.users).values(id=who, name='second', password=hash_password('second-password-123'), created_at=time.time()))
    other = TestClient(app)
    other.cookies.set('echooo_owner', app.state.auth.issue(who, 'owner', 600))
    assert other.get(base + '/bot').status_code == 404
    assert other.post(base + '/bot/leave').status_code == 404
    assert invite(other, base).status_code == 404
    assert app.state.meeting_bots.client.leaves == 0
