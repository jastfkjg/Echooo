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


def wire_ids(blocks):
    return {sid for block in blocks for turn in block['turns'] for sid in turn['source_ids']}


def detail(agent):
    return list(meeting_answers.checks(agent.store, agent.who, agent.mid).values())[-1]


async def test_recent_answer_needs_one_model_call_and_no_search(agent, monkeypatch):
    source = add(agent, 'We selected Telegram for team communication.')
    def forbidden(*args):
        pytest.fail('Recent supported answer must not search')
    monkeypatch.setattr(meeting_answers, 'search_meeting_evidence', forbidden)
    event, calls = await request(agent, [answer('Telegram was selected.', [source['id']])])
    assert len(calls) == 1 and 'retrieval' not in calls[0]
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
        assert 'search_available' not in context
        assert topic['id'] not in wire_ids(context['discussion'])
        retrieved = context['retrieval']['passages']
        assert {topic['id'], decision['id']} <= wire_ids(retrieved)
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
    assert len(calls) == 2 and 'retrieval' in calls[-1]
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
    assert len(json.dumps(meeting_answers.model_context(result), ensure_ascii=False)) <= meeting_answers.CONTEXT_CHARS
    assert result['retrieval']['passages'][0]['id'] == 'old'
    assert len(context['discussion']) == 60


async def test_meeting_deletion_cascades_answer_audit(agent, client):
    await request(agent, [{'action': 'clarify', 'reply': 'Which project?', 'citations': []}])
    assert detail(agent)
    with agent.store.scope(agent.who) as r:
        r.remove(db.meetings, agent.mid)
        assert not r.list(db.meeting_answer_checks)


async def test_trace_preserves_search_and_exact_context_without_poll_payload(agent, client):
    source = add(agent, 'We proposed replacing the reporting workflow.')
    event, calls = await request(agent, [
        answer('I need earlier evidence.', support='insufficient'),
        answer('The reporting workflow should be replaced.', [source['id']])],
        question='What reporting change was proposed?')
    exported = client.get(f'/api/meetings/{agent.mid}/export').json()
    row = exported['answer_traces'][0]
    trace = row['detail']
    assert row['event_id'] == event['id']
    assert trace['search']['queries'] == ['What reporting change was proposed?']
    assert trace['search']['trigger'] == 'insufficient_fallback'
    assert source['content'] in str(trace['search']['result']['passages'])
    assert [c['context'] for c in trace['calls']] == calls
    assert trace['calls'][0]['result']['support'] == 'insufficient'
    assert trace['calls'][1]['result']['citations'] == [source['id']]
    assert trace['calls'][1]['status'] == 'validated'
    assert 'answer_traces' not in client.get(f'/api/meetings/{agent.mid}').json()
    with agent.store.scope('another-owner') as r:
        assert not r.list(db.meeting_answer_traces)
    with agent.store.scope(agent.who) as r:
        r.remove(db.meeting_agent_events, event['id'])
        assert not r.list(db.meeting_answer_traces)


async def test_trace_keeps_invalid_model_result(agent):
    with pytest.raises(ValueError):
        await request(agent, [{'unexpected': 'invalid answer'}])
    with agent.store.scope(agent.who) as r:
        trace = r.list(db.meeting_answer_traces)[0]['detail']
    assert trace['calls'][0]['result'] == {'unexpected': 'invalid answer'}
    assert trace['calls'][0]['error_type'] == 'ValueError'
    assert trace['failure']['stage'] == 'generation'
    assert meeting_answers.JSON_CALL_TRACE.get() is None


async def test_wire_trace_keeps_actual_messages_and_unparseable_content(agent, monkeypatch):
    import json
    import httpx
    from echooo.intelligence import Intelligence, JSON_CALL_TRACE
    captured = {}
    sent = {}
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, *, headers, json):
            sent.update(json)
            return httpx.Response(200, request=httpx.Request('POST', url), json={
                'choices': [{'message': {'content': 'not valid JSON'}, 'finish_reason': 'stop'}]})
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    token = JSON_CALL_TRACE.set(lambda **values: captured.update(values))
    try:
        with pytest.raises(json.JSONDecodeError):
            await Intelligence(agent.settings).json_call('System prompt', {'question': 'A question'}, fast=True)
    finally:
        JSON_CALL_TRACE.reset(token)
    assert captured['request'] == sent
    assert json.loads(sent['messages'][1]['content']) == {'question': 'A question'}
    assert captured['response']['content'] == 'not valid JSON'
    assert 'Authorization' not in str(captured)


async def test_debug_routes_show_exact_trace_without_configuration_noise(agent, client):
    source = add(agent, 'The project started in January.')
    event, calls = await request(agent, [answer('It started in January.', [source['id']])])
    assert 'knowledge' not in calls[0]
    assert 'project' not in calls[0] and 'knowledge_status' not in calls[0]
    base = f'/api/meetings/{agent.mid}/debug'
    index = client.get(base).json()
    assert index['events'][0]['id'] == event['id']
    assert 'trace' not in index
    result = client.get(base + '/' + event['id']).json()
    assert result['trace']['calls'][0]['context'] == calls[0]
    assert result['trace']['calls'][0]['elapsed_ms'] >= 0
    other = client.post('/api/meetings', json={'title': 'Other'}).json()
    assert client.get(f"/api/meetings/{other['id']}/debug/{event['id']}").status_code == 404
    from fastapi.testclient import TestClient
    with TestClient(client.app) as anonymous:
        assert anonymous.get(base).status_code in {401, 403}


def test_runtime_diagnostics_are_bounded_and_owner_scoped():
    from echooo import meeting_debug as debug
    for i in range(debug.LIMIT + 10):
        debug.record('debug-owner', 'debug-meeting', 'stt', text=str(i))
    records = debug.snapshot('debug-owner', 'debug-meeting')
    assert len(records) == debug.LIMIT and records[0]['data']['text'] == '10'
    assert debug.snapshot('other-owner', 'debug-meeting') == []
    debug.clear('debug-owner', 'debug-meeting')
    assert not debug.snapshot('debug-owner', 'debug-meeting')


def test_model_payload_allowlist_keeps_evidence_and_conversation_separate():
    source = {'id': 'original', 'content': 'An observed fact.', 'source_hash': 'internal',
        'offset': 12, 'score': 4.5, 'selection': 'match', 'truncated': False,
        'recording_id': 'recording', 'speaker': 'Alice', 'start_ms': 10, 'end_ms': 20}
    internal = {'question': 'What happened?', 'audience': 'voice', 'discussion': [source],
        'project': 'Setting', 'goal': 'Setting', 'knowledge_status': 'No project selected.',
        'search_available': False, 'knowledge': [],
        'recent_questions': [{'question': 'Earlier question', 'reply': 'Unsupported assistant claim'}],
        'retrieval': {'passages': [source], 'searched_chunks': 300, 'matched_chunks': 9, 'truncated': True}}
    payload = meeting_answers.model_context(internal)
    assert set(payload) == {'question', 'audience', 'discussion', 'recent_questions', 'retrieval'}
    assert set(payload['retrieval']) == {'passages', 'truncated'}
    turn = payload['retrieval']['passages'][0]['turns'][0]
    assert set(turn) == {'source_ids', 'content', 'speaker', 'start_ms', 'end_ms'}
    assert turn['source_ids'] == ['original']
    assert 'Unsupported assistant claim' not in str(payload['discussion'])
    assert internal['discussion'][0]['source_hash'] == 'internal'


async def test_final_stage_has_no_search_contract_and_retains_original_citation(agent):
    source = add(agent, 'The project started in January and lasted about 4 months.')
    for i in range(70):
        add(agent, f'Unrelated scheduling discussion {i}.')
    _, calls = await request(agent, [{'action': 'search', 'queries': ['project start']},
        answer('The project started in January.', [source['id']])], question='When did the project start?')
    with agent.store.scope(agent.who) as r:
        trace = r.list(db.meeting_answer_traces)[0]['detail']
    first, final = [c['system'] for c in trace['calls']]
    assert '"action":"search"' in first
    assert '"action":"search"' not in final and 'queries' not in final
    assert 'FINAL ANSWER STAGE' in final
    assert source['id'] in wire_ids(calls[-1]['retrieval']['passages'])
    assert agent.events()[-1]['citations'][0]['content'] == source['content']


def test_fragmented_answer_is_ranked_and_returned_as_complete_turn(agent):
    with agent.store.scope(agent.who) as r:
        rec = r.add(db.recordings, meeting_id=agent.mid, sample_rate=16000, samples=0)
        texts = [('A', 'When did the project start?'), ('B', 'The'), ('B', 'project'),
            ('B', 'started in'), ('B', 'January'), ('B', 'and lasted about 4 months.')]
        rows = [r.add(db.utterances, meeting_id=agent.mid, recording_id=rec['id'],
            speaker=speaker, content=text, start_ms=i * 1000, end_ms=i * 1000 + 900)
            for i, (speaker, text) in enumerate(texts)]
    result = search_meeting_evidence(agent.store, agent.who, agent.mid, ['project start'], threading.Event())
    blocks = meeting_answers.transcript_blocks(result['passages'])
    assert len(blocks) == 1 and len(blocks[0]['turns']) == 2
    turn = blocks[0]['turns'][1]
    assert turn['content'] == 'The project started in January and lasted about 4 months.'
    assert turn['source_ids'] == [p['id'] for p in rows[1:]]
    assert result['searched_chunks'] == 2  # Complete turns, not six tiny ASR fragments.
    meeting_answers.validate_sources(agent, result['passages'])
    with agent.store.scope(agent.who) as r:
        r.change(db.utterances, rows[4]['id'], content='February')
    with pytest.raises(ValueError, match='changed'):
        meeting_answers.validate_sources(agent, result['passages'])


def test_retrieval_windows_are_bounded_and_do_not_cross_recordings_or_long_gaps(agent):
    with agent.store.scope(agent.who) as r:
        for n in range(12):
            rec = r.add(db.recordings, meeting_id=agent.mid, sample_rate=16000, samples=0)
            for i, text in enumerate(['Delivery schedule?', 'Delivery is on Tuesday.', 'Distant unrelated claim.']):
                r.add(db.utterances, meeting_id=agent.mid, recording_id=rec['id'], speaker=str(i),
                    content=text, start_ms=i * 1000 if i < 2 else 100000, end_ms=i * 1000 + 900 if i < 2 else 101000)
    result = search_meeting_evidence(agent.store, agent.who, agent.mid, ['delivery schedule'], threading.Event())
    blocks = meeting_answers.transcript_blocks(result['passages'])
    assert 1 <= len(blocks) <= 8
    assert all('Tuesday' in str(b) and 'Distant' not in str(b) for b in blocks)
    assert all(len({p['recording_id'] for p in result['passages'] if p['block'] == n}) == 1
        for n in {p['block'] for p in result['passages']})
    assert result['truncated']


def test_assistant_history_never_becomes_retrieval_evidence(agent):
    with agent.store.scope(agent.who) as r:
        r.add(db.meeting_agent_events, meeting_id=agent.mid, connection_id=agent.cid,
            source_key='historical', audience='voice', sender='', request='When did it start?',
            response='ASSISTANT_ONLY The project started in December.', status='spoken', error='')
    context = agent.context({'id': 'current', 'request': 'When?', 'audience': 'voice'})
    assert 'ASSISTANT_ONLY' in str(context['recent_questions'])
    assert not context['discussion']
    result = search_meeting_evidence(agent.store, agent.who, agent.mid, ['project started'], threading.Event())
    assert result['passages'] == []
