"""Deadline evidence repair must not discard valid findings or mark failures processed."""
import pytest

from echooo import database as db
from echooo.meeting_findings import clean_decisions, DeadlineEvidenceError
from test_product import app, client


def prepare(client, app, texts):
    manager = app.state.meeting_findings
    manager.enabled = False
    meeting = client.post('/api/meetings', json={'title': 'Deadline repair'}).json()
    base = '/api/meetings/' + meeting['id']
    rows = [client.post(base + '/utterances', json={'speaker': 'Alice', 'content': text}).json() for text in texts]
    manager.enabled = True
    return manager, meeting, rows, base


def finding(rows, *, kind='action_item', statement='Send the report next Friday.', raw='by next Friday'):
    return {'kind': kind, 'statement': statement, 'deadline_text': raw,
        'evidence': [{'utterance_id': row['id'], 'quote': row['content']} for row in rows]}


class RepairModel:
    def __init__(self, drafts, verified):
        self.drafts, self.verified, self.calls = drafts, verified, []

    async def json_call(self, prompt, data, fast=False):
        self.calls.append(data)
        if 'draft_findings' in data:
            if isinstance(self.verified, Exception):
                raise self.verified
            return {'findings': self.verified}
        return {'findings': self.drafts}


@pytest.mark.asyncio
async def test_rephrased_deadline_reaches_one_semantic_repair(client, app):
    manager, meeting, rows, _ = prepare(client, app, ['Please send the report next Friday.'])
    draft = finding(rows)
    with pytest.raises(DeadlineEvidenceError):
        clean_decisions({'findings': [draft]}, rows, {rows[0]['id']})
    manager.ai = RepairModel([draft], [finding(rows, raw='next Friday')])
    await manager.extract(meeting['owner_id'], meeting['id'])
    data = manager.view(meeting['owner_id'], meeting['id'])
    assert len(manager.ai.calls) == 2
    assert manager.ai.calls[1]['validation_issues'] == [{'index': 0, 'reason': 'Unsupported deadline text'}]
    assert data['findings'][0]['details']['deadline_text'] == 'next Friday'
    assert data['finding_progress']['pending'] == 0


@pytest.mark.asyncio
async def test_repair_can_add_missing_deadline_source(client, app):
    manager, meeting, rows, _ = prepare(client, app, ['Please send the report.', 'It is due next Friday.'])
    manager.ai = RepairModel([finding(rows[:1], raw='next Friday')], [finding(rows, raw='next Friday')])
    await manager.extract(meeting['owner_id'], meeting['id'])
    saved = manager.view(meeting['owner_id'], meeting['id'])['findings'][0]
    assert {e['utterance_id'] for e in saved['evidence']} == {row['id'] for row in rows}
    assert saved['details']['deadline_text'] == 'next Friday'


@pytest.mark.asyncio
async def test_cross_fragment_deadline_requires_verified_statement_and_original_citations(client, app):
    manager, meeting, rows, _ = prepare(client, app, ['请下周', '五之前发送报告。'])
    statement = '下周五之前发送报告。'
    manager.ai = RepairModel([finding(rows, statement=statement, raw='下周五')],
        [finding(rows, statement=statement, raw=None)])
    await manager.extract(meeting['owner_id'], meeting['id'])
    saved = manager.view(meeting['owner_id'], meeting['id'])['findings'][0]
    assert len(manager.ai.calls) == 2
    assert saved['statement'] == statement and saved['details']['deadline_text'] is None
    assert len(saved['evidence']) == 2


@pytest.mark.asyncio
async def test_failed_repair_preserves_valid_item_and_retry_does_not_overwrite_review(client, app):
    manager, meeting, rows, base = prepare(client, app,
        ['We decided to use SQLite. Please send the report next Friday.'])
    valid = finding(rows, kind='decision', statement='Use SQLite.', raw=None)
    invalid = finding(rows)
    manager.ai = RepairModel([valid, invalid], [valid, invalid])
    with pytest.raises(ValueError, match='Some passages still need extraction'):
        await manager.extract(meeting['owner_id'], meeting['id'])
    data = manager.view(meeting['owner_id'], meeting['id'])
    assert len(data['findings']) == 1 and data['finding_progress']['pending'] == 1
    decision = data['findings'][0]
    approved = client.post(base + f"/findings/{decision['id']}/review", json={'action': 'approve', 'revision': decision['revision']})
    assert approved.status_code == 200
    with manager.store.scope(meeting['owner_id']) as r:
        progress = manager.progress(r, meeting['id'])
        assert rows[0]['id'] not in progress['processed']
    manager.ai = RepairModel([valid, invalid], [valid, finding(rows, raw='next Friday')])
    await manager.extract(meeting['owner_id'], meeting['id'])
    data = manager.view(meeting['owner_id'], meeting['id'])
    assert len(data['findings']) == 2 and data['finding_progress']['pending'] == 0
    assert next(f for f in data['findings'] if f['id'] == decision['id'])['status'] == 'approved'
    assert len(data['finding_reviews']) == 1


@pytest.mark.asyncio
async def test_repair_timeout_saves_valid_decision_but_defers_unverified_actions(client, app):
    manager, meeting, rows, _ = prepare(client, app,
        ['We decided to use SQLite.', 'Please send the report next Friday.', 'Please review the checklist.'])
    valid = finding(rows[:1], kind='decision', statement='Use SQLite.', raw=None)
    invalid = finding(rows[1:2])
    unverified = finding(rows[2:], statement='Review the checklist.', raw=None)
    manager.ai = RepairModel([valid, invalid, unverified], TimeoutError())
    with pytest.raises(ValueError, match='Some passages still need extraction'):
        await manager.extract(meeting['owner_id'], meeting['id'])
    data = manager.view(meeting['owner_id'], meeting['id'])
    assert len(data['findings']) == 1 and data['findings'][0]['kind'] == 'decision'
    assert data['finding_progress']['pending'] == 2
    assert len(manager.ai.calls) == 2


@pytest.mark.asyncio
async def test_unsupported_deadline_is_removed_from_statement_by_verifier(client, app):
    manager, meeting, rows, _ = prepare(client, app, ['Please send the report.'])
    manager.ai = RepairModel([finding(rows)], [finding(rows, statement='Send the report.', raw=None)])
    await manager.extract(meeting['owner_id'], meeting['id'])
    saved = manager.view(meeting['owner_id'], meeting['id'])['findings'][0]
    assert saved['statement'] == 'Send the report.'
    assert saved['details']['deadline_text'] is None and saved['details']['deadline'] is None
