import copy

import pytest
from fastapi.testclient import TestClient

from echooo import database as db
from echooo import meeting_minutes as rules
from test_product import app, client


def test_minutes_validate_evidence_status_and_merge():
    records = [{'id': 'a', 'content': 'We should make the repository private.'}, {'id': 'b', 'content': 'I will send the invitation tomorrow.'}]
    point = {'text': 'Make repository private', 'kind': 'decision', 'status': 'requested', 'supporting_quote': records[0]['content'], 'evidence_ids': ['a']}
    action = {'text': 'Send invitation', 'kind': 'action', 'status': 'committed', 'supporting_quote': records[1]['content'], 'evidence_ids': ['b']}
    cleaned = rules.clean_minutes({'overview': 'Collaboration planning.', 'outcomes': [point, action, {**action, 'text': 'Forged', 'supporting_quote': 'Agreed and adopted.'}, {**action, 'text': 'Foreign', 'evidence_ids': ['other']}],
        'topics': [{'title': 'Repository', 'points': [{'text': 'Proposal: private repository', 'evidence_ids': ['a']}]},
                   {'title': 'repository', 'points': [{'text': 'Proposal: private repository', 'evidence_ids': ['a']}, {'text': 'Send invitation', 'evidence_ids': ['b']}]}]}, records)
    assert [i['text'] for i in cleaned['outcomes']] == ['Send invitation']
    assert len(cleaned['topics']) == 1 and len(cleaned['topics'][0]['points']) == 1
    with pytest.raises(ValueError):
        rules.clean_minutes({'overview': '', 'outcomes': [], 'topics': []}, records)


def test_minutes_fold_correction_force_failure_and_export(client, app, monkeypatch):
    m = client.post('/api/meetings', json={'title': 'Planning'}).json()
    path = '/api/meetings/' + m['id']
    u = client.post(path + '/utterances', json={'content': 'Which repository should we use?'}).json()
    v = client.post(path + '/utterances', json={'content': 'Use our existing repository.'}).json()
    monkeypatch.setattr(rules, 'MINUTES_RECORD_LIMIT', 1)
    app.state.service.ai.settings.llm_provider = 'openai_compatible'
    inputs = []

    async def generate(prompt, data, **kwargs):
        inputs.append(copy.deepcopy(data))
        first = data['records'][0]['id'] == u['id']
        return {'overview': 'Repository planning.', 'outcomes': [{'kind': 'question', 'status': 'unresolved', 'text': 'Which repository?', 'supporting_quote': u['content'], 'evidence_ids': [u['id']]}] if first else [],
            'topics': [] if first else [{'title': 'Repository', 'points': [{'text': 'The existing repository was identified for the work.', 'evidence_ids': [v['id']]}]}]}
    app.state.service.ai.json_call = generate
    first = client.post(path + '/minutes?recording_id=notes').json()
    assert first['summary_remaining'] == 1
    final = client.post(path + '/minutes?recording_id=notes').json()
    minutes = final['minutes'][0]
    assert final['summary_remaining'] == 0 and len(final['minutes']) == 1
    assert minutes['content']['outcomes'] == []
    assert inputs[1]['previous_minutes']['outcomes'][0]['kind'] == 'question'
    assert set(minutes['evidence_ids']) == {u['id'], v['id']}
    client.post(path + '/minutes?recording_id=notes')
    assert len(inputs) == 2
    # A failed manual rebuild preserves the last usable document.
    async def invalid(*args, **kwargs):
        return {'overview': None}
    app.state.service.ai.json_call = invalid
    assert client.post(path + '/minutes?recording_id=notes&force=true').status_code == 503
    assert client.get(path).json()['minutes'] == final['minutes']
    app.state.service.ai.json_call = generate
    client.patch(path + '/utterances/' + u['id'], json={'content': 'Which repo?', 'speaker': 'Alice'})
    rebuilt = client.post(path + '/minutes?recording_id=notes').json()
    assert inputs[-1]['previous_minutes'] is None
    assert rebuilt['minutes'][0]['revision'] == 2
    assert len(rebuilt['minutes']) == 1
    assert client.patch(path, json={'title': 'Renamed planning'}).json()['title'] == 'Renamed planning'
    exported = client.get(path + '/export')
    assert exported.json()['title'] == 'Renamed planning'
    assert exported.json()['minutes'] == rebuilt['minutes']
    assert exported.headers['content-disposition'].startswith('attachment;')
    stranger = TestClient(app)
    for suffix in ('/export', ''):
        assert stranger.get(path + suffix).status_code == 401
    assert stranger.patch(path, json={'title': 'Other'}).status_code == 401
    assert stranger.post(path + '/minutes').status_code == 401


def test_minutes_recording_scope_and_cascade(client, app):
    m = client.post('/api/meetings', json={'title': 'One'}).json()
    other = client.post('/api/meetings', json={'title': 'Two'}).json()
    with app.state.store.scope(m['owner_id']) as r:
        rec = r.add(db.recordings, meeting_id=m['id'], sample_rate=16000, samples=0)
        r.add(db.utterances, meeting_id=m['id'], recording_id=rec['id'], start_ms=0, end_ms=1000, speaker='A', content='A topic.')
    path = '/api/meetings/' + m['id']
    assert client.post('/api/meetings/' + other['id'] + '/minutes?recording_id=' + rec['id']).status_code == 404
    selected = client.post(path + '/minutes?recording_id=' + rec['id']).json()
    assert selected['minutes'][0]['scope_key'] == rec['id']
    assert client.post(path + '/minutes?recording_id=notes').json()['summary_remaining'] == 0
    assert len(client.post(path + '/minutes').json()['minutes']) == 2
    assert client.delete(path + '/recordings/' + rec['id']).json()['minutes'] == []
