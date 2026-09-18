import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from echooo import database as db
from echooo.meeting_findings import clean_decisions
from echooo.meeting_live import TranscriptWriter
from echooo.models import STTEvent, STTEventType
from test_product import app, client


class DecisionModel:
    def __init__(self):
        self.calls = 0
        self.invalid = False

    async def json_call(self, prompt, data, fast=False):
        self.calls += 1
        return {'decisions': [{'statement': u['content'], 'evidence': [
            {'utterance_id': u['id'], 'quote': 'invented quote' if self.invalid else u['content']}]
        } for u in data['new_records'] if u['content'].startswith('We decided')]}


def setup(client, app):
    m = client.post('/api/meetings', json={'title': 'Decision review'}).json()
    manager = app.state.meeting_findings
    manager.ai = DecisionModel()
    manager.enabled = True
    manager.delay = 0
    return '/api/meetings/' + m['id'], manager


def await_findings(client, path, *, phase=None, count=1):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        value = client.get(path + '/findings').json()
        if (phase and value['finding_progress']['phase'] == phase) or (not phase and len(value['findings']) >= count):
            return value
        time.sleep(.01)
    pytest.fail(f'Decision processing did not complete: {value}')


def test_automatic_decision_review_record_export_and_reload(client, app):
    path, manager = setup(client, app)
    u = client.post(path + '/utterances', json={'speaker': 'Alice', 'content': 'We decided to ship Friday.'}).json()
    data = await_findings(client, path)
    f = data['findings'][0]
    assert f['status'] == 'provisional'
    assert f['evidence'][0]['utterance_id'] == u['id']
    assert data['approved_record']['decisions'] == []
    response = client.post(path + f"/findings/{f['id']}/review", json={'action': 'approve', 'revision': 1})
    assert response.status_code == 200
    record = client.post(path + '/approved-record').json()
    assert record['summary'] == 'We decided to ship Friday.'
    assert len(client.get(path).json()['finding_reviews']) == 1
    assert client.get(path + '/export').json()['approved_record'] == record
    export = client.get('/api/export').json()
    assert len(export['meeting_findings']) == 1
    # Reopen the same DB to verify additive schema initialization and persisted review.
    reopened = db.Store(app.state.service.ai.settings.database_url)
    with reopened.scope(f['owner_id']) as r:
        assert r.get(db.meeting_findings, f['id'])['status'] == 'approved'
    reopened.close()
    client.post(path + '/findings/extract')
    await_findings(client, path, phase='idle')
    assert manager.ai.calls == 1
    assert len(client.get(path + '/findings').json()['findings']) == 1


def test_edit_reject_stale_requests_and_meeting_scope(client, app):
    path, _ = setup(client, app)
    for content in ['We decided to ship Friday.', 'We decided to use SQLite.']:
        client.post(path + '/utterances', json={'speaker': 'Alice', 'content': content})
    items = await_findings(client, path, count=2)['findings']
    first, second = items
    url = path + f"/findings/{first['id']}/review"
    edited = client.post(url, json={'action': 'edit', 'revision': 1, 'statement': 'Ship on Friday after review.'})
    assert edited.status_code == 200
    f = edited.json()['findings'][0]
    assert f['original']['statement'] == 'We decided to ship Friday.'
    assert f['evidence'] == first['evidence']
    assert client.post(url, json={'action': 'approve', 'revision': 1}).status_code == 409
    assert client.post(path + f"/findings/{second['id']}/review", json={'action': 'reject', 'revision': 1}).status_code == 200
    assert len(client.post(path + '/approved-record').json()['decisions']) == 1
    other = client.post('/api/meetings', json={'title': 'Other'}).json()
    assert client.post(f"/api/meetings/{other['id']}/findings/{first['id']}/review", json={'action': 'approve', 'revision': 2}).status_code == 404
    stranger = TestClient(app)
    assert stranger.get(path + '/findings').status_code == 401
    assert stranger.post(path + '/approved-record').status_code == 401
    # Authenticated different owner cannot read or approve this meeting.
    from echooo.auth import hash_password
    from sqlalchemy import insert
    with app.state.store.engine.begin() as c:
        c.execute(insert(db.users).values(id='other-owner', name='other-owner', password=hash_password('password-123456'), created_at=time.time()))
    assert stranger.post('/api/auth/login', json={'name': 'other-owner', 'password': 'password-123456'}).status_code == 200
    assert stranger.get(path + '/findings').status_code == 404
    assert stranger.post(url, json={'action':'approve','revision':2}).status_code == 404


def test_invalid_evidence_does_not_advance_progress_and_can_retry(client, app):
    path, manager = setup(client, app)
    manager.ai.invalid = True
    client.post(path + '/utterances', json={'content': 'We decided to ship Friday.'})
    failed = await_findings(client, path, phase='error')
    assert failed['findings'] == []
    manager.ai.invalid = False
    client.post(path + '/findings/extract')
    assert len(await_findings(client, path)['findings']) == 1


def test_source_correction_excludes_approved_decision_without_losing_audit(client, app):
    path, manager = setup(client, app)
    u = client.post(path + '/utterances', json={'content': 'We decided to ship Friday.'}).json()
    f = await_findings(client, path)['findings'][0]
    client.post(path + f"/findings/{f['id']}/review", json={'action': 'approve', 'revision': 1})
    manager.enabled = False
    client.patch(path + '/utterances/' + u['id'], json={'speaker': 'Alice', 'content': 'We only proposed Friday.'})
    data = client.get(path + '/findings').json()
    assert data['findings'][0]['status'] == 'approved'
    assert not data['findings'][0]['evidence_current']
    assert data['approved_record']['decisions'] == []
    assert data['finding_reviews'][0]['after']['statement'] == 'We decided to ship Friday.'


@pytest.mark.asyncio
async def test_writer_hook_is_nonblocking_and_ignores_partial(client, app):
    path, manager = setup(client, app)
    m = client.get(path).json()
    gate = asyncio.Event()
    entered = asyncio.Event()
    model = manager.ai
    class SlowModel:
        async def json_call(self, *args, **kwargs):
            entered.set()
            await gate.wait()
            return await model.json_call(*args, **kwargs)
    manager.ai = SlowModel()
    with app.state.store.scope(m['owner_id']) as r:
        rec = r.add(db.recordings, meeting_id=m['id'], sample_rate=16000, samples=32000)
    writer = TranscriptWriter(app.state.store, m['owner_id'], m['id'], rec['id'], app.state.meeting_transcriptions.feed)
    writer.consume(STTEvent(type=STTEventType.PARTIAL, transcript='We decided'), 0, 1, 2000)
    assert not manager.tasks
    rows = writer.consume(STTEvent(type=STTEventType.FINAL, transcript='We decided to ship Friday.', raw={
        'turn_order': 1, 'speaker_label': 'A', 'words': [{'text': 'We decided to ship Friday.', 'start': 100, 'end': 1500}]}), 0, 1, 2000)
    assert rows and manager.tasks
    task = manager.tasks[m['owner_id'], m['id']]
    await asyncio.wait_for(entered.wait(), 1)
    assert not task.done()
    gate.set()
    await task
    result = manager.view(m['owner_id'], m['id'])
    f = result['findings'][0]
    assert f['evidence'][0]['start_ms'] == 100
    assert f['evidence'][0]['end_ms'] == 1500
    assert f['evidence'][0]['recording_id'] == rec['id']
    # Deleting source audio must also purge derivative quotes and audit snapshots.
    client.post(path + f"/findings/{f['id']}/review", json={'action':'approve','revision':1})
    assert client.delete(path + '/recordings/' + rec['id']).status_code == 200
    data = client.get(path + '/findings').json()
    assert data['findings'] == data['finding_reviews'] == []


def test_evidence_validation_requires_all_references_and_new_input():
    u = dict(id='u', recording_id='r', content='We decided yes.', speaker='A', start_ms=0, end_ms=100)
    item = {'statement': 'Yes', 'evidence': [{'utterance_id': 'u', 'quote': 'We decided yes.'}]}
    assert clean_decisions({'decisions':[item]}, [u], {'other'}) == []
    with pytest.raises(ValueError):
        clean_decisions({'decisions':[{**item, 'evidence':item['evidence']+[{'utterance_id':'missing','quote':'yes'}]}]}, [u], {'u'})

class FindingsModel:
    async def json_call(self, prompt, data, fast=False):
        items=[]
        for u in data['new_records']:
            text=u['content']
            if text.startswith('Alice will'):
                item=dict(kind='action_item', statement='Send the report', owner='Alice', deadline='2026-09-18', deadline_text='2026-09-18')
            elif text.startswith('Who will'):
                item=dict(kind='unresolved_question', statement=text)
            elif text.startswith('Bob will own'):
                target=next(f for f in data['existing_findings'] if f['kind']=='unresolved_question')
                item=dict(kind='unresolved_question',statement=target['statement'],supersedes=target['id'],resolved=True)
            elif text.startswith('Change deadline'):
                target=next(f for f in data['existing_findings'] if f['kind']=='action_item')
                item=dict(kind='action_item',statement=target['statement'],owner='Alice',deadline='2026-09-21',deadline_text='2026-09-21',supersedes=target['id'])
            elif text.startswith('We decided'):
                item=dict(kind='decision',statement=text)
            else:
                continue
            item['evidence']=[dict(utterance_id=u['id'],quote=text)]
            items.append(item)
        return {'findings':items}


def add_and_wait(client,path,content,count):
    client.post(path+'/utterances',json={'speaker':'Alice','content':content})
    return await_findings(client,path,count=count)


def approve(client,path,f):
    result=client.post(path+f"/findings/{f['id']}/review",json={'action':'approve','revision':f['revision']})
    assert result.status_code==200,result.text
    return result.json()


def test_three_types_metadata_replacement_and_resolution(client,app):
    path,manager=setup(client,app)
    manager.ai=FindingsModel()
    add_and_wait(client,path,'We decided to use SQLite.',1)
    add_and_wait(client,path,'Alice will send the report by 2026-09-18.',2)
    data=add_and_wait(client,path,'Who will own the launch?',3)
    for f in data['findings']:approve(client,path,f)
    record=client.post(path+'/approved-record').json()
    assert len(record['decisions'])==len(record['action_items'])==len(record['unresolved_questions'])==1
    assert record['action_items'][0]['details']['owner']=='Alice'
    assert record['action_items'][0]['details']['deadline']=='2026-09-18'
    data=add_and_wait(client,path,'Change deadline for Alice to 2026-09-21.',4)
    revision=data['findings'][-1]
    assert revision['status']=='provisional'
    assert data['approved_record']['action_items'][0]['details']['deadline']=='2026-09-18'
    approve(client,path,revision)
    data=add_and_wait(client,path,'Bob will own the launch.',5)
    assert len(data['approved_record']['unresolved_questions'])==1
    data=approve(client,path,data['findings'][-1])
    assert data['approved_record']['unresolved_questions']==[]
    assert len(data['approved_record']['action_items'])==1
    assert data['approved_record']['action_items'][0]['details']['deadline']=='2026-09-21'
    # Duplicate new utterances do not resurrect replaced or rejected items.
    client.post(path+'/utterances',json={'speaker':'Alice','content':'We decided to use SQLite.'})
    client.post(path+'/approved-record')
    assert len(client.get(path+'/findings').json()['findings'])==5


def test_rereview_requires_exact_current_evidence_and_preserves_original(client,app):
    path,manager=setup(client,app)
    u=client.post(path+'/utterances',json={'speaker':'Alice','content':'We decided to ship Friday.'}).json()
    f=await_findings(client,path)['findings'][0]
    approve(client,path,f)
    manager.enabled=False
    client.patch(path+'/utterances/'+u['id'],json={'speaker':'Bob','content':'We decided to ship Monday.'})
    f=client.get(path+'/findings').json()['findings'][0]
    url=path+f"/findings/{f['id']}/review"
    body=dict(action='edit',revision=f['revision'],statement='Ship Monday.')
    assert client.post(url,json=body).status_code==409
    token=f['evidence_token']
    client.patch(path+'/utterances/'+u['id'],json={'speaker':'Bob','content':'We decided to ship Tuesday.'})
    assert client.post(url,json={**body,'evidence_token':token}).status_code==409
    f=client.get(path+'/findings').json()['findings'][0]
    result=client.post(url,json={**body,'statement':'Ship Tuesday.','evidence_token':f['evidence_token']})
    assert result.status_code==200,result.text
    data=result.json()
    assert data['findings'][0]['evidence_current']
    assert data['findings'][0]['original']['statement']=='We decided to ship Friday.'
    assert data['finding_reviews'][-1]['before']['evidence'][0]['speaker']=='Alice'
    assert data['approved_record']['decisions'][0]['statement']=='Ship Tuesday.'


def test_action_validation_keeps_unknown_and_ambiguous_deadlines_empty():
    row=dict(id='a',recording_id='r',speaker='Unknown speaker',content='I will do this next Friday.',start_ms=0,end_ms=1)
    output={'findings':[dict(kind='action_item',statement='Do this',owner='Alice',deadline='2026-09-18',deadline_text='next Friday',evidence=[dict(utterance_id='a',quote=row['content'])])]}
    result=clean_decisions(output,[row],{'a'})[0]
    assert result['details']['owner'] is None
    assert result['details']['deadline'] is None
    assert result['details']['deadline_text']=='next Friday'


@pytest.mark.asyncio
async def test_restart_recovers_pending_input_and_flush_waits_for_it(client,app):
    path,old=setup(client,app)
    old.enabled=False
    u=client.post(path+'/utterances',json={'content':'We decided to finish now.'}).json()
    from echooo.meeting_findings import MeetingFindings
    manager=MeetingFindings(app.state.store,DecisionModel(),app.state.meeting_transcriptions.feed)
    manager.delay=0
    manager.resume()
    assert (u['owner_id'],u['meeting_id']) in manager.tasks
    await manager.flush(u['owner_id'],u['meeting_id'])
    assert len(manager.view(u['owner_id'],u['meeting_id'])['findings'])==1
    await manager.close()
    old.feed.on_utterance=old.notify


def test_end_triggers_remaining_extraction_and_record_waits(client,app):
    path,manager=setup(client,app)
    manager.delay=.05
    client.post(path+'/utterances',json={'content':'We decided to finish with SQLite.'})
    assert client.post(path+'/end').status_code==200
    result=client.post(path+'/approved-record')
    assert result.status_code==200,result.text
    data=client.get(path+'/findings').json()
    assert data['finding_progress']['pending']==0
    assert len(data['findings'])==1
    assert result.json()['decisions']==[]  # Processing does not approve anything.


def test_additive_finding_migration_preserves_old_reviewed_rows(tmp_path):
    from sqlalchemy import create_engine,text,inspect
    from echooo.migrations import add_finding_details
    engine=create_engine('sqlite:///'+str(tmp_path/'old.db'))
    with engine.begin() as c:
        c.execute(text('CREATE TABLE meeting_findings (id TEXT PRIMARY KEY, statement TEXT)'))
        c.execute(text("INSERT INTO meeting_findings VALUES ('old','Reviewed decision')"))
    add_finding_details(engine)
    add_finding_details(engine)
    with engine.connect() as c:
        row=c.execute(text('SELECT statement,details FROM meeting_findings')).one()
        assert row==('Reviewed decision','{}')
    engine.dispose()


def test_later_revision_can_restore_old_value_without_restoring_old_record(client,app):
    path,manager=setup(client,app)
    class RevertingModel(FindingsModel):
        async def json_call(self,prompt,data,fast=False):
            result=await super().json_call(prompt,data,fast)
            if any('back to' in u['content'] for u in data['new_records']):
                for item in result['findings']:
                    item.update(deadline='2026-09-18',deadline_text='2026-09-18')
            return result
    manager.ai=RevertingModel()
    f=add_and_wait(client,path,'Alice will send the report by 2026-09-18.',1)['findings'][0]
    approve(client,path,f)
    f=add_and_wait(client,path,'Change deadline for Alice to 2026-09-21.',2)['findings'][-1]
    approve(client,path,f)
    f=add_and_wait(client,path,'Change deadline for Alice back to 2026-09-18.',3)['findings'][-1]
    data=approve(client,path,f)
    assert len(data['approved_record']['action_items'])==1
    assert data['approved_record']['action_items'][0]['id']==f['id']
    assert data['approved_record']['action_items'][0]['details']['deadline']=='2026-09-18'


def test_failed_final_flush_never_returns_a_completed_record(client,app):
    path,manager=setup(client,app)
    manager.retry_delay=.01
    manager.ai.invalid=True
    client.post(path+'/utterances',json={'content':'We decided to ship Friday.'})
    assert client.post(path+'/approved-record').status_code==409
    assert client.get(path+'/findings').json()['finding_progress']['pending']==1


@pytest.mark.asyncio
async def test_finalization_waits_for_transcript_but_not_legacy_notes(client,app):
    path,manager=setup(client,app)
    m=client.get(path).json()
    transcriptions=app.state.meeting_transcriptions
    with app.state.store.scope(m['owner_id']) as r:
        rec=r.add(db.recordings,meeting_id=m['id'],sample_rate=16000,samples=32000)
    transcriptions.state(m['owner_id'],m['id'],rec['id'],phase='verifying')
    notes_gate=asyncio.Event()
    async def verify_then_build_notes():
        await asyncio.sleep(.02)
        with app.state.store.scope(m['owner_id']) as r:
            u=r.add(db.utterances,meeting_id=m['id'],recording_id=rec['id'],speaker='Alice',content='We decided to keep the last sentence.',start_ms=0,end_ms=1000)
        transcriptions.state(m['owner_id'],m['id'],rec['id'],phase='complete',summary_phase='building')
        transcriptions.feed.publish(m['owner_id'],m['id'],{'type':'utterance','utterance':u})
        await notes_gate.wait()
    task=asyncio.create_task(verify_then_build_notes())
    transcriptions.tasks[rec['id']]=task
    try:
        await asyncio.wait_for(manager.before_record(m['owner_id'],m['id']),1)
        assert not task.done()
        await manager.flush(m['owner_id'],m['id'])
        assert manager.view(m['owner_id'],m['id'])['findings'][0]['statement']=='We decided to keep the last sentence.'
    finally:
        notes_gate.set()
        await task
        transcriptions.tasks.pop(rec['id'],None)


def test_finalization_rechecks_capture_after_model_wait(client,app):
    from echooo.service import Problem
    path,manager=setup(client,app)
    calls=[]
    async def capture_check(who,mid):
        calls.append(mid)
        if len(calls)==2:
            raise Problem('Recording restarted.',409)
    manager.before_record=capture_check
    assert client.post(path+'/approved-record').status_code==409
    assert len(calls)==2


def test_legacy_decision_checkpoint_replay_preserves_review_with_paraphrased_output(client,app):
    from echooo.meeting_findings import digest
    from echooo.meeting_minutes import normalized
    path,manager=setup(client,app)
    f=add_and_wait(client,path,'We decided to ship Friday.',1)['findings'][0]
    approve(client,path,f)
    with app.state.store.scope(f['owner_id']) as r:
        r.change(db.meeting_findings,f['id'],fingerprint=digest(sorted((e['utterance_id'],normalized(e['quote'])) for e in f['evidence'])))
        progress=r.list(db.meeting_finding_progress)[0]
        r.change(db.meeting_finding_progress,progress['id'],processed={})
    class ParaphraseModel(DecisionModel):
        async def json_call(self,*args,**kwargs):
            output=await super().json_call(*args,**kwargs)
            output['decisions'][0]['statement']='Ship this Friday.'
            return output
    manager.ai=ParaphraseModel()
    result=client.post(path+'/approved-record')
    assert result.status_code==200,result.text
    data=client.get(path+'/findings').json()
    assert len(data['findings'])==1
    assert data['findings'][0]['status']=='approved'


def test_unchanged_pending_finding_refreshes_evidence_after_speaker_correction(client, app):
    path, manager = setup(client, app)
    u = client.post(path + '/utterances', json={'speaker': 'Alice', 'content': 'We decided to ship Friday.'}).json()
    f = await_findings(client, path)['findings'][0]
    client.patch(path + '/utterances/' + u['id'], json={'speaker': 'Bob', 'content': u['content']})
    client.post(path + '/approved-record')
    data = client.get(path + '/findings').json()
    assert len(data['findings']) == 1
    refreshed = data['findings'][0]
    assert refreshed['id'] == f['id']
    assert refreshed['evidence_current']
    assert refreshed['status'] == 'provisional'
    assert refreshed['evidence'][0]['speaker'] == 'Bob'
    assert refreshed['original']['evidence'][0]['speaker'] == 'Alice'
    assert data['finding_reviews'][-1]['action'] == 'extraction_revision'
    approve(client, path, refreshed)
    # The same change to an approved finding must still require explicit host review.
    client.patch(path + '/utterances/' + u['id'], json={'speaker': 'Carol', 'content': u['content']})
    client.post(path + '/approved-record')
    data = client.get(path + '/findings').json()
    assert not data['findings'][0]['evidence_current']
    assert data['approved_record']['decisions'] == []


def test_manual_recheck_recovers_previously_processed_stale_pending_item(client, app):
    from echooo.meeting_findings import source_hash
    path, manager = setup(client, app)
    u = client.post(path + '/utterances', json={'speaker': 'Alice', 'content': 'We decided to ship Friday.'}).json()
    f = await_findings(client, path)['findings'][0]
    client.post(path + '/approved-record')
    with manager.store.scope(f['owner_id']) as r:
        r.change(db.utterances, u['id'], speaker='Bob')
        changed = r.get(db.utterances, u['id'])
        p = manager.progress(r, f['meeting_id'])
        r.change(db.meeting_finding_progress, p['id'], processed={u['id']: source_hash(changed)})
    assert not client.get(path + '/findings').json()['findings'][0]['evidence_current']
    client.post(path + '/findings/extract')
    client.post(path + '/approved-record')
    assert client.get(path + '/findings').json()['findings'][0]['evidence_current']


def test_corrected_statement_and_evidence_are_updated_together(client, app):
    path, manager = setup(client, app)
    u = client.post(path + '/utterances', json={'speaker': 'Alice', 'content': 'We decided to ship Friday.'}).json()
    old = await_findings(client, path)['findings'][0]
    client.post(path + '/approved-record')

    class CorrectionModel:
        async def json_call(self, prompt, data, fast=False):
            previous = data['existing_findings'][0]
            assert previous['evidence_ids'] == [u['id']]
            assert not previous['evidence_current']
            row = data['new_records'][0]
            return {'findings': [{'kind': 'decision', 'statement': 'Ship Monday.',
                'supersedes': previous['id'], 'evidence': [{'utterance_id': row['id'], 'quote': row['content']}]}]}

    manager.ai = CorrectionModel()
    client.patch(path + '/utterances/' + u['id'], json={'speaker': 'Bob', 'content': 'We decided to ship Monday.'})
    client.post(path + '/approved-record')
    data = client.get(path + '/findings').json()
    assert len(data['findings']) == 1
    f = data['findings'][0]
    assert f['id'] == old['id'] and f['statement'] == 'Ship Monday.'
    assert f['evidence_current'] and f['evidence'][0]['quote'] == 'We decided to ship Monday.'
    assert f['original']['statement'] == old['statement']


def test_retry_drains_54_passages_after_splitting_invalid_batch(client, app):
    path, manager = setup(client, app)
    manager.enabled = False
    for i in range(54):
        client.post(path + '/utterances', json={'content': f'Passage {i}'})

    class BatchModel:
        async def json_call(self, prompt, data, fast=False):
            if len(data['new_records']) > 4:
                raise ValueError('Model output was truncated')
            return {'findings': []}

    manager.ai = BatchModel()
    manager.enabled = True
    assert client.get(path + '/findings').json()['finding_progress']['pending'] == 54
    assert client.post(path + '/findings/extract').status_code == 200
    result = await_findings(client, path, phase='idle')
    assert result['finding_progress']['pending'] == 0


def test_bad_passage_does_not_block_other_passages_or_fake_completion(client, app):
    path, manager = setup(client, app)
    manager.enabled = False
    ids = [client.post(path + '/utterances', json={'content': str(i)}).json()['id'] for i in range(5)]

    class BrokenModel:
        broken = True

        async def json_call(self, prompt, data, fast=False):
            if self.broken and any(u['id'] == ids[0] for u in data['new_records']):
                raise ValueError('Unsupported evidence')
            return {'findings': []}

    manager.ai = BrokenModel()
    manager.enabled = True
    manager.retry_delay = 0
    client.post(path + '/findings/extract')
    failed = await_findings(client, path, phase='error')
    assert failed['finding_progress']['pending'] == 1
    manager.ai.broken = False
    client.post(path + '/findings/extract')
    assert await_findings(client, path, phase='idle')['finding_progress']['pending'] == 0


def test_action_semantic_verification_can_correct_category(client, app):
    path, manager = setup(client, app)

    class VerifiedModel:
        verified = False

        async def json_call(self, prompt, data, fast=False):
            u = data['new_records'][0]
            self.verified = 'draft_findings' in data
            return {'findings': [{'kind': 'unresolved_question' if self.verified else 'action_item',
                'statement': u['content'], 'evidence': [{'utterance_id': u['id'], 'quote': u['content']}]}]}

    manager.ai = VerifiedModel()
    client.post(path + '/utterances', json={'content': 'Is the inspection complete before the handover?'})
    result = await_findings(client, path)
    assert manager.ai.verified
    assert result['findings'][0]['kind'] == 'unresolved_question'


def test_review_categories_and_all_outcomes_survive_database_reopen(client, app):
    path, manager = setup(client, app)
    manager.enabled = False
    for i in range(3):
        client.post(path + '/utterances', json={'content': f'We decided on option {i}.'})
    manager.enabled = True
    client.post(path + '/findings/extract')
    items = await_findings(client, path, count=3)['findings']
    for f, action in zip(items, ['approve', 'edit', 'reject']):
        body = {'action': action, 'revision': f['revision']}
        if action == 'edit':
            body.update(kind='unresolved_question', statement='Which option needs further review?')
        assert client.post(path + f"/findings/{f['id']}/review", json=body).status_code == 200
    reopened = db.Store(app.state.service.ai.settings.database_url)
    with reopened.scope(items[0]['owner_id']) as r:
        stored = [r.get(db.meeting_findings, f['id']) for f in items]
        assert [f['status'] for f in stored] == ['approved', 'edited', 'rejected']
        assert stored[1]['kind'] == 'unresolved_question'
        assert stored[1]['statement'] == 'Which option needs further review?'
        assert len(r.list(db.meeting_finding_reviews)) == 3
    reopened.close()
    refreshed = client.get(path + '/findings').json()
    assert len(refreshed['approved_record']['decisions']) == 1
    assert len(refreshed['approved_record']['unresolved_questions']) == 1


def test_reclassification_clears_action_metadata_and_preserves_audit(client, app):
    path, manager = setup(client, app)
    manager.ai = FindingsModel()
    data = add_and_wait(client, path, 'Alice will send the report by 2026-09-18.', 1)
    f = data['findings'][0]
    result = client.post(path + f"/findings/{f['id']}/review", json={
        'action': 'edit', 'revision': f['revision'], 'kind': 'unresolved_question',
        'statement': 'When should the report be sent?'}).json()
    changed = result['findings'][0]
    assert changed['kind'] == 'unresolved_question'
    assert all(changed['details'][key] is None for key in ('owner', 'deadline', 'deadline_text'))
    assert result['finding_reviews'][-1]['before']['kind'] == 'action_item'
    assert result['finding_reviews'][-1]['after']['kind'] == 'unresolved_question'


def test_semantic_verifier_invalid_evidence_does_not_save_draft(client, app):
    path, manager = setup(client, app)
    manager.retry_delay = 0

    class InvalidVerifier:
        async def json_call(self, prompt, data, fast=False):
            u = data['new_records'][0]
            return {'findings': [{'kind': 'action_item', 'statement': 'Prepare the handover',
                'evidence': [{'utterance_id': u['id'],
                    'quote': 'Unsupported quote' if 'draft_findings' in data else u['content']}]}]}

    manager.ai = InvalidVerifier()
    client.post(path + '/utterances', json={'content': 'Please prepare the handover.'})
    failed = await_findings(client, path, phase='error')
    assert failed['findings'] == []
    assert failed['finding_progress']['pending'] == 1


def test_review_speaker_names_persist_without_changing_source(client, app):
    path, manager = setup(client, app)
    client.post(path + '/utterances', json={'speaker': 'Speaker D', 'content': 'We decided to review the proposal.'})
    f = await_findings(client, path)['findings'][0]
    uid = f['evidence'][0]['utterance_id']
    url = path + f"/findings/{f['id']}/review"
    bad = client.post(url, json={'action': 'edit', 'revision': f['revision'],
        'statement': f['statement'], 'speaker_names': {'not-evidence': 'Alice'}})
    assert bad.status_code == 400
    response = client.post(url, json={'action': 'edit', 'revision': f['revision'],
        'statement': f['statement'], 'speaker_names': {uid: 'Alice'}})
    assert response.status_code == 200
    refreshed = client.get(path + '/findings').json()
    assert refreshed['findings'][0]['details']['speaker_names'] == {uid: 'Alice'}
    assert refreshed['findings'][0]['evidence'][0]['speaker'] == 'Speaker D'
    assert refreshed['findings'][0]['evidence_current']
    assert refreshed['finding_reviews'][-1]['after']['details']['speaker_names'] == {uid: 'Alice'}
