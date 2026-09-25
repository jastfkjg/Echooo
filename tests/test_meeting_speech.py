from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import update

from echooo import database as db
from echooo.meeting_speech import mark_speech
from echooo.models import AudioChunk
from test_meeting_agent import app, client, agent, Socket


def recording(agent, *, created_at=100, samples=16000 * 120):
    with agent.store.scope(agent.who) as r:
        rec = r.add(db.recordings, meeting_id=agent.mid, sample_rate=16000,
            samples=samples, created_at=created_at)
        r.c.execute(update(db.recordings).where(db.recordings.c.id == rec['id']).values(created_at=created_at))
        return {**rec, 'created_at': created_at}


def reply(agent, rid, key='one', **extra):
    with agent.store.scope(agent.who) as r:
        event = r.add(db.meeting_agent_events, meeting_id=agent.mid, connection_id=agent.cid,
            source_key=f'voice:{rid}:1:{key}', audience='voice', sender='', request='What is our repo?',
            response='The repo is https://github.com/example/assembly.', status='spoken', error='',
            created_at=110, **extra)
        r.c.execute(update(db.meeting_agent_events).where(db.meeting_agent_events.c.id == event['id']).values(created_at=110))
        return {**event, 'created_at': 110}


async def test_completed_speech_has_durable_sample_clock_anchor_without_human_evidence(agent, client):
    rec = recording(agent, samples=16000 * 12)
    agent.recording_id = rec['id']
    agent.settings = replace(agent.settings, tts_provider='dashscope')
    class TTS:
        async def stream_audio(self, text, *, cancel):
            yield AudioChunk(b'\x01\x00' * 7200, 24000)
    agent.tts_factory = TTS
    agent.manager.sockets[agent.cid] = Socket(agent)
    await agent.accept(f'voice:{rec["id"]}:1:1', 'Echooo, what is our repo?', 'voice', '')
    event = agent.queue.get_nowait()
    await agent.answer(event)
    base = '/api/meetings/' + agent.mid
    detail = client.get(base).json()
    speech = detail['assistant_utterances'][0]
    assert speech['speaker'] == 'Echooo AI' and speech['assistant']
    assert speech['content'] == event['response'] and speech['recording_id'] == rec['id']
    assert not speech['has_sources']
    assert speech['start_ms'] == 12000 and not speech['timing_estimated']
    assert detail['utterances'] == []  # No generated evidence for memories or human minutes.
    assert client.get(base + '/export').json()['assistant_utterances'] == [speech]
    with agent.store.scope(agent.who) as r:
        assert len(r.list(db.meeting_speech)) == 1
    agent.manager.sockets.pop(agent.cid)


def test_historical_speech_is_available_beyond_activity_limit_and_estimates_time(agent, client, app):
    rec = recording(agent)
    for n in range(25):
        event = reply(agent, rec['id'], str(n))
        if n == 0:
            sourced_event_id = event['id']
            with agent.store.scope(agent.who) as r:
                r.add(db.meeting_answer_sources, meeting_id=agent.mid, event_id=event['id'],
                    scope={}, citations=[{'kind': 'utterance', 'id': 'historical-source'}])
    base = '/api/meetings/' + agent.mid
    detail = client.get(base).json()
    assert len(detail['assistant_utterances']) == 25
    assert len({u['id'] for u in detail['assistant_utterances']}) == 25
    assert {u['event_id'] for u in detail['assistant_utterances'] if u['has_sources']} == {sourced_event_id}
    assert all(u['timing_estimated'] and u['start_ms'] == 10000 for u in detail['assistant_utterances'])
    agent.manager.update(agent.row, state='ended', desired_state='left')
    assert len(client.get(base).json()['assistant_utterances']) == 25
    assert TestClient(app).get(base).status_code == 401
    assert client.delete(base + '/recordings/' + rec['id']).status_code == 200
    assert client.get(base).json()['assistant_utterances'] == []


def test_private_unplayed_failed_and_interrupted_responses_never_become_completed_transcript(agent, client):
    rec = recording(agent)
    for index, status in enumerate(['thinking', 'speaking', 'interrupted', 'error', 'uncertain', 'skipped']):
        event = reply(agent, rec['id'], str(index))
        agent.change(event, status=status)
    event = reply(agent, rec['id'], 'private')
    agent.change(event, audience='private', status='submitted')
    event = reply(agent, rec['id'], 'chat')
    agent.change(event, audience='public', status='submitted')
    assert client.get('/api/meetings/' + agent.mid).json()['assistant_utterances'] == []


def test_recording_deletion_does_not_resurrect_anchored_speech_as_notes(agent, client):
    rec = recording(agent)
    agent.recording_id = rec['id']
    event = reply(agent, rec['id'])
    mark_speech(agent, event)
    mark_speech(agent, event, complete=True)
    base = '/api/meetings/' + agent.mid
    assert len(client.get(base).json()['assistant_utterances']) == 1
    agent.manager.update(agent.row, state='ended', desired_state='left')
    assert client.delete(base + '/recordings/' + rec['id']).status_code == 200
    assert client.get(base).json()['assistant_utterances'] == []
