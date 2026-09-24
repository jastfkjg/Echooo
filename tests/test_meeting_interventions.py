import asyncio
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from echooo import database as db
from echooo.auth import hash_password
from echooo.meeting_findings import clean_decisions
from echooo.meeting_interventions import Review, purge_interventions
from echooo.models import AudioChunk
from test_meeting_agent import agent, app, client, Socket


class IssueModel:
    relevant = True
    resolved = []
    invalid = False
    calls = 0

    async def json_call(self, prompt, data, fast=False):
        self.calls += 1
        if 'question' in data:
            return {'relevant': self.relevant}
        return {'proposals': [{'kind': 'missing_detail', 'question': 'Who will own the launch checklist?',
            'reason': 'The checklist is required before launch and has no assigned owner.',
            'evidence': [{'utterance_id': data['records'][0]['id'],
                'quote': 'invented' if self.invalid else data['records'][0]['content']}]}], 'resolved_ids': self.resolved}


async def test_same_question_with_different_evidence_subset_is_not_inserted(governed):
    a,m=governed
    await m.detect(a.who,a.mid)
    class Expanded(IssueModel):
        async def json_call(self,prompt,data,fast=False):
            result=await super().json_call(prompt,data,fast)
            result['proposals'][0]['evidence'].append({'utterance_id':data['records'][1]['id'],'quote':data['records'][1]['content']})
            result['proposals'].append(dict(result['proposals'][0]))
            return result
    m.ai=Expanded()
    await m.detect(a.who,a.mid)
    assert len(m.snapshot(a.who,a.mid)[2])==1


def test_internal_handles_are_removed_only_from_display_prose():
    from echooo.meeting_interventions import display_text
    token='speech-'+'a'*32
    assert display_text(f'First date ({token}). Later date ({token}-123456789abc).')=='First date. Later date.'


async def test_legacy_duplicates_hide_without_deleting_audit_or_resurfacing_after_dismiss(governed):
    a,m=governed
    p=await propose(governed)
    with a.store.scope(a.who) as r:
        r.add(db.meeting_interventions,**{k:p[k] for k in ('meeting_id','kind','question','reason','evidence','status','revision','state')})
    assert len(m.snapshot(a.who,a.mid)[2])==2
    assert len(m.view(a.who,a.mid)['interventions'])==1
    await m.review(a.who,a.mid,p['id'],Review(action='reject',revision=1))
    assert [x['status'] for x in m.view(a.who,a.mid)['interventions']]==['rejected']
    assert len(m.snapshot(a.who,a.mid)[2])==2


async def test_inconsistent_relevance_fails_visibly_without_archiving(governed):
    a,m=governed
    p=await propose(governed)
    class Inconsistent:
        async def json_call(self,*args,**kwargs):
            return {'relevant':False,'reason_code':'unresolved'}
    m.ai=Inconsistent()
    with pytest.raises(Exception,match='inconsistent result'):
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    view=m.view(a.who,a.mid)
    assert view['interventions'][0]['status']=='proposed'
    assert view['intervention_progress']['last_check']['outcome']=='invalid_relevance'


async def test_incremental_detection_and_audit(governed, client):
    a, m = governed
    await m.detect(a.who, a.mid, incremental=True)
    await m.detect(a.who, a.mid, incremental=True)
    assert m.ai.calls == 1
    checks = client.get(f'/api/meetings/{a.mid}/interventions/checks')
    assert checks.status_code == 200
    assert m.view(a.who, a.mid)['intervention_progress']['last_check']['outcome'] == 'suggested'
    await m.detect(a.who, a.mid)
    assert m.view(a.who, a.mid)['intervention_progress']['last_check']['outcome'] == 'duplicate'


async def test_followup_waits_for_new_evidence(governed):
    a, m = governed
    class Uncertain:
        calls = 0
        inputs = []
        async def json_call(self, prompt, data, fast=False):
            self.calls += 1
            self.inputs.append(data)
            return {'proposals':[], 'needs_followup':True}
    m.ai = Uncertain()
    await m.detect(a.who, a.mid, incremental=True)
    await m.detect(a.who, a.mid, incremental=True)
    assert m.ai.calls == 1
    assert (a.who, a.mid) in m.awaiting_evidence
    with a.store.scope(a.who) as r:
        r.add(db.utterances, meeting_id=a.mid, recording_id=None, speaker='Bob',
              content='Alice will take responsibility.', start_ms=3000, end_ms=4000)
    await m.detect(a.who, a.mid, incremental=True)
    assert m.ai.calls == 2
    assert m.ai.inputs[-1]['awaiting_clarification'] is True


class ObservingModel:
    def __init__(self):
        self.inputs = []

    async def json_call(self, prompt, data, fast=False):
        self.inputs.append(data)
        return {'proposals': [], 'needs_followup': True}


def add_discussion(a, index):
    with a.store.scope(a.who) as r:
        return r.add(db.utterances, meeting_id=a.mid, recording_id=None, speaker='Bob',
                     content=f'Discussion continues on item {index}.',
                     start_ms=3000 + index * 1000, end_ms=4000 + index * 1000)


async def wait_until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.005)


async def test_automatic_batches_coalesce_continuous_speech_without_starvation(governed):
    a, m = governed
    now = [0.0]
    m.clock, m.delay, m.ai = lambda: now[0], .001, ObservingModel()
    key = a.who, a.mid
    m.notify(*key)
    try:
        await wait_until(lambda: m.phases.get(key) == 'scheduled')
        task = m.tasks[key]
        for second in range(1, 30):
            now[0] = second
            add_discussion(a, second)
            m.notify(*key)
            assert m.tasks[key] is task
            await asyncio.sleep(.002)
        assert not m.ai.inputs
        now[0] = 30
        await wait_until(lambda: key not in m.tasks)
        assert len(m.ai.inputs) == 1
        assert len(m.ai.inputs[0]['new_record_ids']) == 31
        now[0] = 100
        await asyncio.sleep(.01)
        assert len(m.ai.inputs) == 1  # Waiting for clarification does not poll the model.
    finally:
        await m.close()


async def test_automatic_cooldown_batches_new_and_corrected_speech(governed):
    a, m = governed
    now = [0.0]
    m.clock, m.quiet_seconds, m.ai = lambda: now[0], 0, ObservingModel()
    await m.detect(a.who, a.mid, incremental=True, scheduled=True)
    revised = add_discussion(a, 1)
    for second in (1, 5, 19):
        now[0] = second
        with a.store.scope(a.who) as r:
            r.change(db.utterances, revised['id'], content=f'Corrected discussion version {second}.')
        assert await m.detect(a.who, a.mid, incremental=True, scheduled=True) == 'scheduled'
    now[0] = 20
    await m.detect(a.who, a.mid, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 2
    assert len(m.ai.inputs[-1]['new_record_ids']) == 1
    assert m.ai.inputs[-1]['records'][-1]['content'] == 'Corrected discussion version 19.'


async def test_append_rechecks_share_budget_and_defer_unchecked_drafts(governed):
    a, m = governed
    now = [0.0]
    m.clock, m.quiet_seconds = lambda: now[0], 0
    class Appending(IssueModel):
        async def json_call(self, prompt, data, fast=False):
            if 'candidates' in data:
                self.calls += 1
                return {'keep_ids': ['0']}
            result = await super().json_call(prompt, data, fast=fast)
            add_discussion(a, self.calls)
            return result
    m.ai = Appending()
    await m.detect(a.who, a.mid, incremental=True, scheduled=True)
    assert m.ai.calls == 2  # Generation plus append-only relevance check.
    checked = dict(m.checked_units[a.who, a.mid])
    now[0] = 20
    assert await m.detect(a.who, a.mid, incremental=True, scheduled=True) == 'scheduled'
    assert m.ai.calls == 3
    assert m.checked_units[a.who, a.mid] == checked
    assert m.view(a.who, a.mid)['intervention_progress']['last_check']['outcome'] == 'budget_deferred'
    now[0] = 40
    assert await m.detect(a.who, a.mid, incremental=True, scheduled=True) == 'scheduled'
    assert m.ai.calls == 3
    now[0] = 60
    await m.detect(a.who, a.mid, incremental=True, scheduled=True)
    assert m.ai.calls == 5
    assert len(m.background_calls[a.who, a.mid]) == 3


async def test_manual_check_bypasses_background_budget(governed):
    a, m = governed
    m.clock, m.quiet_seconds, m.ai = lambda: 0, 0, ObservingModel()
    key = a.who, a.mid
    m.background_calls[key].extend([0, 0, 0])
    assert await m.detect(*key, incremental=True, scheduled=True) == 'scheduled'
    m.force.add(key)
    await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 1
    assert key not in m.force
    assert len(m.background_calls[key]) == 3


async def test_failed_automatic_calls_still_consume_budget(governed):
    a, m = governed
    now = [0.0]
    m.clock, m.quiet_seconds = lambda: now[0], 0
    async def fail(*args, **kwargs):
        raise TimeoutError()
    m.ai.json_call = fail
    for second in (0, 20, 40):
        now[0] = second
        with pytest.raises(TimeoutError):
            await m.detect(a.who, a.mid, incremental=True, scheduled=True)
    now[0] = 59
    assert await m.detect(a.who, a.mid, incremental=True, scheduled=True) == 'scheduled'
    assert len(m.background_calls[a.who, a.mid]) == 3
    assert m.view(a.who, a.mid)['intervention_progress']['last_check']['model_calls'] == 1


async def test_inflight_check_coalesces_manual_requests_and_new_speech(governed, client):
    a, m = governed
    entered, release = asyncio.Event(), asyncio.Event()
    class Slow(ObservingModel):
        async def json_call(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return await super().json_call(*args, **kwargs)
    now = [0.0]
    m.clock, m.delay, m.quiet_seconds, m.ai = lambda: now[0], .001, 0, Slow()
    key = a.who, a.mid
    m.notify(*key)
    try:
        await entered.wait()
        for _ in range(3):
            assert client.post(f'/api/meetings/{a.mid}/interventions/check').status_code == 202
        assert key not in m.force
        add_discussion(a, 1)
        m.notify(*key)
        release.set()
        await wait_until(lambda: m.phases.get(key) == 'scheduled')
        assert len(m.ai.inputs) == 1
        now[0] = 20
        await wait_until(lambda: key not in m.tasks)
        assert len(m.ai.inputs) == 2
        assert len(m.ai.inputs[-1]['new_record_ids']) == 1
    finally:
        release.set()
        await m.close()


@pytest.mark.parametrize('keep', [True, False])
async def test_append_only_rechecks_instead_of_discarding(governed, keep):
    a, m = governed
    class Append(IssueModel):
        async def json_call(self, prompt, data, fast=False):
            if 'candidates' in data:
                return {'keep_ids':['0'] if keep else []}
            result = await super().json_call(prompt, data, fast=fast)
            with a.store.scope(a.who) as r:
                r.add(db.utterances, meeting_id=a.mid, recording_id=None, speaker='Bob',
                      content='We are still discussing release readiness.', start_ms=5000, end_ms=6000)
            return result
    m.ai = Append()
    await m.detect(a.who, a.mid)
    assert bool(m.view(a.who, a.mid)['interventions']) is keep


def test_stable_input_wait_is_bounded(governed):
    from echooo.meeting_findings import source_hash
    a, m = governed
    raw = dict(id='fragment', recording_id='r', speaker='Alice', content='We plan to',
               start_ms=0, end_ms=100, created_at=time.time())
    key = a.who, a.mid, raw['id']
    m.changed_at[key] = (source_hash(raw), time.time())
    units, waiting, _ = m.stable_context(a.who, a.mid, [raw], [])
    assert not units and waiting
    m.changed_at[key] = (source_hash(raw), time.time()-4)
    units, waiting, _ = m.stable_context(a.who, a.mid, [raw], [])
    assert not units and not waiting
    raw['content'] += ' release.'
    m.changed_at[key] = (source_hash(raw), time.time())
    assert not m.stable_context(a.who, a.mid, [raw], [])[0]
    m.changed_at[key] = (source_hash(raw), time.time()-2)
    assert len(m.stable_context(a.who, a.mid, [raw], [])[0]) == 1


@pytest.fixture
def governed(agent):
    m = agent.manager.interventions
    m.ai = IssueModel()
    m.enabled = True
    # Speech is mocked, but approval still requires a configured server provider.
    # Keep this independent of developer credentials and provider overrides.
    agent.settings = replace(agent.settings, tts_provider='dashscope', stt_provider='assemblyai',
        assistant_tts_providers='dashscope', dashscope_api_key='test-key', assemblyai_api_key='test-key')
    with agent.store.scope(agent.who) as r:
        for i, text in enumerate(['We need the launch checklist completed before release. No one owns it yet.',
                                  'Let us move on to the support plan.']):
            r.add(db.utterances, meeting_id=agent.mid, recording_id=None, speaker='Alice', content=text,
                start_ms=i*1000, end_ms=(i+1)*1000)
    return agent, m


async def propose(governed):
    a, m = governed
    await m.detect(a.who, a.mid)
    return m.view(a.who, a.mid)['interventions'][0]


async def test_private_detection_dedup_review_audit_and_exact_speech(governed, client):
    a, m = governed
    p = await propose(governed)
    assert a.queue.empty() and p['status'] == 'proposed'
    assert client.get('/api/meetings/'+a.mid).json()['approved_record']['unresolved_questions'] == []
    await m.detect(a.who, a.mid)
    assert len(m.view(a.who, a.mid)['interventions']) == 1
    question = 'Who will take responsibility for the launch checklist?'
    result = await m.review(a.who, a.mid, p['id'], Review(action='approve', revision=1, question=question))
    assert result['intervention_reviews'][0]['before']['question'] == p['question']
    assert result['interventions'][0]['state']['original_question'] == p['question']
    event = a.queue.get_nowait()
    captured = []
    class TTS:
        async def stream_audio(self, text, *, cancel):
            captured.append(text)
            yield AudioChunk(b'\x01\x00'*100, 24000)
    a.tts_factory = TTS
    a.manager.sockets[a.cid] = Socket(a)
    a.current_event = event
    await a.answer(event)
    a.current_event = None
    assert captured == [question]
    assert m.view(a.who, a.mid)['interventions'][0]['status'] == 'spoken'
    assert m.ai.calls == 3  # Detection twice and approval; unchanged pre-speech check is reused.
    exported = client.get('/api/meetings/'+a.mid+'/export').json()
    assert exported['intervention_reviews'][0]['after']['question'] == question
    assert exported['assistant_utterances'][0]['content'] == question


@pytest.mark.parametrize('change', ['expired', 'legacy', 'new_speech'])
async def test_approval_receipt_requires_fresh_matching_context(governed, change):
    a, m = governed
    p = await propose(governed)
    await m.review(a.who, a.mid, p['id'], Review(action='approve', revision=1))
    if change == 'new_speech':
        add_discussion(a, 1)
    else:
        with a.store.scope(a.who) as r:
            saved = r.get(db.meeting_interventions, p['id'])
            state = dict(saved['state'])
            if change == 'expired':
                state['approved_checked_at'] = time.time() - m.approval_check_ttl - 1
            else:
                state.pop('approved_checked_at')
                state.pop('approved_revision')
            r.change(db.meeting_interventions, p['id'], state=state)
    before = m.ai.calls
    assert await m.prepare_speech(a, a.queue.get_nowait()) == p['question']
    assert m.ai.calls == before + 1


async def test_corrected_evidence_never_reuses_approval(governed):
    a, m = governed
    p = await propose(governed)
    await m.review(a.who, a.mid, p['id'], Review(action='approve', revision=1))
    with a.store.scope(a.who) as r:
        r.change(db.utterances, p['evidence'][0]['utterance_id'], content='The task was cancelled.')
    before = m.ai.calls
    with pytest.raises(ValueError, match='no longer relevant'):
        await m.prepare_speech(a, a.queue.get_nowait())
    assert m.ai.calls == before  # Invalid original evidence is rejected locally.


async def test_owner_only_routes_and_cross_meeting_access(governed, client, app):
    a, m = governed
    p = await propose(governed)
    url = f'/api/meetings/{a.mid}/interventions'
    other = TestClient(app)
    assert other.get(url).status_code == 401
    assert other.post(url+'/'+p['id']+'/review', json={'action':'approve','revision':1}).status_code == 401
    # Owner-scoped repository access cannot retrieve another owner's suggestion.
    with a.store.scope('another-owner') as r:
        assert r.get(db.meeting_interventions, p['id']) is None
    with a.store.engine.begin() as c:
        c.execute(db.insert(db.users).values(id='another-owner',name='other',password=hash_password('other-password'),created_at=time.time()))
    other.cookies.set('echooo_owner', app.state.auth.issue('another-owner','owner',60))
    assert other.get(url).status_code == 404
    assert other.post(url+'/'+p['id']+'/review',json={'action':'approve','revision':1}).status_code == 404
    mid = client.post('/api/meetings',json={'title':'Other meeting'}).json()['id']
    assert client.post(f'/api/meetings/{mid}/interventions/{p["id"]}/review',json={'action':'reject','revision':1}).status_code == 404


async def test_defer_reject_and_old_revision_never_speak(governed):
    a, m = governed
    p = await propose(governed)
    await m.review(a.who,a.mid,p['id'],Review(action='defer',revision=1))
    with pytest.raises(Exception, match='changed'):
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    await m.review(a.who,a.mid,p['id'],Review(action='reject',revision=2))
    await m.detect(a.who,a.mid)
    assert a.queue.empty()
    assert [p['status'] for p in m.view(a.who,a.mid)['interventions']] == ['rejected']


@pytest.mark.parametrize('stage', ['approval','queued'])
async def test_resolved_question_cannot_be_spoken(governed, stage):
    a, m = governed
    p = await propose(governed)
    if stage == 'queued':
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    m.ai.relevant = False
    with a.store.scope(a.who) as r:
        r.add(db.utterances, meeting_id=a.mid, recording_id=None, speaker='Bob',
              content='Alice owns the launch checklist now.', start_ms=3000, end_ms=4000)
    if stage == 'approval':
        with pytest.raises(Exception, match='Nothing was played'):
            await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
        assert a.queue.empty()
    else:
        with pytest.raises(ValueError, match='no longer relevant'):
            await m.prepare_speech(a,a.queue.get_nowait())
    assert m.view(a.who,a.mid)['interventions'][0]['status'] == ('proposed' if stage == 'approval' else 'stale')


async def test_corrections_and_end_invalidate_suggestions(governed):
    a, m = governed
    p = await propose(governed)
    with a.store.scope(a.who) as r:
        r.change(db.utterances,p['evidence'][0]['utterance_id'],content='This was not a launch discussion.')
    assert m.view(a.who,a.mid)['interventions'][0]['status'] == 'stale'
    with pytest.raises(Exception):
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    assert a.queue.empty()
    await m.detect(a.who,a.mid)
    items = m.view(a.who,a.mid)['interventions']
    assert len(items) == 2  # Corrected evidence can support a fresh model proposal.
    with a.store.scope(a.who) as r:
        r.change(db.meetings,a.mid,status='ended')
    assert all(p['status']=='stale' for p in m.view(a.who,a.mid)['interventions'])


async def test_cancel_queue_stop_and_restart_never_replay(governed):
    a, m = governed
    p = await propose(governed)
    await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    await a.stop()
    assert a.queue.empty()
    assert m.view(a.who,a.mid)['interventions'][0]['status'] == 'cancelled'
    await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=2))
    m.resume()
    event = a.queue.get_nowait()
    with pytest.raises(ValueError,match='no longer valid'):
        await m.prepare_speech(a,event)
    assert m.view(a.who,a.mid)['intervention_reviews'][-1]['action'] == 'approve'


async def test_cancel_specific_queued_proposal_and_recheck_failure(governed):
    a, m = governed
    p = await propose(governed)
    await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    event = a.queue.get_nowait()
    a.queue.put_nowait(event)
    await m.review(a.who,a.mid,p['id'],Review(action='cancel',revision=2))
    assert a.queue.empty() and event['status']=='interrupted'
    with pytest.raises(ValueError):
        await m.prepare_speech(a,event)
    async def fail(*args,**kwargs):
        raise TimeoutError()
    m.ai.json_call = fail
    with pytest.raises(Exception,match='Nothing was approved'):
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=3))
    assert a.queue.empty()


async def test_old_cancelled_event_cannot_fail_new_approval(governed):
    a, m = governed
    p = await propose(governed)
    await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    old = a.queue.get_nowait()
    await m.review(a.who,a.mid,p['id'],Review(action='cancel',revision=2))
    await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=3))
    a.change(old,status='error')
    assert m.view(a.who,a.mid)['interventions'][0]['status'] == 'approved'


async def test_slow_background_model_does_not_block_cancellation(governed):
    a,m = governed
    p = await propose(governed)
    await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    entered = asyncio.Event()
    async def slow(*args,**kwargs):
        entered.set()
        await asyncio.Future()
    m.ai.json_call = slow
    task = asyncio.create_task(m.detect(a.who,a.mid))
    await entered.wait()
    try:
        await asyncio.wait_for(m.review(a.who,a.mid,p['id'],Review(action='cancel',revision=2)),.5)
        assert m.view(a.who,a.mid)['interventions'][0]['status']=='cancelled'
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)


async def test_concurrent_discussion_preserves_proposal_for_retry(governed):
    a, m = governed
    p = await propose(governed)
    original = m.ai.json_call
    async def update_then_check(*args,**kwargs):
        with a.store.scope(a.who) as r:
            r.add(db.utterances,meeting_id=a.mid,recording_id=None,speaker='Bob',content='The issue is still pending.',start_ms=3000,end_ms=4000)
        return await original(*args,**kwargs)
    m.ai.json_call = update_then_check
    with pytest.raises(Exception,match='discussion changed'):
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    assert m.view(a.who,a.mid)['interventions'][0]['status'] == 'proposed'
    assert a.queue.empty()


async def test_stop_during_approval_check_does_not_queue(governed):
    a, m = governed
    p = await propose(governed)
    original = m.ai.json_call
    async def stop_then_check(*args,**kwargs):
        await a.stop()
        return await original(*args,**kwargs)
    m.ai.json_call = stop_then_check
    with pytest.raises(Exception,match='stopped'):
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    assert a.queue.empty()


async def test_changed_context_blocks_outgoing_audio(governed):
    a, m = governed
    p = await propose(governed)
    await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    event = a.queue.get_nowait()
    await m.prepare_speech(a,event)
    m.guard(a,event)
    with a.store.scope(a.who) as r:
        r.change(db.utterances,p['evidence'][0]['utterance_id'],content='The checklist was cancelled.')
    with pytest.raises(ValueError,match='changed'):
        m.guard(a,event)


async def test_invalid_evidence_resolution_and_purge(governed):
    a, m = governed
    m.ai.invalid = True
    with pytest.raises(ValueError,match='evidence'):
        await propose(governed)
    assert m.view(a.who,a.mid)['interventions'] == []
    m.ai.invalid = False
    p = await propose(governed)
    await m.review(a.who,a.mid,p['id'],Review(action='defer',revision=1))
    m.ai.resolved = [p['id']]
    await m.detect(a.who,a.mid)
    assert m.view(a.who,a.mid)['interventions'][0]['status'] == 'stale'
    with a.store.scope(a.who) as r:
        purge_interventions(r,a.mid,{p['evidence'][0]['utterance_id']})
    assert m.view(a.who,a.mid)['interventions'] == []
    assert m.view(a.who,a.mid)['intervention_reviews'] == []


@pytest.mark.parametrize('unavailable', ['disabled', 'missing_credentials', 'mock_stt'])
async def test_without_online_voice_approval_is_not_recorded(governed, unavailable):
    a, m = governed
    p = await propose(governed)
    if unavailable == 'disabled':
        a.prefs['voice_enabled'] = False
    elif unavailable == 'missing_credentials':
        a.settings = replace(a.settings, dashscope_api_key='')
    else:
        a.settings = replace(a.settings, stt_provider='mock')
    with pytest.raises(Exception,match='enable server voice'):
        await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    assert m.view(a.who,a.mid)['intervention_reviews'] == []
    assert m.view(a.who,a.mid)['interventions'][0]['status'] == 'proposed'
    assert a.queue.empty()


def test_final_transcript_feed_persists_suggestions_and_reloads(client, app):
    base = '/api/meetings/'+client.post('/api/meetings',json={'title':'Automatic proposals'}).json()['id']
    m = app.state.meeting_interventions
    m.ai, m.enabled, m.delay = IssueModel(), True, .01
    m.quiet_seconds = .02
    for text in ['We need the checklist before launch, but no owner is assigned.', 'Next topic: support.']:
        assert client.post(base+'/utterances',json={'speaker':'Alice','content':text}).status_code == 201
    deadline = time.monotonic()+3
    while time.monotonic()<deadline:
        result = client.get(base+'/interventions').json()
        if result['interventions']:
            break
        time.sleep(.01)
    assert len(result['interventions']) == 1
    p = result['interventions'][0]
    assert client.post(base+f'/interventions/{p["id"]}/review',json={'action':'defer','revision':1}).status_code == 200
    reopened = db.Store(app.state.service.ai.settings.database_url)
    with reopened.scope(p['owner_id']) as r:
        assert r.get(db.meeting_interventions,p['id'])['status'] == 'deferred'
        assert len(r.list(db.meeting_intervention_reviews)) == 1
    reopened.close()
    assert client.get('/api/export').json()['meeting_interventions'][0]['id'] == p['id']
    assert client.delete(base).status_code == 200
    with app.state.store.scope(p['owner_id']) as r:
        assert not r.list(db.meeting_intervention_reviews)


async def test_tts_failure_never_marks_question_spoken(governed):
    a,m = governed
    p = await propose(governed)
    await m.review(a.who,a.mid,p['id'],Review(action='approve',revision=1))
    class BrokenTTS:
        async def stream_audio(self,text,*,cancel):
            raise RuntimeError('private provider details')
            yield
    a.tts_factory = BrokenTTS
    a.manager.sockets[a.cid] = Socket(a)
    worker = asyncio.create_task(a.work())
    try:
        async with asyncio.timeout(3):
            while m.view(a.who,a.mid)['interventions'][0]['status'] != 'failed':
                await asyncio.sleep(.01)
        with a.store.scope(a.who) as r:
            event = r.list(db.meeting_agent_events)[0]
            assert event['status']=='error'
            assert 'private provider details' not in event['error']
    finally:
        worker.cancel()
        await asyncio.gather(worker,return_exceptions=True)


def test_risk_and_contradiction_schema_require_real_evidence():
    rows = [dict(id=str(i),recording_id=None,speaker='Alice',content=t,start_ms=i,end_ms=i+1) for i,t in enumerate(['Friday is the release date.','Monday is the release date.'])]
    p = {'kind':'contradiction','statement':'The release date is disputed.', 'evidence':[{'utterance_id':r['id'],'quote':r['content']} for r in rows]}
    assert clean_decisions({'findings':[p]},rows,{'0','1'})[0]['kind'] == 'contradiction'
    with pytest.raises(ValueError,match='both sides'):
        clean_decisions({'findings':[{**p,'evidence':p['evidence'][:1]}]},rows,{'0'})
