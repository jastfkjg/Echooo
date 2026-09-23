"""Browser direct replies: evidence, ownership, one-shot delivery and continuous capture."""
import asyncio
import time

import pytest

from echooo import database as db
from echooo.meeting_browser_answers import BrowserMeetingAnswers, history
from echooo.meeting_live import TranscriptWriter
from echooo.meeting_speech import speech_transcript
from echooo.models import STTEvent, STTEventType
from test_product import app, client


@pytest.fixture(autouse=True)
def capture_speech_provider(monkeypatch):
    from echooo.models import AudioChunk
    class TTS:
        async def stream_audio(self, text, *, cancel):
            yield AudioChunk(b'\x01\x00' * 2400, 24000)
    monkeypatch.setattr('echooo.meeting_browser_answers.assistant_tts', lambda *args: TTS())


@pytest.fixture
async def browser(client, app):
    m = client.post('/api/meetings', json={'title': 'Browser questions'}).json()
    manager = app.state.meeting_bots
    with manager.store.scope(m['owner_id']) as r:
        rec = r.add(db.recordings, meeting_id=m['id'], sample_rate=16000, samples=160000)
    packets = []
    async def send(packet):
        packets.append(packet)
    def validate():
        with manager.store.scope(m['owner_id']) as r:
            assert r.get(db.meetings, m['id'])['status'] == 'active'
    b = BrowserMeetingAnswers(manager, m['owner_id'], m['id'], rec['id'], send, validate)
    from echooo.models import AudioChunk
    class TTS:
        async def stream_audio(self, text, *, cancel):
            yield AudioChunk(b'\x01\x00' * 2400, 24000)
    b.tts_factory = TTS
    b.packets = packets
    b.writer = TranscriptWriter(b.store, b.who, b.mid, b.recording_id, manager.transcriptions.feed)
    await b.control({'type': 'direct_config', 'enabled': True})
    try:
        yield b
    finally:
        await b.close()


async def final(b, text='Hello, Echooo.', start=1000, end=2000):
    event = STTEvent(STTEventType.FINAL, text, raw={'turn_order': len(b.writer.seen),
        'words': [{'text': text, 'start': start, 'end': end}]})
    rows = b.writer.consume(event, 0, 'session', max(10000, end))
    await b.transcript(event, rows)
    return rows[0]


async def wait_for(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.005)


async def offer(b):
    await wait_for(lambda: any(p['type'] == 'direct_offer' for p in b.packets))
    return [p for p in b.packets if p['type'] == 'direct_offer'][-1]


async def receipt(b, action, **overrides):
    packet = {**await offer(b), 'type': 'direct_speech', 'action': action,
        'request_id': str(time.monotonic_ns()), **overrides}
    await b.control(packet)
    return next(p for p in reversed(b.packets) if p.get('request_id') == packet['request_id'])


def events(b):
    return history(b.manager, b.who, b.mid)


async def test_direct_final_answers_without_attendee_and_completion_is_durable(browser, client):
    b = browser
    await b.transcript(STTEvent(STTEventType.PARTIAL, 'Hello, Echooo.'), [])
    assert not events(b)
    u = await final(b)
    await offer(b)
    assert (await receipt(b, 'spoken'))['ok'] is False  # No completion before start.
    ack = await receipt(b, 'start')
    assert ack['ok'] and 'local demo reply' in ack['question']
    assert (await receipt(b, 'spoken'))['ok']
    await b.task
    assert events(b)[0]['status'] == 'spoken'
    with b.store.scope(b.who) as r:
        assert r.get(db.utterances, u['id'])['content'] == 'Hello, Echooo.'
        assert not r.list(db.meeting_bots) and not r.list(db.meeting_agent_settings)
        assert len(speech_transcript(r, b.mid, r.list(db.recordings))) == 1
    exported = client.get(f'/api/meetings/{b.mid}/export').json()
    assert exported['browser_answers'][0]['response'] == ack['question']
    assert exported['assistant_utterances'][0]['content'] == ack['question']
    assert 'token' not in str(exported)
    assert (await receipt(b, 'start'))['ok'] is False


async def test_shared_recent_then_history_search_and_support_audit(browser):
    b = browser
    b.settings.llm_provider = 'openai_compatible'
    source = await final(b, 'We decided to use Telegram.')
    for i in range(65):
        await final(b, f'Unrelated discussion {i}.')
    calls = []
    async def model(system, context, **kwargs):
        calls.append(context)
        if 'retrieval' not in context:
            assert source['id'] not in {sid for b in context['discussion'] for t in b['turns'] for sid in t['source_ids']}
            return {'action': 'search', 'queries': ['Telegram decision']}
        assert source['id'] in {sid for b in context['retrieval']['passages'] for t in b['turns'] for sid in t['source_ids']}
        return {'action': 'answer', 'support': 'supported', 'reply': 'Telegram.', 'citations': [source['id']]}
    b.intelligence.json_call = model
    await final(b, 'Echooo, which communication platform was selected?')
    await offer(b)
    assert len(calls) == 2
    await receipt(b, 'start')
    await receipt(b, 'spoken')
    await b.task
    e = events(b)[0]
    assert e['answer_check']['search_used'] and e['answer_check']['support'] == 'supported'
    assert e['citations'][0]['id'] == source['id']


async def test_bad_tokens_duplicate_start_and_foreign_events_cannot_play(browser):
    await final(browser)
    assert not (await receipt(browser, 'start', token='other-session'))['ok']
    assert not (await receipt(browser, 'start', id='other-event'))['ok']
    assert (await receipt(browser, 'start'))['ok']
    assert not (await receipt(browser, 'start'))['ok']


async def test_untimed_and_old_audio_do_not_interrupt_and_manual_stop_still_works(browser):
    b = browser
    await final(b)
    await receipt(b, 'start')
    # Untimed partials and pre-playback audio cannot establish a new interruption.
    for text in ['Hello, I am your meeting assistant.', 'Echooo, repeat that.', 'Wait, I have another question.']:
        await b.transcript(STTEvent(STTEventType.PARTIAL, text), [])
        await final(b, text, start=9500, end=10000)
        assert events(b)[0]['status'] == 'speaking'
        assert len(events(b)) == 1
    assert not any(p['type'] == 'direct_cancel' for p in b.packets)
    await b.control({'type': 'direct_stop'})
    assert events(b)[0]['status'] == 'interrupted'
    assert (await receipt(b, 'cancelled'))['ok']
    delayed = await final(b, 'Echooo, repeat that.', start=9500, end=10500)
    assert len(events(b)) == 1
    with b.store.scope(b.who) as r:
        assert r.get(db.utterances, delayed['id'])['content'] == 'Echooo, repeat that.'
    # A genuinely later question is eligible again; no blacklist of echoed words.
    await final(b, 'Echooo, repeat that.', start=14000, end=15000)
    assert len(events(b)) == 2


async def test_echoed_reply_can_finish_without_starting_another_answer(browser):
    b = browser
    await final(b)
    ack = await receipt(b, 'start')
    await b.transcript(STTEvent(STTEventType.PARTIAL, ack['question']), [])
    echoed = await final(b, ack['question'], start=10000, end=10500)
    assert events(b)[0]['status'] == 'speaking'
    assert not any(p['type'] == 'direct_cancel' for p in b.packets)
    assert (await receipt(b, 'spoken'))['ok']
    await b.task
    assert len(events(b)) == 1 and events(b)[0]['status'] == 'spoken'
    with b.store.scope(b.who) as r:
        assert r.get(db.utterances, echoed['id'])['content'] == ack['question']


async def test_stale_answer_rejected_before_browser_playback(browser):
    b = browser
    b.settings.llm_provider = 'openai_compatible'
    async def model(*args, **kwargs):
        return {'action': 'clarify', 'reply': 'Which project?', 'citations': []}
    b.intelligence.json_call = model
    await final(b)
    await offer(b)
    await final(b, 'The project has changed.')
    assert not (await receipt(b, 'start'))['ok']
    with b.store.scope(b.who) as r:
        assert not r.list(db.meeting_speech)


async def test_stop_and_disconnect_cancel_generation_without_replay(browser):
    b = browser
    b.settings.llm_provider = 'openai_compatible'
    entered = asyncio.Event()
    async def model(*args, **kwargs):
        entered.set()
        await asyncio.sleep(30)
    b.intelligence.json_call = model
    await final(b)
    await entered.wait()
    await b.control({'type': 'direct_stop'})
    assert events(b)[0]['status'] == 'interrupted'
    assert events(b)[0]['answer_check']['failure'] == 'cancelled'
    assert not any(p['type'] == 'direct_offer' for p in b.packets)
    await b.close()
    packets = []
    async def send(p):
        packets.append(p)
    fresh = BrowserMeetingAnswers(b.manager, b.who, b.mid, b.recording_id, send, b.validate)
    try:
        assert fresh.task is None and fresh.receipt is None and not packets
    finally:
        await fresh.close()


@pytest.mark.parametrize('action', ['failed', 'cancelled'])
async def test_failed_or_cancelled_playback_never_becomes_spoken(browser, action):
    await final(browser)
    await receipt(browser, 'start')
    await receipt(browser, action)
    if browser.task:
        await browser.task
    assert events(browser)[0]['status'] in {'error', 'interrupted'}
    with browser.store.scope(browser.who) as r:
        assert not speech_transcript(r, browser.mid, r.list(db.recordings))


async def test_missing_heartbeats_expire_and_cannot_be_replayed(browser):
    await final(browser)
    await receipt(browser, 'start')
    browser.receipt['expires'] = time.monotonic() - 1
    await wait_for(lambda: events(browser)[0]['status'] == 'interrupted')
    assert not (await receipt(browser, 'spoken'))['ok']


async def test_approved_local_questions_share_echo_guard_and_cancel_direct_reply(browser):
    b = browser
    await final(b)
    await offer(b)
    await b.control({'type': 'local_speech_guard', 'active': True, 'request_id': 'guard'})
    assert events(b)[0]['status'] == 'interrupted'
    await final(b, 'Echooo, what is missing?', start=10000, end=11000)
    assert len(events(b)) == 1
    await b.control({'type': 'local_speech_guard', 'active': False, 'request_id': 'guard-end'})
    await final(b, 'Echooo, what is missing?', start=14000, end=15000)
    assert len(events(b)) == 2


async def test_disabled_answers_still_save_transcript(browser):
    await browser.control({'type': 'direct_config', 'enabled': False})
    u = await final(browser)
    assert not events(browser)
    with browser.store.scope(browser.who) as r:
        assert r.get(db.utterances, u['id'])


async def test_stop_rejects_late_final_from_audio_captured_before_the_click(browser):
    await browser.control({'type': 'direct_stop'})
    await final(browser)
    assert not events(browser)
    await final(browser, start=14000, end=15000)
    assert len(events(browser)) == 1


def test_capture_control_does_not_drop_pcm(client):
    m = client.post('/api/meetings', json={'title': 'Continuous audio'}).json()
    pcm = b'\x01\x00' * 1600
    with client.websocket_connect('/ws/meetings/' + m['id']) as ws:
        assert ws.receive_json()['type'] == 'warning'
        rec = ws.receive_json()['recording']
        ws.send_json({'type': 'direct_config', 'enabled': True})
        ws.send_json({'type': 'local_speech_guard', 'active': True, 'request_id': 'start'})
        assert ws.receive_json()['ok']
        ws.send_bytes(pcm)
        assert ws.receive_json() == {'type': 'saved', 'samples': 1600}
        ws.send_json({'type': 'direct_stop'})
        ws.send_bytes(pcm)
        assert ws.receive_json() == {'type': 'saved', 'samples': 3200}
        ws.send_text('stop')
        assert ws.receive_json()['type'] == 'stopped'
    audio = client.get(f"/api/meetings/{m['id']}/recordings/{rec['id']}/audio")
    assert audio.content[44:] == pcm * 2


def test_capture_routes_live_finals_to_answers_and_keeps_interruption_audio(client, app, monkeypatch):
    import echooo.meetings as routes
    class Live:
        def __init__(self, factory, rate, consume, state):
            self.consume, self.count, self.tasks = consume, 0, []
        def start(self):
            pass
        def feed(self, pcm, samples):
            self.count += 1
            text = 'Hello, Echooo.' if self.count == 1 else 'Echooo, wait.'
            event = STTEvent(STTEventType.FINAL, text, raw={'turn_order': self.count,
                'words': [{'text': text, 'start': (self.count - 1) * 100, 'end': self.count * 100}]})
            self.tasks.append(asyncio.create_task(self.consume(event, 0, 'live')))
        async def finish(self):
            await asyncio.gather(*self.tasks)
    monkeypatch.setattr(routes, 'LiveTranscription', Live)
    monkeypatch.setattr(app.state.meeting_bots.settings, 'stt_provider', 'assemblyai')
    monkeypatch.setattr(app.state.meeting_transcriptions, 'start', lambda *args: None)
    m = client.post('/api/meetings', json={'title': 'Live socket'}).json()
    pcm = b'\x02\x00' * 1600
    def until(ws, kind):
        for _ in range(40):
            p = ws.receive_json()
            if p['type'] == kind:
                return p
        pytest.fail('Missing socket event ' + kind)
    with client.websocket_connect('/ws/meetings/' + m['id']) as ws:
        rec = until(ws, 'ready')['recording']
        ws.send_json({'type': 'direct_config', 'enabled': True})
        ws.send_bytes(pcm)
        token = until(ws, 'direct_offer')
        ws.send_json({**token, 'type': 'direct_speech', 'action': 'start', 'request_id': 'start'})
        assert until(ws, 'direct_ack')['ok']
        ws.send_bytes(pcm)
        assert until(ws, 'utterance')['utterance']['content'] == 'Echooo, wait.'
        assert until(ws, 'direct_cancel')['id'] == token['id']
        ws.send_text('stop')
        until(ws, 'stopped')
    result = client.get('/api/meetings/' + m['id']).json()
    assert [u['content'] for u in result['utterances']] == ['Hello, Echooo.', 'Echooo, wait.']
    assert len(result['browser_answers']) == 1 and result['browser_answers'][0]['status'] == 'interrupted'
    assert result['assistant_utterances'] == []
    audio = client.get(f"/api/meetings/{m['id']}/recordings/{rec['id']}/audio")
    assert audio.content[44:] == pcm * 2


async def test_stop_before_generation_task_runs_persists_interrupted(browser):
    await final(browser)
    await browser.stop()
    assert events(browser)[0]['status'] == 'interrupted'


async def test_recording_deletion_removes_browser_answer_and_speech_history(browser, client):
    b = browser
    await final(b)
    await receipt(b, 'start')
    await receipt(b, 'spoken')
    await b.task
    await b.close()
    result = client.delete(f'/api/meetings/{b.mid}/recordings/{b.recording_id}')
    assert result.status_code == 200
    assert result.json()['browser_answers'] == result.json()['assistant_utterances'] == []
    with b.store.scope(b.who) as r:
        assert not r.list(db.meeting_speech) and not r.list(db.meeting_agent_events)


def partial(text, start=11000, end=11400):
    return STTEvent(STTEventType.PARTIAL, text, raw={'words': [{'text': text, 'start': start, 'end': end}]})


async def test_brief_interruption_pauses_then_resumes_same_reply(browser):
    b = browser
    await final(b)
    await receipt(b, 'start')
    await b.transcript(partial('A different thought'), [])
    assert b.phase == 'paused'
    await wait_for(lambda: any(p.get('action') == 'pause' for p in b.packets))
    await b.barge_task
    assert b.phase == 'speaking'
    assert b.packets[-1]['action'] == 'resume'
    assert events(b)[0]['status'] == 'speaking'


async def test_sustained_interruption_stops_then_final_is_semantically_routed(browser):
    b = browser
    await final(b)
    await receipt(b, 'start')
    await b.transcript(partial('Can you explain'), [])
    await asyncio.sleep(.32)
    await b.transcript(partial('Can you explain the reasoning', end=11800), [])
    await b.barge_task
    assert events(b)[0]['status'] == 'interrupted'
    assert b.conversation_active()
    contexts = []
    async def classify(system, context, **kwargs):
        contexts.append(context)
        return {'action': 'respond'}
    b.intelligence.json_call = classify
    await final(b, 'Can you explain the reasoning?', start=11000, end=12000)
    await wait_for(lambda: len(events(b)) == 2)
    assert contexts and events(b)[1]['request'] == 'Can you explain the reasoning?'


@pytest.mark.parametrize('action,expected', [('respond', 2), ('listen', 1), ('end', 1)])
async def test_followup_uses_shared_turn_model_and_public_context(browser, action, expected):
    b = browser
    await final(b)
    await receipt(b, 'start')
    await receipt(b, 'spoken')
    await b.task
    async def model(system, context, **kwargs):
        from echooo.meeting_agent import TURN_SYSTEM
        assert system == TURN_SYSTEM
        assert context['recent_questions'][-1]['reply']
        assert context['audience'] == 'voice'
        return {'action': action}
    b.intelligence.json_call = model
    await final(b, 'Could you expand on that?', start=14000, end=15000)
    task = b.decision_task
    assert task is not None
    await task
    assert len(events(b)) == expected
    if action == 'end':
        assert not b.conversation_active()


async def test_expired_followup_and_stop_cancel_late_classifier(browser):
    b = browser
    await final(b)
    await receipt(b, 'start')
    await receipt(b, 'spoken')
    await b.task
    b.conversation_until = time.monotonic() - 1
    await final(b, 'Could you expand on that?', start=14000, end=15000)
    assert b.decision_task is None
    b.conversation_until = time.monotonic() + 15
    entered = asyncio.Event()
    async def slow(*args, **kwargs):
        entered.set()
        await asyncio.sleep(30)
        return {'action': 'respond'}
    b.intelligence.json_call = slow
    await final(b, 'Could you expand on that?', start=16000, end=17000)
    await entered.wait()
    task = b.decision_task
    await b.control({'type': 'direct_stop'})
    await task
    assert len(events(b)) == 1 and not b.conversation_active()


async def test_delayed_echo_with_audio_timestamp_remains_filtered_after_wall_clock_tail(browser):
    b = browser
    await final(b)
    ack = await receipt(b, 'start')
    await receipt(b, 'spoken')
    await b.task
    b.echo_until = 0
    await final(b, ack['question'], start=10000, end=11000)
    assert len(events(b)) == 1 and b.decision_task is None


async def test_owner_correction_is_marked_for_transcript_display_after_reload(browser, client):
    b = browser
    original = await final(b, 'This is a participant statement, not an assistant command.')
    base = f'/api/meetings/{b.mid}'
    assert not next(u for u in client.get(base).json()['utterances'] if u['id'] == original['id'])['user_edited']
    response = client.patch(base + '/utterances/' + original['id'], json={
        'speaker': 'Alice', 'content': original['content']})
    assert response.status_code == 200
    restored = next(u for u in client.get(base).json()['utterances'] if u['id'] == original['id'])
    assert restored['user_edited'] and restored['speaker'] == 'Alice'
    assert restored['content'] == original['content']


async def test_server_tts_audio_is_private_to_start_receipt(browser):
    import base64
    b = browser
    await final(b)
    packet = await offer(b)
    assert 'audio' not in packet
    started = await receipt(b, 'start')
    assert base64.b64decode(started['audio']).startswith(b'RIFF')
    assert 'audio' not in str(events(b))
    heartbeat = await receipt(b, 'heartbeat')
    assert 'audio' not in heartbeat
    await receipt(b, 'spoken')
    await b.task


async def test_server_tts_failure_keeps_answer_text_and_never_offers_playback(browser):
    b = browser
    class Broken:
        async def stream_audio(self, text, *, cancel):
            raise RuntimeError('PRIVATE_PROVIDER_ERROR')
            yield
    b.tts_factory = Broken
    await final(b)
    await b.task
    event = events(b)[0]
    assert event['response'] and event['status'] == 'error'
    assert 'Speech generation failed' in event['error']
    assert 'PRIVATE_PROVIDER_ERROR' not in str(b.packets)
    assert not any(p['type'] == 'direct_offer' for p in b.packets)


async def test_stop_during_server_synthesis_never_offers_audio(browser):
    b = browser
    entered = asyncio.Event()
    class Slow:
        async def stream_audio(self, text, *, cancel):
            entered.set()
            await asyncio.sleep(10)
            yield
    b.tts_factory = Slow
    await final(b)
    await asyncio.wait_for(entered.wait(), 1)
    await b.stop()
    assert not any(p['type'] == 'direct_offer' for p in b.packets)
    assert events(b)[0]['status'] == 'interrupted'
