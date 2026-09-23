import asyncio
import base64
import io
import time
import wave

import pytest
from fastapi.testclient import TestClient

from echooo import assistant_voice as voices, database as db
from echooo.app import create_app
from echooo.config import Settings
from echooo.models import AudioChunk


@pytest.fixture
def configured(tmp_path, monkeypatch):
    settings = Settings(database_url=f'sqlite:///{tmp_path}/voice.db', stt_provider='mock',
        llm_provider='mock', tts_provider='cosyvoice', assistant_tts_providers='cosyvoice,dashscope',
        dashscope_api_key='test-only', dashscope_tts_voice='longanyang', dashscope_tts_model='cosyvoice-v2')
    made = []
    class TTS:
        def __init__(self, config):
            self.provider = config.tts_provider
            made.append(self)
        def configure_voice(self, profile):
            self.voice = profile.speaker_id
        async def stream_audio(self, text, *, cancel):
            self.text = text
            yield AudioChunk(b'\x01\x00' * 100, 24000)
    monkeypatch.setattr(voices, 'create_tts', TTS)
    app = create_app(settings)
    with TestClient(app) as client:
        user = client.post('/api/auth/setup', json={'name': 'owner', 'password': 'test-password-123'}).json()['user']
        yield client, app, settings, user['id'], made


def test_preferences_persist_and_both_transports_use_next_reply_settings(configured):
    client, app, settings, who, made = configured
    url = '/api/settings/assistant-voice'
    data = client.get(url).json()
    assert [s['id'] for s in data['services']] == ['cosyvoice', 'dashscope']
    old = voices.factory(app.state.store, who, settings)
    voice = data['services'][1]['voices'][0]['id']
    selected = {'provider': 'dashscope', 'voice': voice}
    assert client.put(url, json=selected).status_code == 200
    # Both meeting implementations resolve this shared factory once per reply.
    new = voices.factory(app.state.store, who, settings)
    assert old.provider == 'cosyvoice' and old.voice == settings.cosyvoice_speaker_id
    assert new.provider == 'dashscope' and new.voice == voice
    reopened = db.Store(settings.database_url)
    try:
        assert voices.preferences(reopened, who, settings) == selected
        assert voices.preferences(reopened, 'another-owner', settings)['provider'] == 'cosyvoice'
    finally:
        reopened.close()
    assert client.put(url, json={'provider': 'browser', 'voice': 'anything'}).status_code == 422
    assert client.put(url, json={'provider': 'dashscope', 'voice': 'invented'}).status_code == 422
    assert voices.preferences(app.state.store, who, settings) == selected


def test_preview_uses_unsaved_selection_without_changing_preference(configured):
    client, app, settings, who, made = configured
    selected = {'provider': 'cosyvoice', 'voice': settings.cosyvoice_speaker_id}
    result = client.post('/api/settings/assistant-voice/preview', json=selected)
    assert result.status_code == 200
    with wave.open(io.BytesIO(base64.b64decode(result.json()['audio']))) as wav:
        assert wav.getframerate() == 24000 and wav.getnframes() == 100
    assert made[-1].voice == selected['voice']
    with app.state.store.scope(who) as r:
        assert not r.list(db.assistant_voice_settings)
    client.post('/api/auth/logout')
    assert client.get('/api/settings/assistant-voice').status_code == 401
    assert client.put('/api/settings/assistant-voice', json=selected).status_code == 401
    assert client.post('/api/settings/assistant-voice/preview', json=selected).status_code == 401


async def test_failed_and_cancelled_synthesis_never_returns_fallback_audio():
    class Empty:
        async def stream_audio(self, text, *, cancel):
            if False:
                yield
    with pytest.raises(ValueError, match='no valid audio'):
        await voices.synthesize(Empty(), 'hello')
    class Cancellable:
        async def stream_audio(self, text, *, cancel):
            yield AudioChunk(b'\0\0', 24000)
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await voices.synthesize(Cancellable(), 'hello', cancel)
