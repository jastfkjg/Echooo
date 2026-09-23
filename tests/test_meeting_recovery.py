import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from echooo import database as db
from echooo.meeting_transcription import LiveTranscription, RecordingTranscriptions, missing_passages
from echooo.models import STTEvent, STTEventType
from test_product import app, client


def word(text, start, end):
    return {'text': text, 'start': start, 'end': end}


def test_backfill_keeps_corrected_speech_and_maps_only_supported_speakers():
    existing = [{'id': 'kept', 'content': 'Manually corrected.', 'speaker': 'Alice', 'start_ms': 0, 'end_ms': 1000}]
    result = {'text': 'Original later different', 'utterances': [
        {'speaker': 'A', 'words': [word('Original', 0, 800), word('later', 1200, 1800)]},
        {'speaker': 'B', 'words': [word('different', 2000, 2500)]}]}
    additions = missing_passages(result, existing, 2600, 'abcd1234')
    assert [u['content'] for u in additions] == ['later', 'different']
    assert additions[0]['speaker'] == 'Alice'
    assert additions[1]['speaker'].startswith('Recovered speaker B')
    assert existing[0]['content'] == 'Manually corrected.'
    assert missing_passages(result, existing + additions, 2600, 'abcd1234') == []
    assert missing_passages({'text': '', 'utterances': []}, [], 60000, 'r') == []
    with pytest.raises(ValueError):
        missing_passages({'text': 'Untimed text'}, [], 60000, 'r')


async def eventually(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(.005)
    raise AssertionError('Timed out waiting for condition')


@pytest.mark.asyncio
async def test_live_reconnect_offset_and_repeated_turn_order_are_session_local(monkeypatch):
    monkeypatch.setattr('echooo.meeting_transcription.RECONNECT_SECONDS', .001)
    states, events, providers = [], [], []
    class Provider:
        def __init__(self):
            self.queue = asyncio.Queue()
            providers.append(self)
        async def connect(self):
            pass
        async def send_audio(self, pcm):
            assert len(pcm) <= 3200
            await self.queue.put(STTEvent(type=STTEventType.FINAL, transcript='Test', raw={'turn_order': 1, 'words': [word('Test', 0, 80)]}))
        async def events(self):
            while True:
                yield await self.queue.get()
        async def finish(self):
            await self.queue.put(STTEvent(type=STTEventType.FINAL, transcript='Last phrase', raw={'turn_order': 2}))
            await self.queue.put(STTEvent(type=STTEventType.TERMINATED))
        async def close(self):
            pass
    async def event(event, offset, session):
        events.append((event, offset, session))
    async def state(phase, message):
        states.append(phase)
    live = LiveTranscription(Provider, 16000, event, state)
    live.start()
    live.feed(bytes(3200), 1600)
    await eventually(lambda: len(events) >= 1)
    await providers[0].queue.put(STTEvent(type=STTEventType.ERROR))
    await eventually(lambda: 'reconnecting' in states)
    # 22 minutes of saved audio elapsed, independently of the failed STT session.
    live.feed(bytes(3200), 22 * 60 * 16000)
    await eventually(lambda: len(providers) == 2 and len(events) >= 2)
    await live.finish()
    assert events[0][1:] == (0, 1)
    assert events[1][1:] == (1319900, 2)
    assert events[-1][0].transcript == 'Last phrase'
    assert states == ['live', 'reconnecting', 'live']
    assert live.repair_bounds() is not None


@pytest.mark.asyncio
async def test_silent_stream_close_reconnects_without_an_error_event(monkeypatch):
    monkeypatch.setattr('echooo.meeting_transcription.RECONNECT_SECONDS', .001)
    states = []
    class Provider:
        async def connect(self): pass
        async def send_audio(self, pcm): await asyncio.sleep(10)
        async def events(self):
            if False: yield
        async def close(self): pass
    async def event(*args): pass
    async def state(phase, message): states.append(phase)
    live = LiveTranscription(Provider, 16000, event, state)
    live.start();live.feed(bytes(3200), 1600)
    await eventually(lambda: 'reconnecting' in states)
    await live.finish()


def seed_recording(client, app, seconds=18*60):
    meeting = client.post('/api/meetings', json={'title': 'Recovery test'}).json()
    with app.state.store.scope(meeting['owner_id']) as r:
        rec = r.add(db.recordings, meeting_id=meeting['id'], sample_rate=16000, samples=seconds*16000)
        r.add(db.audio_parts, meeting_id=meeting['id'], recording_id=rec['id'], sequence=0, pcm=bytes(seconds*32000))
        u = r.add(db.utterances, meeting_id=meeting['id'], recording_id=rec['id'], speaker='Alice', content='A corrected opening.', start_ms=0, end_ms=1000)
    return meeting, rec, u


def wait_ready(client, path):
    for _ in range(200):
        result = client.get(path).json()
        phase = result['recordings'][0]['transcription']['phase']
        if phase in {'complete', 'error'}:
            return result
        time.sleep(.01)
    raise AssertionError('Verification did not finish')


def test_repair_scope_idempotency_preserves_audio_corrections_and_silence(client, app):
    m, rec, original = seed_recording(client, app)
    manager = app.state.meeting_transcriptions
    manager.settings.stt_provider = 'assemblyai';manager.settings.assemblyai_api_key = 'test-key'
    calls = []
    class Provider:
        async def submit(self, audio, **kwargs):
            assert audio[:4] == b'RIFF'
            calls.append('submit');return 'job-1'
        async def result(self, job):
            return {'status': 'completed', 'text': 'opening recovered', 'utterances': [
                {'speaker': 'A', 'words': [word('opening', 0, 800), word('recovered', 6*60000, 6*60000+1000)]}]}
        async def delete(self, job): calls.append('delete')
    manager.provider = Provider()
    path = '/api/meetings/'+m['id'];url = path+'/recordings/'+rec['id']+'/transcribe'
    other = client.post('/api/meetings', json={'title': 'Other'}).json()
    assert client.post('/api/meetings/'+other['id']+'/recordings/'+rec['id']+'/transcribe').status_code == 404
    assert TestClient(app).post(url).status_code == 401
    assert client.post(url,json={'mode':'full'}).status_code == 202
    result = wait_ready(client, path)
    assert result['recordings'][0]['transcription']['verified_samples'] == 18*60*16000
    assert [u['content'] for u in result['utterances']] == ['A corrected opening.', 'recovered']
    assert result['utterances'][0]['id'] == original['id']
    assert client.post(url).status_code == 202
    assert calls.count('submit') == 1
    # Full audio is processed despite the last 12 minutes having no returned speech.
    assert len(client.get(path+'/recordings/'+rec['id']+'/audio').content) == 18*60*32000+44
    for _ in range(100):
        result=client.get(path).json()
        if result['minutes'] and len(result['minutes'][-1]['evidence_ids'])==2: break
        time.sleep(.01)
    assert set(result['minutes'][-1]['evidence_ids']) == {u['id'] for u in result['utterances']}


def test_failed_poll_resumes_saved_provider_job_without_reupload(client, app):
    m, rec, original = seed_recording(client, app, seconds=2)
    manager=app.state.meeting_transcriptions
    manager.settings.stt_provider='assemblyai';manager.settings.assemblyai_api_key='test-key'
    calls=[]
    class Provider:
        async def submit(self, audio, **kwargs): calls.append('submit');return 'saved-job'
        async def result(self,job):
            calls.append(job)
            if calls.count('saved-job')==1: raise RuntimeError('Temporary failure')
            return {'status':'completed','text':'','utterances':[]}
        async def delete(self,job): pass
    manager.provider=Provider()
    path='/api/meetings/'+m['id'];url=path+'/recordings/'+rec['id']+'/transcribe'
    assert client.post(url,json={'mode':'full'}).status_code==202
    assert wait_ready(client,path)['recordings'][0]['transcription']['phase']=='error'
    assert client.post(url).status_code==202
    assert wait_ready(client,path)['recordings'][0]['transcription']['phase']=='complete'
    assert calls.count('submit')==1

@pytest.mark.asyncio
async def test_22_minute_audio_stream_and_final_tail_are_not_truncated():
    frames = 22 * 60 * 10
    received = 0
    class Provider:
        def __init__(self): self.queue=asyncio.Queue()
        async def connect(self): pass
        async def send_audio(self,pcm):
            nonlocal received
            assert 1600 <= len(pcm) <= 3200
            received += 1
        async def events(self):
            while True: yield await self.queue.get()
        async def finish(self): await self.queue.put(STTEvent(type=STTEventType.TERMINATED))
        async def close(self): pass
    async def event(*args): pass
    async def state(*args): pass
    live=LiveTranscription(Provider,16000,event,state);live.start()
    for start in range(0,frames,100):
        for i in range(start,start+100):live.feed(bytes(3200),(i+1)*1600)
        await eventually(lambda:received==start+100)
    live.feed(bytes(64),frames*1600+32)
    await live.finish()
    assert received==frames+1
    assert live.samples==22*60*16000+32
    assert live.session==1
    assert live.repair_bounds() is None


@pytest.mark.asyncio
async def test_batch_api_upload_contract_and_polling(monkeypatch):
    import httpx,json
    from echooo.config import Settings
    from echooo.meeting_transcription import BatchTranscriber
    requests=[]
    async def handler(request):
        requests.append(request)
        if request.url.path=='/v2/upload':
            assert len(await request.aread())==200000
            assert request.headers['Content-Length']=='200000'
            return httpx.Response(200,json={'upload_url':'https://example.test/audio'})
        if request.method=='POST':
            payload=json.loads(request.content)
            assert payload['speaker_labels'] and payload['language_detection']
            assert payload['speech_models']==['universal-3-pro','universal-2']
            return httpx.Response(200,json={'id':'job'})
        return httpx.Response(200,json={'status':'completed','text':'','words':[]})
    provider=BatchTranscriber(Settings(assemblyai_api_key='test'))
    provider.client=lambda:httpx.AsyncClient(base_url='https://example.test',transport=httpx.MockTransport(handler))
    assert await provider.submit(bytes(200000))=='job'
    assert (await provider.result('job'))['status']=='completed'
    await provider.delete('job')
    assert [r.method for r in requests]==['POST','POST','GET','DELETE']

@pytest.mark.asyncio
async def test_shutdown_and_startup_resume_the_submitted_job(client, app):
    from collections import defaultdict
    m,rec,_=seed_recording(client,app,seconds=2)
    manager=app.state.meeting_transcriptions
    manager.settings.stt_provider='assemblyai';manager.settings.assemblyai_api_key='test-key'
    submitted=[];polling=asyncio.Event()
    class Provider:
        async def submit(self, audio, **kwargs): submitted.append(1);return 'durable-job'
        async def result(self,job):
            assert job=='durable-job'
            await polling.wait()
            return {'status':'completed','text':'','utterances':[]}
        async def delete(self,job): pass
    provider=Provider();manager.provider=provider
    manager.start(m['owner_id'],m['id'],rec['id'])
    await eventually(lambda:bool(manager.state(m['owner_id'],m['id'],rec['id']).get('job_id')))
    await manager.close()
    replacement=RecordingTranscriptions(app.state.store,manager.settings,defaultdict(asyncio.Lock))
    replacement.provider=provider;polling.set();replacement.resume()
    await replacement.tasks[rec['id']]
    assert submitted==[1]
    assert replacement.state(m['owner_id'],m['id'],rec['id'])['phase']=='complete'


def test_provider_completion_with_short_audio_coverage_is_not_marked_verified(client, app):
    m,rec,_=seed_recording(client,app,seconds=20)
    manager=app.state.meeting_transcriptions
    manager.settings.stt_provider='assemblyai';manager.settings.assemblyai_api_key='test-key'
    class Provider:
        async def submit(self, audio, **kwargs): return 'short-job'
        async def result(self,job): return {'status':'completed','audio_duration':5,'text':'','utterances':[]}
    manager.provider=Provider()
    path='/api/meetings/'+m['id']
    client.post(path+'/recordings/'+rec['id']+'/transcribe',json={'mode':'full'})
    result=wait_ready(client,path)
    assert result['recordings'][0]['transcription']['phase']=='error'
    assert result['recordings'][0]['transcription']['verified_samples']==0
    assert len(result['utterances'])==1


@pytest.mark.asyncio
async def test_summary_retry_does_not_retranscribe_completed_audio(client, app):
    m,rec,_=seed_recording(client,app,seconds=2)
    manager=app.state.meeting_transcriptions
    manager.settings.stt_provider='assemblyai';manager.settings.assemblyai_api_key='test-key'
    manager.state(m['owner_id'],m['id'],rec['id'],phase='complete',verified_samples=32000,summary_phase='error')
    calls=[]
    async def summarize(who,mid,rid): calls.append(rid)
    manager.on_complete=summarize
    manager.start(m['owner_id'],m['id'],rec['id'],retry=True)
    await manager.tasks[rec['id']]
    state=manager.state(m['owner_id'],m['id'],rec['id'])
    assert calls==[rec['id']]
    assert state['phase']==state['summary_phase']=='complete'


@pytest.mark.asyncio
async def test_healthy_finish_and_interrupted_restart_do_not_submit_audio(client, app):
    m, rec, _ = seed_recording(client, app, seconds=2)
    manager = app.state.meeting_transcriptions
    manager.settings.stt_provider = 'assemblyai'
    manager.settings.assemblyai_api_key = 'test'
    class Provider:
        async def submit(self, *args, **kwargs):
            pytest.fail('Healthy or interrupted recordings must not auto-submit')
    manager.provider = Provider()
    live = LiveTranscription(None, 16000, None, None)
    live.samples = 32000
    live.terminated = True
    await manager.finish_recording(m['owner_id'], m['id'], rec['id'], live)
    assert manager.state(m['owner_id'], m['id'], rec['id'])['phase'] == 'live_ready'
    await manager.tasks[rec['id']]
    manager.state(m['owner_id'], m['id'], rec['id'], phase='live')
    manager.resume()
    assert manager.state(m['owner_id'], m['id'], rec['id'])['phase'] == 'interrupted'
    assert not manager.tasks
    path = '/api/meetings/' + m['id']
    assert client.get(path).status_code == 200
    assert client.post(path + '/recordings/' + rec['id'] + '/transcribe').status_code == 409


@pytest.mark.asyncio
async def test_gap_repair_sends_window_and_restores_absolute_timestamps(client, app):
    import io, wave
    m, rec, original = seed_recording(client, app, seconds=60)
    manager = app.state.meeting_transcriptions
    manager.settings.stt_provider = 'assemblyai'
    manager.settings.assemblyai_api_key = 'test'
    class Provider:
        async def submit(self, audio, **kwargs):
            with wave.open(io.BytesIO(audio)) as wav:
                assert wav.getnframes() == 20 * 16000  # 20–30 s gap plus 5 s context each side.
            return 'window-job'
        async def result(self, job):
            return {'status': 'completed', 'audio_duration': 20, 'utterances': [
                {'speaker': 'A', 'words': [word('Recovered.', 6000, 7000)]}]}
        async def delete(self, job): pass
    manager.provider = Provider()
    live = LiveTranscription(None, 16000, None, None)
    live.samples, live.gap_start, live.gap_end = 60*16000, 20*16000, 30*16000
    await manager.finish_recording(m['owner_id'], m['id'], rec['id'], live)
    await manager.tasks[rec['id']]
    state = manager.state(m['owner_id'], m['id'], rec['id'])
    assert state['phase'] == 'complete' and state['mode'] == 'repair'
    assert state['verified_samples'] == 0  # Never claim full-recording verification.
    with app.state.store.scope(m['owner_id']) as r:
        utterances = r.list(db.utterances, db.utterances.c.recording_id == rec['id'])
    assert [(u['content'], u['start_ms']) for u in utterances] == [('A corrected opening.', 0), ('Recovered.', 21000)]


@pytest.mark.asyncio
async def test_uncertain_submission_is_not_repeated_on_retry_or_restart(client, app):
    import httpx
    from echooo.meeting_transcription import BatchTranscriber
    m, rec, _ = seed_recording(client, app, seconds=2)
    manager = app.state.meeting_transcriptions
    manager.settings.stt_provider = 'assemblyai'
    manager.settings.assemblyai_api_key = 'test'
    calls = []
    async def handler(request):
        calls.append(request.url.path)
        if request.url.path == '/v2/upload':
            return httpx.Response(200, json={'upload_url': 'https://private.test/audio'})
        raise httpx.ReadTimeout('lost response', request=request)
    provider = BatchTranscriber(manager.settings)
    provider.client = lambda: httpx.AsyncClient(base_url='https://example.test', transport=httpx.MockTransport(handler))
    manager.provider = provider
    manager.start(m['owner_id'], m['id'], rec['id'], full=True)
    await manager.tasks[rec['id']]
    state = manager.state(m['owner_id'], m['id'], rec['id'])
    assert state['submission_uncertain'] and state['error_stage'] == 'submitting'
    manager.start(m['owner_id'], m['id'], rec['id'], retry=True)
    manager.resume()
    assert calls == ['/v2/upload', '/v2/transcript']
    assert not manager.tasks
    public = client.get('/api/meetings/' + m['id']).json()['recordings'][0]['transcription']
    assert 'upload_url' not in public
    await app.state.meeting_findings.before_record(m['owner_id'], m['id'])


@pytest.mark.asyncio
async def test_upload_checkpoint_skips_duplicate_upload():
    import httpx, json
    from echooo.config import Settings
    from echooo.meeting_transcription import BatchTranscriber
    calls, checkpoints = [], []
    async def handler(request):
        calls.append(request.url.path)
        assert json.loads(request.content)['audio_url'] == 'https://private.test/saved'
        return httpx.Response(200, json={'id': 'existing-upload-job'})
    provider = BatchTranscriber(Settings(assemblyai_api_key='test'))
    provider.client = lambda: httpx.AsyncClient(base_url='https://example.test', transport=httpx.MockTransport(handler))
    await provider.submit(b'audio', upload_url='https://private.test/saved', checkpoint=lambda **state: checkpoints.append(state))
    assert calls == ['/v2/transcript']
    assert checkpoints == [{'stage': 'submitting', 'submission_uncertain': True}]
