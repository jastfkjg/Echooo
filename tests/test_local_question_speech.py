import time

import pytest

from echooo import database as db
from echooo.meeting_interventions import Review, BrowserSpeech
from echooo.meeting_speech import speech_transcript
from test_meeting_interventions import governed, propose, agent, app, client


@pytest.fixture(autouse=True)
def speech_provider(monkeypatch):
    from echooo.models import AudioChunk
    class TTS:
        async def stream_audio(self, text, *, cancel):
            yield AudioChunk(b'\x01\x00' * 2400, 24000)
    monkeypatch.setattr('echooo.assistant_voice.factory', lambda *args: TTS())


async def local(governed):
    a, m = governed
    a.manager.update(a.row, desired_state='left', state='ended')
    with a.store.scope(a.who) as r:
        rec = r.add(db.recordings, meeting_id=a.mid, sample_rate=16000, samples=16000)
    a.manager.captures.add(a.mid)
    p = await propose(governed)
    result = await m.review(a.who, a.mid, p['id'], Review(action='approve', revision=1,
        question='Who owns the launch checklist?', delivery='browser', recording_id=rec['id']))
    receipt = result['browser_speech']
    async def send(action, **kwargs):
        return await m.browser_speech(a.who,a.mid,p['id'],BrowserSpeech(action=action,
            revision=receipt['revision'],token=kwargs.get('token',receipt['token'])))
    return a,m,p,rec,receipt,send


async def test_local_approved_wording_once_and_completed_projection(governed):
    a,m,p,rec,receipt,send = await local(governed)
    assert a.queue.empty()
    assert receipt['token'] not in str(m.view(a.who,a.mid))
    calls=m.ai.calls
    assert (await send('start'))['question']=='Who owns the launch checklist?'
    assert m.ai.calls==calls  # No second semantic verdict for unchanged approved input.
    with pytest.raises(Exception,match='already started'):
        await send('start')
    assert (await send('heartbeat'))['status']=='speaking'
    await send('spoken')
    with a.store.scope(a.who) as r:
        entries = speech_transcript(r,a.mid,[rec])
        assert entries[0]['content']=='Who owns the launch checklist?'
        assert entries[0]['recording_id']==rec['id']
        assert len(r.list(db.utterances))==2
    with pytest.raises(Exception,match='no longer valid'):
        await send('start')


async def test_browser_receipt_required_and_relevance_rechecked(governed):
    a,m,p,rec,receipt,send = await local(governed)
    with pytest.raises(Exception,match='no longer valid'):
        await send('start',token='wrong')
    m.ai.relevant=False
    with a.store.scope(a.who) as r:
        r.add(db.utterances,meeting_id=a.mid,recording_id=None,speaker='Bob',content='Alice owns the checklist now.',start_ms=5000,end_ms=6000)
    with pytest.raises(Exception,match='no longer relevant'):
        await send('start')
    assert m.view(a.who,a.mid)['interventions'][0]['status']=='failed'


async def test_local_playback_rechecks_expired_semantic_receipt(governed):
    a,m,p,rec,receipt,send = await local(governed)
    with a.store.scope(a.who) as r:
        saved = r.get(db.meeting_interventions, p['id'])
        r.change(db.meeting_interventions, p['id'], state={**saved['state'],
            'approved_checked_at': time.time() - m.approval_check_ttl - 1})
    calls = m.ai.calls
    await send('start')
    assert m.ai.calls == calls + 1


@pytest.mark.parametrize('content', [
    'Who owns the launch checklist?',
    'You asked who owns the launch checklist. I will own it.',
    'That question is incorrect; we already assigned the checklist.',
])
async def test_human_speech_during_playback_is_preserved_not_text_deduplicated(governed, content):
    a,m,p,rec,receipt,send = await local(governed)
    await send('start')
    with a.store.scope(a.who) as r:
        human = r.add(db.utterances, meeting_id=a.mid, recording_id=rec['id'],
            speaker='Participant', content=content, start_ms=1000, end_ms=2000)
    with pytest.raises(Exception, match='discussion changed'):
        await send('heartbeat')
    await send('cancelled')
    with a.store.scope(a.who) as r:
        assert r.get(db.utterances,human['id'])['content'] == content
        assert r.get(db.utterances,human['id'])['speaker'] == 'Participant'
        assert r.list(db.meeting_agent_events)[0]['status'] == 'interrupted'


@pytest.mark.parametrize('action',['failed','cancelled'])
async def test_local_failed_or_cancelled_never_completed(governed,action):
    a,m,p,rec,receipt,send = await local(governed)
    await send('start')
    await send(action)
    with a.store.scope(a.who) as r:
        assert speech_transcript(r,a.mid,[rec])==[]
    with pytest.raises(Exception):
        await send('spoken')


async def test_local_context_changes_or_stopped_capture_block_completion(governed):
    a,m,p,rec,receipt,send = await local(governed)
    await send('start')
    with a.store.scope(a.who) as r:
        r.change(db.utterances,p['evidence'][0]['utterance_id'],content='The checklist is already assigned.')
    with pytest.raises(Exception,match='discussion changed'):
        await send('heartbeat')
    a.manager.captures.discard(a.mid)
    with pytest.raises(Exception,match='Start recording'):
        await send('spoken')
    await send('cancelled')


async def test_browser_lease_expiry_and_restart_never_replay(governed):
    a,m,p,rec,receipt,send = await local(governed)
    await send('start')
    with a.store.scope(a.who) as r:
        current=r.get(db.meeting_interventions,p['id'])
        r.change(db.meeting_interventions,p['id'],state={**current['state'],'expires_at':time.time()-1})
    assert m.view(a.who,a.mid)['interventions'][0]['status']=='cancelled'
    with pytest.raises(Exception):
        await send('spoken')
    with a.store.scope(a.who) as r:
        assert r.list(db.meeting_agent_events)[0]['status']=='interrupted'


async def test_browser_does_not_bypass_online_meeting_controls(governed):
    a,m=governed
    p=await propose(governed)
    with pytest.raises(Exception,match='leave the online meeting'):
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1,delivery='browser',recording_id='anything'))


async def test_browser_endpoint_requires_owner(governed,client):
    from fastapi.testclient import TestClient
    a,m,p,rec,receipt,send=await local(governed)
    outsider=TestClient(client.app)
    path=f'/api/meetings/{a.mid}/interventions/{p["id"]}/browser-speech'
    data={'action':'start','revision':receipt['revision'],'token':receipt['token']}
    assert outsider.post(path,json=data).status_code==401
    assert client.post(path,json=data).status_code==200
