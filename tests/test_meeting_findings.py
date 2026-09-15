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
