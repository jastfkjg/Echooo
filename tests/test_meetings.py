import io
import wave

from fastapi.testclient import TestClient

from echooo import database as db
from test_product import app, client


def test_meeting_evidence_review_and_correction(client):
    m = client.post('/api/meetings', json={'title': 'Launch review'}).json()
    path = '/api/meetings/' + m['id']
    ids = []
    for i in range(25):
        u = client.post(path + '/utterances', json={'speaker': 'Alice', 'content': f'Passage {i}'}).json()
        ids.append(u['id'])
    result = client.post(path + '/chapters?max_sections=3').json()
    assert len(result['sections']) == 3
    assert set(ids) == {uid for s in result['sections'] for uid in s['evidence_ids']}
    assert len(client.post(path + '/chapters').json()['sections']) == 3
    s = result['sections'][0]
    assert client.post(path + f"/sections/{s['id']}/review", json={'status':'confirmed','revision':1}).status_code == 200
    corrected = client.patch(path + '/utterances/' + ids[0], json={'speaker':'Bob','content':'Corrected statement'}).json()
    assert all(s['status'] == 'stale' for s in corrected['sections'])
    assert client.post(path + f"/sections/{s['id']}/review", json={'status':'confirmed','revision':1}).status_code == 409
    refreshed = client.post(path + '/chapters?max_sections=3').json()
    assert len([s for s in refreshed['sections'] if s['status']=='pending']) == 3
    assert client.post(path + '/end').json()['status'] == 'ended'
    assert client.post(path + '/utterances', json={'content':'Late'}).status_code == 409


def test_recording_persistence_ranges_scope_delete(client, app):
    m = client.post('/api/meetings', json={'title':'Audio test'}).json()
    path = '/api/meetings/' + m['id']
    pcm = b'\x01\x00' * 1600
    with client.websocket_connect('/ws/meetings/' + m['id']) as ws:
        assert ws.receive_json()['type'] == 'warning'
        ready = ws.receive_json()
        rid = ready['recording']['id']
        ws.send_bytes(pcm)
        assert ws.receive_json() == {'type':'saved','samples':1600}
        assert client.delete(path).status_code == 409
        ws.send_text('stop')
        assert ws.receive_json()['type'] == 'stopped'
    url = path + '/recordings/' + rid + '/audio'
    audio = client.get(url)
    assert audio.status_code == 200
    with wave.open(io.BytesIO(audio.content)) as wav:
        assert wav.getnframes() == 1600
        assert wav.readframes(1600) == pcm
    partial = client.get(url, headers={'Range':'bytes=44-63'})
    assert partial.status_code == 206 and partial.content == pcm[:20]
    assert client.get(url, headers={'Range':'bytes=999999-'}).status_code == 416
    stranger = TestClient(app)
    assert stranger.get(url).status_code == 401
    other = client.post('/api/meetings', json={'title':'Other'}).json()
    assert client.get(f"/api/meetings/{other['id']}/recordings/{rid}/audio").status_code == 404
    assert client.get('/api/export').status_code == 200
    assert client.delete(path).status_code == 200
    assert client.get(url).status_code == 404
    with app.state.store.scope(m['owner_id']) as r:
        assert r.list(db.audio_parts) == []


def test_untrusted_analysis_citations_filtered(client, app):
    m = client.post('/api/meetings', json={'title':'Evidence'}).json()
    path='/api/meetings/'+m['id']
    u=client.post(path+'/utterances',json={'content':'Maybe Friday.'}).json()
    app.state.service.ai.settings.llm_provider='openai_compatible'
    async def analyze(*args, **kwargs):
        return {'summary':'A possible date was discussed.', 'items':[
            {'kind':'action','text':'Invented','evidence_ids':['foreign']},
            {'kind':'contradiction','text':'Unsupported conflict','evidence_ids':[u['id']]},
            {'kind':'question','text':'Confirm the date','evidence_ids':[u['id']]}]}
    app.state.service.ai.json_call=analyze
    response=client.post(path+'/chapters')
    assert response.status_code==200
    assert [i['kind'] for i in response.json()['sections'][0]['items']]==['question']


def test_summary_is_bounded_text_only_and_failure_preserves_progress(client, app, monkeypatch):
    import asyncio
    m=client.post('/api/meetings',json={'title':'Incremental'}).json()
    path='/api/meetings/'+m['id']
    for i in range(13):
        client.post(path+'/utterances',json={'content':f'Statement {i}'})
    app.state.service.ai.settings.llm_provider='openai_compatible'
    calls=[]
    async def analyze(prompt, data, **kwargs):
        calls.append(data)
        assert kwargs=={'fast':True}
        assert all(set(u)=={'id','speaker','content'} for u in data['records']+data['context'])
        assert len(data['records'])<=12
        return {'summary':'A text summary.','items':[]}
    app.state.service.ai.json_call=analyze
    first=client.post(path+'/chapters').json()
    assert len(calls)==1 and first['summary_remaining']==1 and len(first['sections'])==1
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    app.state.service.ai.json_call=slow
    monkeypatch.setattr('echooo.meetings.SUMMARY_TIMEOUT',0.01)
    failed=client.post(path+'/chapters')
    assert failed.status_code==503 and 'timed out' in failed.json()['detail']
    assert len(client.get(path).json()['sections'])==1
    app.state.service.ai.json_call=analyze
    last=client.post(path+'/chapters').json()
    assert last['summary_remaining']==0 and len(last['sections'])==2
    assert len(calls[-1]['records'])==1


def test_recording_overview_is_separate_scoped_and_delete_cascades(client, app):
    m=client.post('/api/meetings',json={'title':'Two recordings'}).json()
    path='/api/meetings/'+m['id']
    recs=[]
    with app.state.store.scope(m['owner_id']) as r:
        for text in ['First recording decision.', 'Second recording only.']:
            rec=r.add(db.recordings,meeting_id=m['id'],sample_rate=16000,samples=1600)
            r.add(db.audio_parts,meeting_id=m['id'],recording_id=rec['id'],sequence=0,pcm=bytes(3200))
            u=r.add(db.utterances,meeting_id=m['id'],recording_id=rec['id'],speaker='A',content=text,start_ms=0,end_ms=100)
            recs.append((rec,u))
    for rec,u in recs:
        result=client.post(path+'/summarize',params={'recording_id':rec['id']}).json()
        overview=[s for s in result['overviews'] if s['scope_key']==rec['id']][0]
        assert overview['evidence_ids']==[u['id']]
        assert result['sections']==[]  # Summarize never creates a chapter.
    for rec,u in recs:
        result=client.post(path+'/chapters',params={'recording_id':rec['id']}).json()
        assert any(s['evidence_ids']==[u['id']] for s in result['sections'])
    other=client.post('/api/meetings',json={'title':'Other'}).json()
    assert client.post(f"/api/meetings/{other['id']}/summarize",params={'recording_id':recs[0][0]['id']}).status_code==404
    assert client.delete(f"/api/meetings/{other['id']}/recordings/{recs[0][0]['id']}").status_code==404
    result=client.delete(path+'/recordings/'+recs[0][0]['id']).json()
    assert [r['id'] for r in result['recordings']]==[recs[1][0]['id']]
    assert [u['id'] for u in result['utterances']]==[recs[1][1]['id']]
    assert len(result['overviews'])==len(result['sections'])==1
    assert client.get(path+'/recordings/'+recs[0][0]['id']+'/audio').status_code==404
    assert client.get(path+'/recordings/'+recs[1][0]['id']+'/audio').status_code==200


def test_overview_folds_all_text_and_updates_same_overview(client, app):
    m=client.post('/api/meetings',json={'title':'Long overview'}).json();path='/api/meetings/'+m['id']
    for i in range(45):client.post(path+'/utterances',json={'content':f'Test {i}'})
    app.state.service.ai.settings.llm_provider='openai_compatible';calls=[]
    async def summarize(prompt,data,**kwargs):
        calls.append(data)
        assert all(set(u)=={'id','speaker','content'} for u in data['records'])
        return {'summary':data['previous_summary']+' '+data['records'][-1]['content']}
    app.state.service.ai.json_call=summarize
    a=client.post(path+'/summarize?recording_id=notes').json()
    assert a['summary_remaining']==5 and a['overviews'][0]['status']=='building'
    b=client.post(path+'/summarize?recording_id=notes').json()
    assert b['summary_remaining']==0 and len(b['overviews'])==1 and b['sections']==[]
    assert 'Test 39' in b['overviews'][0]['summary'] and 'Test 44' in b['overviews'][0]['summary']
    assert len(b['overviews'][0]['evidence_ids'])==45
    client.post(path+'/summarize?recording_id=notes')
    assert len(calls)==2
    u=b['utterances'][0]
    client.patch(path+'/utterances/'+u['id'],json={'content':'Corrected','speaker':'B'})
    c=client.post(path+'/summarize?recording_id=notes').json()
    assert c['overviews'][-1]['revision']==2 and calls[-1]['previous_summary']==''


def test_overview_timeout_preserves_previous_and_can_resume(client, app, monkeypatch):
    import asyncio
    m=client.post('/api/meetings',json={'title':'Retry overview'}).json()
    path='/api/meetings/'+m['id']
    client.post(path+'/utterances',json={'content':'Initial decision'})
    initial=client.post(path+'/summarize?recording_id=notes').json()['overviews'][0]
    u=client.post(path+'/utterances',json={'content':'New condition'}).json()
    app.state.service.ai.settings.llm_provider='openai_compatible'
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    app.state.service.ai.json_call=slow
    monkeypatch.setattr('echooo.meetings.SUMMARY_TIMEOUT',0.01)
    failed=client.post(path+'/summarize?recording_id=notes')
    assert failed.status_code==503 and 'timed out' in failed.json()['detail']
    assert client.get(path).json()['overviews'][0]==initial
    async def resume(prompt,data,**kwargs):
        assert kwargs=={'fast':True}
        assert data['previous_summary']==initial['summary']
        assert [record['id'] for record in data['records']]==[u['id']]
        return {'summary':'Initial decision with a new condition.'}
    app.state.service.ai.json_call=resume
    result=client.post(path+'/summarize?recording_id=notes').json()
    assert result['summary_remaining']==0 and result['sections']==[]
    assert result['overviews'][0]['id']==initial['id']


def test_live_stt_speaker_timestamp_without_agent_reply(client, app, monkeypatch):
    import asyncio
    from echooo.models import STTEvent, STTEventType
    class FakeSTT:
        speaker_labels = False
        def __init__(self):
            self.queue = asyncio.Queue()
        async def connect(self):
            assert self.speaker_labels
        async def send_audio(self, pcm):
            await self.queue.put(STTEvent(type=STTEventType.FINAL, transcript='I will send the draft.',
                raw={'turn_order':1, 'speaker_label':'B', 'words':[{'start':20,'end':80}]}))
        async def events(self):
            while True:
                yield await self.queue.get()
        async def close(self):
            pass
    monkeypatch.setattr('echooo.meetings.create_stt', lambda settings: FakeSTT())
    app.state.service.ai.settings.stt_provider = 'assemblyai'
    m=client.post('/api/meetings',json={'title':'Live'}).json()
    with client.websocket_connect('/ws/meetings/'+m['id']) as ws:
        assert ws.receive_json()['type']=='ready'
        ws.send_bytes(bytes(3200))
        assert ws.receive_json()['type']=='saved'
        event=ws.receive_json()
        assert event['type']=='utterance'
        assert event['utterance']['speaker'].startswith('Speaker B')
        assert event['utterance']['start_ms']==20
        assert event['utterance']['end_ms']==80
        ws.send_text('stop')
        assert ws.receive_json()['type']=='stopped'
    result=client.get('/api/meetings/'+m['id']).json()
    assert len(result['utterances'])==1  # Repeated/formatted finals are not duplicated.
    with app.state.store.scope(m['owner_id']) as r:
        assert not r.list(db.messages)
