"""Lifecycle tests use simulated semantic judgments; live semantics have a separate evaluation."""
import copy

import pytest

from echooo import database as db
from echooo.meeting_interventions import Review, purge_interventions
from test_meeting_interventions import governed, agent, app, client, add_discussion, wait_until


def assessment(data, *, readiness='wait', status='open', missing=None, propose=False,
               ref=None, task='Complete the launch checklist', material_change=False):
    ref = ref or (data['tracked_tasks'][0]['id'] if data['tracked_tasks'] else 'new:checklist')
    evidence = [{'utterance_id': r['id'], 'quote': r['content']} for r in [data['records'][0], data['records'][-1]]]
    update = {'ref': ref, 'task': task, 'status': status,
        'missing': missing if missing is not None else ['owner', 'timing'],
        'readiness': readiness, 'material_change': material_change,
        'reason': 'The task needs clarification before the discussion concludes.', 'evidence': evidence}
    proposals = [{'kind': 'missing_detail', 'question': f'Who will own this task: {task}, and when will it be ready?',
        'reason': update['reason'], 'evidence': evidence, 'task_refs': [ref]}] if propose else []
    return {'task_updates': [update], 'proposals': proposals, 'resolved_ids': []}


class TaskModel:
    def __init__(self, result):
        self.result, self.inputs, self.review_inputs = result, [], []

    async def json_call(self, prompt, data, fast=False):
        if 'task_candidates' in data:
            self.review_inputs.append(copy.deepcopy(data))
            return {'checks': [{'candidate_id': c['id'], 'ready': True, 'same_issue_ids': [],
                'material_change': any(t['assessment'].get('material_change') for t in c['tasks']),
                'reason': 'The allocation exchange has concluded.'} for c in data['task_candidates']]}
        self.inputs.append(copy.deepcopy(data))
        return self.result(data)


async def start_waiting_task(governed, *, still_wait=False):
    a, m = governed
    now = [0.0]
    m.clock, m.delay, m.quiet_seconds = lambda: now[0], .001, 0
    def result(data):
        eligible = bool(data.get('followup_task_ids')) and not still_wait
        return assessment(data, readiness='review' if eligible else 'wait', propose=eligible)
    m.ai = TaskModel(result)
    m.notify(a.who, a.mid)
    await wait_until(lambda: (a.who, a.mid) not in m.tasks)
    assert len(m.ai.inputs) == 1 and not m.view(a.who, a.mid)['interventions']
    assert (a.who, a.mid) in m.followup_tasks
    return now


async def test_grace_expiry_publishes_host_review_question_without_more_speech(governed):
    a, m = governed
    now = await start_waiting_task(governed)
    key = a.who, a.mid
    m.quiet_seconds = 2  # Timer wake-up must not add another quiet interval.
    now[0] = m.task_grace_seconds - 1
    await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 1
    now[0] = m.task_grace_seconds
    await wait_until(lambda: bool(m.view(*key)['interventions']))
    await wait_until(lambda: key not in m.tasks)
    view = m.view(*key)
    assert len(m.ai.inputs) == 2 and len(m.ai.review_inputs) == 1
    ids = [view['tracked_tasks'][0]['id']]
    assert m.ai.inputs[-1]['new_record_ids'] == []
    assert m.ai.inputs[-1]['followup_task_ids'] == m.ai.review_inputs[0]['followup_task_ids'] == ids
    assert m.last_activity[key] == 0
    assert view['tracked_tasks'][0]['readiness'] == 'review'
    assert view['interventions'][0]['status'] == 'proposed' and a.queue.empty()
    assert view['intervention_progress']['last_check']['followup_task_ids'] == ids
    assert key not in m.followup_tasks and key not in m.followup_context
    now[0] = 120
    await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 2


async def test_grace_reassessment_does_not_poll_unchanged_unready_discussion(governed):
    a, m = governed
    now = await start_waiting_task(governed, still_wait=True)
    key = a.who, a.mid
    now[0] = m.task_grace_seconds
    await wait_until(lambda: len(m.ai.inputs) == 2 and key not in m.tasks)
    assert not m.ai.review_inputs and not m.view(*key)['interventions']
    assert key not in m.followup_tasks and key not in m.followup_context
    now[0] = 120
    await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 2
    add_discussion(a, 1)
    m.notify(*key)
    await wait_until(lambda: len(m.ai.inputs) == 3 and key not in m.tasks)
    assert key in m.followup_tasks  # New evidence permits one later reassessment.


async def test_natural_answer_during_grace_cancels_pending_question(governed):
    a, m = governed
    now = await start_waiting_task(governed)
    key = a.who, a.mid
    now[0] = m.task_grace_seconds - 1
    add_discussion(a, 1)
    m.ai.result = lambda data: assessment(data, status='resolved', missing=[])
    m.notify(*key)
    now[0] = m.task_grace_seconds
    await wait_until(lambda: key not in m.tasks)
    assert len(m.ai.inputs) == 2 and m.ai.inputs[-1]['followup_task_ids'] == []
    assert m.view(*key)['tracked_tasks'][0]['status'] == 'resolved'
    assert not m.view(*key)['interventions'] and not m.ai.review_inputs
    assert key not in m.followup_tasks


async def test_due_followup_waits_for_budget_without_losing_eligibility(governed):
    a, m = governed
    now = await start_waiting_task(governed)
    key = a.who, a.mid
    m.background_calls[key].extend([0] * 4)  # Only one slot remains.
    now[0] = m.task_grace_seconds
    await wait_until(lambda: m.followup_context.get(key, {}).get('due'))
    assert len(m.ai.inputs) == 1
    now[0] = 60
    await wait_until(lambda: bool(m.view(*key)['interventions']))
    assert len(m.ai.inputs) == 2 and len(m.ai.review_inputs) == 1


async def test_answer_arriving_during_timed_generation_is_rechecked_before_publication(governed):
    a, m = governed
    now = await start_waiting_task(governed)
    key = a.who, a.mid
    def result(data):
        if data.get('followup_task_ids'):
            add_discussion(a, 1)
            return assessment(data, readiness='review', propose=True)
        return assessment(data, status='resolved', missing=[])
    m.ai.result = result
    now[0] = m.task_grace_seconds
    await wait_until(lambda: len(m.ai.inputs) == 3 and key not in m.tasks)
    assert m.ai.inputs[1]['followup_task_ids']
    assert m.ai.inputs[2]['followup_task_ids'] == []
    assert m.ai.inputs[2]['new_record_ids']
    assert m.view(*key)['tracked_tasks'][0]['status'] == 'resolved'
    assert not m.view(*key)['interventions'] and not m.ai.review_inputs
    assert key not in m.followup_tasks and a.queue.empty()


@pytest.mark.parametrize('change', ['ended', 'deleted', 'closed'])
async def test_pending_grace_never_publishes_after_end_delete_or_shutdown(governed, change):
    a, m = governed
    now = await start_waiting_task(governed)
    key = a.who, a.mid
    if change == 'closed':
        await m.close()
    else:
        with a.store.scope(a.who) as r:
            if change == 'ended':
                r.change(db.meetings, a.mid, status='ended')
            else:
                for u in r.list(db.utterances):
                    r.remove(db.utterances, u['id'])
    now[0] = m.task_grace_seconds
    await wait_until(lambda: key not in m.followup_tasks)
    assert len(m.ai.inputs) == 1 and not m.ai.review_inputs
    assert not m.view(*key)['interventions']


async def test_first_assessment_publishes_review_question_without_grace_or_speech(governed):
    a, m = governed
    with a.store.scope(a.who) as r:
        rows = r.list(db.utterances)
        r.change(db.utterances, rows[0]['id'], content='We need to prepare the walkthrough.')
        for row in rows[1:]:
            r.remove(db.utterances, row['id'])
    now = [0.0]
    m.clock, m.delay = lambda: now[0], .001
    m.ai = TaskModel(lambda data: assessment(data, readiness='review', propose=True))
    key = a.who, a.mid
    m.notify(*key)
    await wait_until(lambda: m.phases.get(key) == 'scheduled')
    now[0] = 2  # Default coalescing window, with no topic transition or follow-up.
    await wait_until(lambda: key not in m.tasks)
    view = m.view(*key)
    assert len(m.ai.inputs) == len(m.ai.review_inputs) == 1
    assert m.ai.inputs[0]['followup_task_ids'] == []
    assert len(view['interventions']) == 1 and view['interventions'][0]['status'] == 'proposed'
    assert key not in m.followup_tasks and a.queue.empty()
    now[0] = 120
    await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 1


async def test_answer_arriving_during_first_generation_prevents_obsolete_question(governed):
    a, m = governed
    def result(data):
        if len(m.ai.inputs) == 1:
            add_discussion(a, 1)
            return assessment(data, readiness='review', propose=True)
        return assessment(data, status='resolved', missing=[])
    m.ai = TaskModel(result)
    await m.detect(a.who, a.mid)
    assert len(m.ai.inputs) == 2 and not m.ai.review_inputs
    assert m.view(a.who, a.mid)['tracked_tasks'][0]['status'] == 'resolved'
    assert not m.view(a.who, a.mid)['interventions'] and a.queue.empty()


@pytest.mark.parametrize('missing', [['owner'], ['timing'], ['scope'], ['owner', 'timing']])
async def test_ready_assessment_with_omitted_wording_still_gets_independent_review(governed, missing):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='review', missing=missing))
    await m.detect(a.who, a.mid)
    question = m.view(a.who, a.mid)['interventions'][0]['question']
    assert len(m.ai.inputs) == len(m.ai.review_inputs) == 1
    assert ('who will take responsibility' in question) == ('owner' in missing)
    assert ('when should it be ready' in question) == ('timing' in missing)
    assert ('what work does the assignment cover' in question) == ('scope' in missing)
    assert a.queue.empty()
    p = m.view(a.who, a.mid)['interventions'][0]
    await m.review(a.who, a.mid, p['id'], Review(action='reject', revision=p['revision']))
    add_discussion(a, 1)
    await m.detect(a.who, a.mid)
    assert len(m.ai.review_inputs) == 1  # No new fallback for the rejected task.
    assert [p['status'] for p in m.view(a.who, a.mid)['interventions']] == ['rejected']


async def test_omitted_wording_fallback_cannot_bypass_semantic_review(governed):
    a, m = governed
    class Hold(TaskModel):
        async def json_call(self, prompt, data, fast=False):
            result = await super().json_call(prompt, data, fast=fast)
            if 'task_candidates' in data:
                result['checks'][0].update(ready=False, reason='The information has already been supplied.')
            return result
    m.ai = Hold(lambda data: assessment(data, readiness='review'))
    await m.detect(a.who, a.mid)
    assert len(m.ai.review_inputs) == 1
    assert not m.view(a.who, a.mid)['interventions'] and a.queue.empty()


async def test_fallback_refreshes_saved_question_to_only_remaining_gap(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='review'))
    await m.detect(a.who, a.mid)
    original = m.view(a.who, a.mid)['interventions'][0]
    await m.review(a.who, a.mid, original['id'], Review(action='defer', revision=1))
    add_discussion(a, 1)
    m.ai.result = lambda data: assessment(data, readiness='review', missing=['timing'])
    await m.detect(a.who, a.mid)
    queue = m.view(a.who, a.mid)['interventions']
    assert len(queue) == 1 and queue[0]['id'] == original['id']
    assert queue[0]['status'] == 'deferred' and queue[0]['revision'] > original['revision']
    assert 'when should it be ready' in queue[0]['question']
    assert 'who will take responsibility' not in queue[0]['question']
    assert len(m.ai.review_inputs) == 2 and a.queue.empty()


async def test_waiting_task_survives_reload_and_long_discussion_without_visible_reminder(governed, client):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, propose=True))  # Guard even an over-eager model.
    await m.detect(a.who, a.mid, incremental=True)
    view = m.view(a.who, a.mid)
    tid = view['tracked_tasks'][0]['id']
    assert not view['interventions'] and a.queue.empty()
    assert view['intervention_progress']['last_check']['held_reminders'][0]['reason'] == 'waiting_for_context'
    await m.detect(a.who, a.mid, incremental=True)
    assert len(m.ai.inputs) == 1  # No immediate duplicate call before the grace window.
    reopened = db.Store(a.settings.database_url)
    try:
        with reopened.scope(a.who) as r:
            assert r.get(db.meeting_task_gaps, tid)['assessment']['missing'] == ['owner', 'timing']
    finally:
        reopened.close()
    m.checked_units.clear()
    m.awaiting_evidence.clear()
    for i in range(45):
        add_discussion(a, i + 1)
    m.ai.result = lambda data: assessment(data, readiness='boundary', propose=True)
    await m.detect(a.who, a.mid, incremental=True)
    assert m.ai.inputs[-1]['tracked_tasks'][0]['id'] == tid
    assert any('launch checklist' in r['content'] for r in m.ai.inputs[-1]['records'])
    view = m.view(a.who, a.mid)
    assert len(view['tracked_tasks']) == len(view['interventions']) == 1
    assert view['interventions'][0]['state']['task_ids'] == [tid]
    assert a.queue.empty()  # Private reminder still needs host approval.
    assert client.get(f'/api/meetings/{a.mid}/export').json()['tracked_tasks'][0]['id'] == tid


async def test_natural_assignment_closes_waiting_task_without_creating_a_reminder(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data))
    await m.detect(a.who, a.mid)
    with a.store.scope(a.who) as r:
        r.add(db.utterances, meeting_id=a.mid, recording_id=None, speaker='Unidentified speaker',
              content='I will take the checklist and finish it before the release.', start_ms=4000, end_ms=5000)
    m.ai.result = lambda data: assessment(data, status='resolved', missing=[])
    await m.detect(a.who, a.mid, incremental=True)
    view = m.view(a.who, a.mid)
    assert view['tracked_tasks'][0]['status'] == 'resolved'
    assert not view['interventions']


@pytest.mark.parametrize('action', ['reject', 'defer'])
async def test_human_disposition_prevents_paraphrased_repeated_task_reminders(governed, action):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    p = m.view(a.who, a.mid)['interventions'][0]
    await m.review(a.who, a.mid, p['id'], Review(action=action, revision=p['revision']))
    add_discussion(a, 1)
    def paraphrase(data):
        result = assessment(data, readiness='boundary', propose=True)
        result['proposals'][0]['question'] = 'Can someone clarify responsibility and delivery timing for this work?'
        return result
    m.ai.result = paraphrase
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(view['interventions']) == 1
    assert view['intervention_progress']['last_check']['held_reminders'][0]['reason'] == 'already_reminded'


async def test_distinct_tasks_enter_queue_while_another_reminder_is_pending(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    add_discussion(a, 1)
    m.ai.result = lambda data: assessment(data, readiness='boundary', propose=True,
                                         ref='new:support', task='Prepare the support handover')
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(view['tracked_tasks']) == len(view['interventions']) == 2
    assert not view['intervention_progress']['last_check']['held_reminders']
    tid = next(t['id'] for t in view['tracked_tasks'] if t['task'] == 'Prepare the support handover')
    add_discussion(a, 2)
    m.ai.result = lambda data: assessment(data, readiness='blocking', propose=False,
                                         ref=tid, task='Prepare the support handover')
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(view['interventions']) == 2
    assert next(p for p in view['interventions'] if tid in p['state']['task_ids'])['state']['task_priority'] == 'blocking'


async def test_dismissed_question_does_not_delay_a_different_task(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    p = m.view(a.who, a.mid)['interventions'][0]
    await m.review(a.who, a.mid, p['id'], Review(action='reject', revision=1))
    add_discussion(a, 1)
    m.checked_units.clear()
    m.ai.result = lambda data: assessment(data, readiness='boundary', propose=True,
                                         ref='new:other', task='Prepare a separate deliverable')
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(view['interventions']) == 2
    assert not view['intervention_progress']['last_check']['held_reminders']
    other = next(t for t in view['tracked_tasks'] if t['id'] != p['state']['task_ids'][0])
    add_discussion(a, 2)
    m.ai.result = lambda data: assessment(data, readiness='boundary', propose=True,
                                         ref=other['id'], task=other['task'])
    await m.detect(a.who, a.mid)
    assert len(m.view(a.who, a.mid)['interventions']) == 2


async def test_resolved_task_withdraws_visible_question_but_keeps_review_history(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    p = m.view(a.who, a.mid)['interventions'][0]
    await m.review(a.who, a.mid, p['id'], Review(action='defer', revision=1))
    add_discussion(a, 1)
    m.ai.result = lambda data: assessment(data, status='resolved', missing=[])
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert view['interventions'][0]['status'] == 'stale'
    assert view['intervention_reviews'][0]['action'] == 'defer'


async def test_partial_answer_withdraws_question_that_still_asks_for_known_owner(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    add_discussion(a, 1)
    m.ai.result = lambda data: assessment(data, missing=['timing'])
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert view['interventions'][0]['status'] == 'stale'
    assert view['tracked_tasks'][0]['missing'] == ['timing']


@pytest.mark.parametrize('deferred', [False, True])
@pytest.mark.parametrize('intermediate', ['direct', 'waiting', 'corrected'])
async def test_remaining_gap_refreshes_same_queue_item_and_preserves_deferral(governed, deferred, intermediate):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    original = m.view(a.who, a.mid)['interventions'][0]
    if deferred:
        await m.review(a.who, a.mid, original['id'], Review(action='defer', revision=1))
    add_discussion(a, 1)
    if intermediate == 'corrected':
        with a.store.scope(a.who) as r:
            r.change(db.utterances, original['evidence'][0]['utterance_id'],
                     content='Alice owns the checklist. Delivery timing is still undecided.')
        assert m.view(a.who, a.mid)['interventions'][0]['status'] == 'stale'
    if intermediate == 'waiting':
        m.ai.result = lambda data: assessment(data, missing=['timing'])
        await m.detect(a.who, a.mid)
        assert m.view(a.who, a.mid)['interventions'][0]['status'] == 'stale'
        add_discussion(a, 2)
    def remaining(data):
        result = assessment(data, missing=['timing'], readiness='boundary', propose=True)
        result['proposals'][0]['question'] = 'When will the checklist be ready?'
        return result
    m.ai.result = remaining
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(view['interventions']) == 1
    updated = view['interventions'][0]
    assert updated['id'] == original['id'] and updated['revision'] > original['revision']
    assert updated['question'] == 'When will the checklist be ready?'
    assert updated['status'] == ('deferred' if deferred else 'proposed')
    assert list(updated['state']['task_missing'].values()) == [['timing']]
    assert view['intervention_reviews'][-1]['action'] == 'refresh'
    assert view['intervention_reviews'][-1]['before']['question'] == original['question']
    assert a.queue.empty()


async def test_several_distinct_tasks_with_shared_evidence_are_not_truncated(governed):
    a, m = governed
    def result(data):
        tasks = [assessment(data, readiness='blocking' if i == 3 else 'boundary', propose=True,
                            ref=f'new:task{i}', task=f'Deliverable {i}') for i in range(4)]
        return {'task_updates': [t['task_updates'][0] for t in tasks],
                'proposals': [t['proposals'][0] for t in tasks]}
    m.ai = TaskModel(result)
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(view['interventions']) == len(view['tracked_tasks']) == 4
    assert len(m.ai.review_inputs) == 1
    assert len(m.ai.review_inputs[0]['task_candidates']) == 4
    assert view['interventions'][0]['state']['task_priority'] == 'blocking'
    assert a.queue.empty()


async def test_material_change_updates_saved_item_instead_of_adding_a_duplicate(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    p = m.view(a.who, a.mid)['interventions'][0]
    await m.review(a.who, a.mid, p['id'], Review(action='defer', revision=1))
    add_discussion(a, 1)
    def changed(data):
        result = assessment(data, readiness='boundary', propose=True, material_change=True)
        result['proposals'][0]['question'] = 'Who can own the expanded checklist and confirm its new delivery plan?'
        return result
    m.ai.result = changed
    await m.detect(a.who, a.mid)
    queue = m.view(a.who, a.mid)['interventions']
    assert len(queue) == 1 and queue[0]['id'] == p['id'] and queue[0]['status'] == 'deferred'
    assert queue[0]['question'].startswith('Who can own the expanded checklist')


async def test_host_handling_rechecks_unqueued_tasks_once_without_new_speech(governed):
    a, m = governed
    m.quiet_seconds, m.min_interval, m.delay = 0, 0, .001
    def result(data):
        first = assessment(data, readiness='boundary', propose=True)
        second = assessment(data, readiness='boundary', ref='new:handover', task='Support handover')
        return {**first, 'task_updates': first['task_updates'] + second['task_updates']}
    m.ai = TaskModel(result)
    await m.detect(a.who, a.mid)
    key = a.who, a.mid
    m.processed[key] = m.snapshot(*key)[3]
    view = m.view(*key)
    other = next(t for t in view['tracked_tasks'] if t['task'] == 'Support handover')
    # Simulate a ready task saved by the older pipeline without a queue item.
    with a.store.scope(a.who) as r:
        for queued in view['interventions']:
            if other['id'] in queued['state']['task_ids']:
                r.remove(db.meeting_interventions, queued['id'])
    m.ai.result = lambda data: assessment(data, readiness='boundary', propose=True, ref=other['id'], task=other['task'])
    p = view['interventions'][0]
    await m.review(*key, p['id'], Review(action='reject', revision=1))
    from test_meeting_interventions import wait_until
    await wait_until(lambda: key not in m.tasks)
    assert len(m.ai.inputs) == 2
    assert m.ai.inputs[-1]['reassess_pending'] is True
    assert m.ai.inputs[-1]['new_record_ids'] == []
    assert [p['status'] for p in m.view(*key)['interventions']] == ['rejected', 'proposed']
    assert key not in m.pending_reassessment


async def test_dismissed_task_reopens_only_for_material_change_with_new_evidence(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    p = m.view(a.who, a.mid)['interventions'][0]
    await m.review(a.who, a.mid, p['id'], Review(action='reject', revision=1))
    m.ai.result = lambda data: assessment(data, readiness='boundary', propose=True, material_change=True)
    await m.detect(a.who, a.mid)
    assert len(m.view(a.who, a.mid)['interventions']) == 1
    with a.store.scope(a.who) as r:
        r.add(db.utterances, meeting_id=a.mid, recording_id=None, speaker='Alice',
              content='The external review was moved to tomorrow; we must now finish the checklist tonight.',
              start_ms=5000, end_ms=6000)
    def changed(data):
        result = assessment(data, readiness='boundary', propose=True, material_change=True)
        result['proposals'][0]['question'] = 'Who can take the checklist for the newly advanced review?'
        return result
    m.ai.result = changed
    await m.detect(a.who, a.mid)
    assert len(m.view(a.who, a.mid)['interventions']) == 2


async def test_task_reminder_slot_does_not_suppress_independent_contradiction(governed):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    add_discussion(a, 1)
    def result(data):
        value = assessment(data, readiness='boundary', propose=True, ref='new:other', task='Another task')
        contradiction = {**value['proposals'][0], 'kind': 'contradiction', 'task_refs': [],
                         'question': 'Which delivery commitment is current?'}
        value['proposals'].append(contradiction)
        return value
    m.ai.result = result
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert [p['kind'] for p in view['interventions']] == ['missing_detail', 'missing_detail', 'contradiction']


async def test_multiple_ready_tasks_in_same_pass_are_all_queued(governed):
    a, m = governed
    def result(data):
        first = assessment(data, readiness='boundary', propose=True)
        second = assessment(data, readiness='boundary', propose=True, ref='new:other', task='Another task')
        return {'task_updates': first['task_updates'] + second['task_updates'],
                'proposals': first['proposals'] + second['proposals'], 'resolved_ids': []}
    m.ai = TaskModel(result)
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(view['tracked_tasks']) == len(view['interventions']) == 2
    assert not view['intervention_progress']['last_check']['held_reminders']


async def test_independent_review_holds_a_premature_draft(governed):
    a, m = governed
    class Reviewed(TaskModel):
        async def json_call(self, prompt, data, fast=False):
            result = await super().json_call(prompt, data, fast=fast)
            if 'task_candidates' in data:
                result['checks'][0].update(ready=False, reason='The group is still allocating the related deliverables.')
            return result
    m.ai = Reviewed(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert not view['interventions']
    assert view['tracked_tasks'][0]['readiness'] == 'wait'
    assert view['intervention_progress']['last_check']['model_calls'] == 2


async def test_review_matches_legacy_dismissal_and_preserves_that_association(governed):
    a, m = governed
    await m.detect(a.who, a.mid)  # Legacy suggestion without a task ID.
    p = m.view(a.who, a.mid)['interventions'][0]
    await m.review(a.who, a.mid, p['id'], Review(action='reject', revision=1))
    class LegacyMatch(TaskModel):
        async def json_call(self, prompt, data, fast=False):
            result = await super().json_call(prompt, data, fast=fast)
            if 'task_candidates' in data:
                result['checks'][0]['same_issue_ids'] = [p['id']]
            return result
    m.ai = LegacyMatch(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(view['interventions']) == 1
    assert view['tracked_tasks'][0]['related_proposal_ids'] == [p['id']]
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    add_discussion(a, 1)
    await m.detect(a.who, a.mid)
    assert len(m.view(a.who, a.mid)['interventions']) == 1


@pytest.mark.parametrize('limit', [3, 6])
async def test_task_publication_reserves_generation_and_review_budget(governed, limit):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    now = [40.0]
    m.clock, m.quiet_seconds, m.background_call_limit = lambda: now[0], 0, limit
    key = a.who, a.mid
    m.background_calls[key].extend([0] * (limit - 1))
    for second in (40, 50, 59):
        now[0] = second
        assert await m.detect(*key, incremental=True, scheduled=True) == 'scheduled'
    assert not m.ai.inputs and not m.ai.review_inputs
    assert not m.view(a.who, a.mid)['interventions']
    assert key not in m.checked_units
    now[0] = 60
    await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == len(m.ai.review_inputs) == 1
    assert len(m.view(*key)['interventions']) == 1
    assert len(m.background_calls[key]) == 2


async def deferred_task(governed, limit=3):
    """An append-only task reassessment uses the slot intended for review."""
    a, m = governed
    now = [40.0]
    m.clock, m.quiet_seconds, m.background_call_limit = lambda: now[0], 0, limit
    def result(data):
        if len(m.ai.inputs) == 1:
            add_discussion(a, 1)
        return assessment(data, readiness='boundary', propose=True)
    m.ai = TaskModel(result)
    m.background_calls[a.who, a.mid].extend([0] * (limit - 2))
    assert await m.detect(a.who, a.mid, incremental=True, scheduled=True) == 'scheduled'
    assert len(m.ai.inputs) == 2 and not m.ai.review_inputs
    view = m.view(a.who, a.mid)
    assert not view['interventions'] and not view['tracked_tasks']
    assert view['intervention_progress']['last_check']['draft_retained'] is True
    return now


@pytest.mark.parametrize('limit', [3, 6])
async def test_budget_deferred_task_resumes_review_without_regeneration(governed, limit):
    a, m = governed
    now = await deferred_task(governed, limit)
    key = a.who, a.mid
    for second in (41, 50, 59):
        now[0] = second
        assert await m.detect(*key, incremental=True, scheduled=True) == 'scheduled'
        assert len(m.ai.inputs) == 2 and not m.ai.review_inputs
        assert key not in m.checked_units
    now[0] = 60
    await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 2 and len(m.ai.review_inputs) == 1
    assert key not in m.pending_drafts
    assert len(m.background_calls[key]) <= limit
    view = m.view(*key)
    assert len(view['interventions']) == len(view['tracked_tasks']) == 1
    check = view['intervention_progress']['last_check']
    assert check['resumed_draft'] is True and check['model_calls'] == 1
    now[0] = 100
    await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 2 and len(m.ai.review_inputs) == 1
    assert a.queue.empty()  # Review does not authorize speech.


@pytest.mark.parametrize('resolved', [False, True])
async def test_pending_task_rechecks_new_speech_before_review(governed, resolved):
    a, m = governed
    now = await deferred_task(governed)
    key = a.who, a.mid
    add_discussion(a, 2)
    m.ai.result = lambda data: assessment(data, status='resolved', missing=[]) if resolved else assessment(data, readiness='boundary', propose=True)
    now[0] = 60  # Only one call is available: reassess the appended speech.
    result = await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 3 and not m.ai.review_inputs
    assert len(m.ai.inputs[-1]['records']) == 4
    assert not m.view(*key)['interventions']
    if resolved:
        assert key not in m.pending_drafts
        assert m.view(*key)['tracked_tasks'][0]['status'] == 'resolved'
    else:
        assert result == 'scheduled' and key in m.pending_drafts
        now[0] = 100
        await m.detect(*key, incremental=True, scheduled=True)
        assert len(m.ai.inputs) == 3 and len(m.ai.review_inputs) == 1
        assert len(m.ai.review_inputs[0]['records']) == 4
        assert len(m.view(*key)['interventions']) == 1


@pytest.mark.parametrize('change', ['corrected', 'deleted', 'reviewed', 'expired', 'manual'])
async def test_stale_pending_drafts_are_invalidated(governed, change):
    a, m = governed
    now = await deferred_task(governed)
    key = a.who, a.mid
    if change in {'corrected', 'deleted'}:
        uid = m.snapshot(*key)[1][0]['id']
        with a.store.scope(a.who) as r:
            if change == 'corrected':
                r.change(db.utterances, uid, content='The checklist is complete and no work remains.')
            else:
                r.remove(db.utterances, uid)
    elif change == 'reviewed':
        with a.store.scope(a.who) as r:
            r.add(db.meeting_interventions, meeting_id=a.mid, kind='missing_detail',
                question='Who owns the checklist?', reason='Review completed while waiting.',
                evidence=[], status='rejected', revision=2, state={'fingerprint': 'reviewed-checklist'})
    elif change == 'manual':
        m.force.add(key)
    m.ai.result = lambda data: assessment(data, status='resolved', missing=[])
    now[0] = 160 if change == 'expired' else 60
    result = await m.detect(*key, incremental=True, scheduled=True)
    assert key not in m.pending_drafts
    if change not in {'manual', 'expired'}:
        assert result == 'scheduled' and len(m.ai.inputs) == 2
        now[0] = 100  # A fresh generation must have two slots available.
        await m.detect(*key, incremental=True, scheduled=True)
    assert len(m.ai.inputs) == 3 and not m.ai.review_inputs
    assert m.view(*key)['tracked_tasks'][0]['status'] == 'resolved'
    assert all(p['status'] == 'rejected' for p in m.view(*key)['interventions'])


async def test_default_budget_supports_three_two_call_batches_per_minute(governed):
    a, m = governed
    now = [0.0]
    m.clock, m.quiet_seconds = lambda: now[0], 0
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    key = a.who, a.mid
    for i, second in enumerate((0, 20, 40, 60, 80, 100), 1):
        now[0] = second
        add_discussion(a, i)
        await m.detect(*key, incremental=True, scheduled=True)
        assert len(m.ai.inputs) == len(m.ai.review_inputs) == i
        assert len(m.background_calls[key]) <= 6
        assert key not in m.pending_drafts
    assert len(m.view(*key)['interventions']) == 1  # Extra capacity does not repeat reminders.


async def test_ended_meeting_clears_pending_draft_without_review(governed):
    a, m = governed
    now = await deferred_task(governed)
    with a.store.scope(a.who) as r:
        r.change(db.meetings, a.mid, status='ended')
    now[0] = 60
    await m.detect(a.who, a.mid, incremental=True, scheduled=True)
    assert (a.who, a.mid) not in m.pending_drafts
    assert len(m.ai.inputs) == 2 and not m.ai.review_inputs
    assert not m.view(a.who, a.mid)['interventions']


async def test_new_speech_during_publication_review_does_not_save_outdated_state(governed):
    a, m = governed
    class Concurrent(TaskModel):
        async def json_call(self, prompt, data, fast=False):
            result = await super().json_call(prompt, data, fast=fast)
            if 'task_candidates' in data:
                add_discussion(a, 1)
            return result
    m.ai = Concurrent(lambda data: assessment(data, readiness='boundary', propose=True))
    assert await m.detect(a.who, a.mid) == 'scheduled'
    view = m.view(a.who, a.mid)
    assert not view['tracked_tasks'] and not view['interventions']
    assert view['intervention_progress']['last_check']['outcome'] == 'task_context_changed'


async def test_invalid_publication_review_cannot_link_a_foreign_proposal(governed):
    a, m = governed
    class Invalid(TaskModel):
        async def json_call(self, prompt, data, fast=False):
            result = await super().json_call(prompt, data, fast=fast)
            if 'task_candidates' in data:
                result['checks'][0]['same_issue_ids'] = ['foreign-proposal']
            return result
    m.ai = Invalid(lambda data: assessment(data, readiness='boundary', propose=True))
    with pytest.raises(ValueError, match='Invalid task reminder review'):
        await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert not view['tracked_tasks'] and not view['interventions']


async def test_new_speech_during_task_check_reassesses_resolution_before_saving(governed):
    a, m = governed
    def result(data):
        if len(m.ai.inputs) == 1:
            add_discussion(a, 1)
            return assessment(data, readiness='boundary', propose=True)
        return assessment(data, status='resolved', missing=[])
    m.ai = TaskModel(result)
    await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert len(m.ai.inputs) == 2
    assert view['tracked_tasks'][0]['status'] == 'resolved' and not view['interventions']


@pytest.mark.parametrize('corruption', ['foreign_ref', 'invalid_quote', 'foreign_proposal_ref'])
async def test_invalid_tracking_output_cannot_partially_write_or_publish(governed, corruption):
    a, m = governed
    def result(data):
        value = assessment(data, readiness='boundary', propose=True)
        if corruption == 'foreign_ref':
            value['task_updates'][0]['ref'] = 'task-from-another-meeting'
        elif corruption == 'invalid_quote':
            value['task_updates'][0]['evidence'][0]['quote'] = 'Fabricated commitment'
        else:
            value['proposals'][0]['task_refs'] = ['task-from-another-meeting']
        return value
    m.ai = TaskModel(result)
    with pytest.raises(ValueError):
        await m.detect(a.who, a.mid)
    view = m.view(a.who, a.mid)
    assert not view['tracked_tasks'] and not view['interventions']


async def test_deleted_source_purges_task_memory_and_associated_suggestions(governed, client):
    a, m = governed
    m.ai = TaskModel(lambda data: assessment(data, readiness='boundary', propose=True))
    await m.detect(a.who, a.mid)
    p = m.view(a.who, a.mid)['interventions'][0]
    with a.store.scope(a.who) as r:
        purge_interventions(r, a.mid, {p['evidence'][0]['utterance_id']})
        assert not r.list(db.meeting_task_gaps) and not r.list(db.meeting_interventions)
    await m.detect(a.who, a.mid)
    a.manager.update(a.row, state='ended', desired_state='left')
    assert client.delete(f'/api/meetings/{a.mid}').status_code == 200
    with a.store.scope(a.who) as r:
        assert not r.list(db.meeting_task_gaps)
