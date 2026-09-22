"""Recent-first direct answering, bounded retrieval and durable support outcomes."""
import asyncio
from dataclasses import replace
import threading
import time

import pytest

from echooo import database as db
from echooo import meeting_answers
from echooo.meeting_agent import MeetingAgent
from echooo.meeting_retrieval import recent_passages, search_meeting_evidence, SEARCH_CHARS, RECENT_CHARS
from test_meeting_agent import agent, app, client


def add(agent, text, *, mid=None, **extra):
    with agent.store.scope(agent.who) as r:
        return r.add(db.utterances, meeting_id=mid or agent.mid, recording_id=None,
            speaker='Alice', content=text, start_ms=0, end_ms=0, **extra)


def answer(text, citations=(), support='supported'):
    return {'action': 'answer', 'support': support, 'reply': text, 'citations': list(citations)}


async def request(agent, responses, question='Which communication platform was selected?'):
    agent.settings = replace(agent.settings, llm_provider='openai_compatible')
    calls = []
    async def model(system, context, **kwargs):
        calls.append(context)
        result = responses.pop(0)
        return result(context) if callable(result) else result
    agent.intelligence.json_call = model
    await agent.accept('test:' + str(time.monotonic_ns()), question, 'public', '')
    event = agent.queue.get_nowait()
    await agent.answer(event)
    return event, calls


def detail(agent):
    return list(meeting_answers.checks(agent.store, agent.who, agent.mid).values())[-1]


async def test_recent_answer_needs_one_model_call_and_no_search(agent, monkeypatch):
    source = add(agent, 'We selected Telegram for team communication.')
    def forbidden(*args):
        pytest.fail('Recent supported answer must not search')
    monkeypatch.setattr(meeting_answers, 'search_meeting_evidence', forbidden)
    event, calls = await request(agent, [answer('Telegram was selected.', [source['id']])])
    assert len(calls) == 1 and calls[0]['search_available']
    assert event['status'] == 'submitted'
    assert detail(agent)['support'] == 'supported' and not detail(agent)['search_used']
    assert agent.events()[-1]['citations'][0]['content'] == source['content']


async def test_search_finds_old_evidence_and_adjacent_answer_without_foreign_data(agent):
    topic = add(agent, 'Which team communication platform should we use?')
    decision = add(agent, 'We have decided on Telegram.')
    for i in range(75):
        add(agent, f'Unrelated agenda update number {i}.')
    with agent.store.scope(agent.who) as r:
        other = r.add(db.meetings, title='Other', status='active', revision=1)
    add(agent, 'PRIVATE_OTHER_MEETING communication platform.', mid=other['id'])
    await agent.accept('private', 'PRIVATE_CHAT communication platform', 'private', 'other', reply=False)
    def final(context):
        assert not context['search_available']
        assert topic['id'] not in {p['id'] for p in context['discussion']}
        retrieved = context['retrieval']['passages']
        assert {topic['id'], decision['id']} <= {p['id'] for p in retrieved}
        assert 'PRIVATE_' not in str(context)
        return answer('Telegram.', [decision['id']])
    event, calls = await request(agent, [{'action': 'search', 'queries': ['communication platform']}, final])
    assert len(calls) == 2 and event['response'] == 'Telegram.'
    assert detail(agent)['search_used'] and detail(agent)['search_ms'] >= 0


async def test_no_matches_is_insufficient_not_provider_failure_and_survives_restart(agent, client):
    event, calls = await request(agent, [{'action': 'search', 'queries': ['approved budget']},
        answer('I did not find an approved budget in the available records.', support='insufficient')])
    assert calls[-1]['retrieval']['passages'] == []
    assert detail(agent)['support'] == 'insufficient'
    restored = MeetingAgent.saved_view(agent.manager, agent.row)
    assert restored['events'][-1]['answer_check']['support'] == 'insufficient'
    restarted = MeetingAgent(agent.manager, agent.row)
    assert restarted.queue.empty()
    exported = client.get(f'/api/meetings/{agent.mid}/export').json()
    assert exported['answer_checks'][0]['event_id'] == event['id']
    assert exported['answer_checks'][0]['detail']['support'] == 'insufficient'


async def test_clarify_is_single_call_without_historical_search(agent):
    event, calls = await request(agent, [{'action': 'clarify', 'reply': 'Which project do you mean?', 'citations': []}])
    assert len(calls) == 1 and event['status'] == 'submitted'
    assert detail(agent)['action'] == 'clarify'


async def test_conflicting_evidence_is_explicit(agent):
    a = add(agent, 'We should use Telegram.')
    b = add(agent, 'I disagree; the platform is still undecided.')
    _, _ = await request(agent, [answer('The platform is still disputed.', [a['id'], b['id']], 'conflicting')])
    assert detail(agent)['support'] == 'conflicting'


@pytest.mark.parametrize('invalid', [
    {'reply': 'Telegram.', 'citations': []},
    answer('Telegram.'),
    answer('Telegram.', ['foreign-id']),
    {'action': 'search', 'queries': []},
    {'action': 'search', 'queries': ['x' * 181]},
    {'action': 'search', 'queries': ['platform'], 'meeting_id': 'other'},
    {'action': 'clarify', 'reply': 'Which one?', 'citations': ['foreign-id']},
])
async def test_invalid_contract_or_unsupported_fact_never_delivers(agent, invalid):
    with pytest.raises(ValueError):
        await request(agent, [invalid])
    assert not agent.manager.client.chats
    assert detail(agent)['support'] == 'unavailable'


async def test_second_search_is_rejected_not_looped(agent):
    with pytest.raises(ValueError, match='repeated'):
        await request(agent, [{'action': 'search', 'queries': ['platform']}] * 2)
    assert detail(agent)['model_calls'] == 2 and not agent.manager.client.chats


async def test_retrieval_error_is_unavailable_not_insufficient(agent, monkeypatch):
    def broken(*args):
        raise RuntimeError('PRIVATE_PROVIDER_DIAGNOSTIC')
    monkeypatch.setattr(meeting_answers, 'search_meeting_evidence', broken)
    with pytest.raises(RuntimeError):
        await request(agent, [{'action': 'search', 'queries': ['platform']}])
    assert detail(agent)['support'] == 'unavailable' and detail(agent)['failure'] == 'retrieval'
    assert 'PRIVATE_PROVIDER' not in str(detail(agent))
    assert not agent.manager.client.chats


async def test_search_timeout_cancels_worker_and_does_not_call_second_model(agent, monkeypatch):
    stopped = threading.Event()
    def slow(store, who, mid, queries, cancelled):
        cancelled.wait(1)
        stopped.set()
        return {'passages': [], 'matched_chunks': 0, 'searched_chunks': 0, 'truncated': False}
    monkeypatch.setattr(meeting_answers, 'search_meeting_evidence', slow)
    monkeypatch.setattr(meeting_answers, 'SEARCH_TIMEOUT', .02)
    with pytest.raises(TimeoutError):
        await request(agent, [{'action': 'search', 'queries': ['platform']}])
    await asyncio.to_thread(stopped.wait, 1)
    assert stopped.is_set()
    assert detail(agent)['model_calls'] == 1 and detail(agent)['failure'] == 'retrieval'


async def test_total_deadline_covers_model_generation(agent, monkeypatch):
    agent.settings = replace(agent.settings, llm_provider='openai_compatible')
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    agent.intelligence.json_call = slow
    monkeypatch.setattr(meeting_answers, 'ANSWER_TIMEOUT', .02)
    await agent.accept('timeout', 'What was approved?', 'public', '')
    with pytest.raises(TimeoutError):
        await agent.answer(agent.queue.get_nowait())
    assert detail(agent)['support'] == 'unavailable' and not agent.manager.client.chats


async def test_stop_cancels_pending_search_without_delivery(agent, monkeypatch):
    entered = threading.Event()
    def slow(store, who, mid, queries, cancelled):
        entered.set()
        cancelled.wait(1)
        return {'passages': [], 'matched_chunks': 0, 'searched_chunks': 0, 'truncated': False}
    monkeypatch.setattr(meeting_answers, 'search_meeting_evidence', slow)
    agent.settings = replace(agent.settings, llm_provider='openai_compatible')
    async def model(*args, **kwargs):
        return {'action': 'search', 'queries': ['platform']}
    agent.intelligence.json_call = model
    await agent.accept('voice:cancel', 'Echooo, which platform?', 'voice', '')
    work = asyncio.create_task(agent.work())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        await agent.stop()
        assert detail(agent)['failure'] == 'cancelled'
        assert agent.events()[-1]['status'] == 'interrupted'
        assert not agent.manager.client.chats
    finally:
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)


@pytest.mark.parametrize('mutation', ['edit', 'delete', 'append'])
async def test_transcript_changes_during_generation_block_delivery(agent, mutation):
    source = add(agent, 'Telegram was selected.')
    def change(context):
        with agent.store.scope(agent.who) as r:
            if mutation == 'edit':
                r.change(db.utterances, source['id'], content='No platform was selected.')
            elif mutation == 'delete':
                r.remove(db.utterances, source['id'])
        if mutation == 'append':
            add(agent, 'We have now replaced Telegram with another platform.')
        return answer('Telegram.', [source['id']])
    with pytest.raises(ValueError, match='changed'):
        await request(agent, [change])
    assert not agent.manager.client.chats


def test_search_includes_chinese_and_late_revisions_with_bounded_context(agent):
    first = add(agent, '决定采用微信作为团队沟通工具。')
    for i in range(20):
        add(agent, f'团队沟通工具讨论 {i}。')
    changed = add(agent, '团队沟通工具最终改为飞书。')
    result = search_meeting_evidence(agent.store, agent.who, agent.mid, ['沟通工具', 'communication platform'], threading.Event())
    assert changed['id'] in {p['id'] for p in result['passages']}
    assert result['searched_chunks'] >= 22
    assert sum(len(p['content']) for p in result['passages']) <= SEARCH_CHARS
    assert result['truncated']
    with agent.store.scope(agent.who) as r:
        r.remove(db.utterances, first['id'])
    refreshed = search_meeting_evidence(agent.store, agent.who, agent.mid, ['微信'], threading.Event())
    assert first['id'] not in {p['id'] for p in refreshed['passages']}


def test_search_reads_tail_of_long_passage_and_recent_context_is_bounded(agent):
    source = add(agent, ('Background discussion. ' * 400) + 'The approved launch budget is 8500 dollars.')
    for _ in range(20):
        add(agent, 'Unrelated recent discussion. ' * 100)
    result = search_meeting_evidence(agent.store, agent.who, agent.mid, ['approved launch budget'], threading.Event())
    assert any(p['id'] == source['id'] and '8500' in p['content'] for p in result['passages'])
    assert sum(len(p['content']) for p in recent_passages(agent.store, agent.who, agent.mid)) <= RECENT_CHARS


def test_recent_and_search_use_audio_time_not_repair_insertion_order(agent):
    with agent.store.scope(agent.who) as r:
        rec = r.add(db.recordings, meeting_id=agent.mid, sample_rate=16000, samples=0)
        late = r.add(db.utterances, meeting_id=agent.mid, recording_id=rec['id'], speaker='A',
            content='Later platform decision.', start_ms=2000, end_ms=3000)
        early = r.add(db.utterances, meeting_id=agent.mid, recording_id=rec['id'], speaker='A',
            content='Earlier platform proposal.', start_ms=0, end_ms=1000)
    assert [p['id'] for p in recent_passages(agent.store, agent.who, agent.mid)] == [early['id'], late['id']]
    result = search_meeting_evidence(agent.store, agent.who, agent.mid, ['platform'], threading.Event())
    assert [p['id'] for p in result['passages']] == [early['id'], late['id']]


def test_search_never_reads_another_owner_even_with_forged_meeting_id(agent):
    with agent.store.engine.begin() as c:
        c.execute(db.users.insert().values(id='other-owner', name='Other', password='unused', created_at=time.time()))
    with agent.store.scope('other-owner') as r:
        other = r.add(db.meetings, title='Private meeting', status='active', revision=1)
        r.add(db.utterances, meeting_id=other['id'], recording_id=None, speaker='B',
            content='Secret budget.', start_ms=0, end_ms=0)
    result = search_meeting_evidence(agent.store, agent.who, other['id'], ['budget'], threading.Event())
    assert result['passages'] == []


async def test_initial_insufficiency_falls_back_to_one_search_before_answering(agent):
    _, calls = await request(agent, [answer('I cannot tell from recent context.', support='insufficient'),
        answer('I did not find an approved budget in the available records.', support='insufficient')])
    assert len(calls) == 2 and not calls[-1]['search_available']
    assert detail(agent)['search_used'] and detail(agent)['support'] == 'insufficient'


def test_restart_cancels_pending_search_and_updates_audit_without_replay(agent):
    with agent.store.scope(agent.who) as r:
        event = r.add(db.meeting_agent_events, meeting_id=agent.mid, connection_id=agent.cid,
            source_key='voice:restart', audience='voice', sender='', request='Which platform?',
            response='', status='searching', error='')
        r.add(db.meeting_answer_checks, meeting_id=agent.mid, event_id=event['id'],
            detail={'support': 'pending', 'search_used': True})
    restarted = MeetingAgent(agent.manager, agent.row)
    assert restarted.queue.empty()
    assert restarted.events()[-1]['status'] == 'interrupted'
    assert detail(agent)['failure'] == 'restart' and detail(agent)['support'] == 'unavailable'


def test_total_context_budget_includes_metadata_and_keeps_retrieval():
    import json
    context = {'question': 'What happened?', 'discussion': [{'id': str(i), 'content': 'a' * 2000} for i in range(60)],
        'knowledge': [{'id': 'knowledge', 'content': 'b' * 30000}], 'recent_questions': [],
        'retrieval': {'passages': [{'id': 'old', 'content': 'Earlier evidence.'}], 'truncated': False}}
    result = meeting_answers.bounded_context(context)
    assert len(json.dumps(result, ensure_ascii=False)) <= meeting_answers.CONTEXT_CHARS
    assert result['retrieval']['passages'][0]['id'] == 'old'
    assert len(context['discussion']) == 60


async def test_meeting_deletion_cascades_answer_audit(agent, client):
    await request(agent, [{'action': 'clarify', 'reply': 'Which project?', 'citations': []}])
    assert detail(agent)
    with agent.store.scope(agent.who) as r:
        r.remove(db.meetings, agent.mid)
        assert not r.list(db.meeting_answer_checks)
