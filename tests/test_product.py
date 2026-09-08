"""Release invariants: test permissions and lifecycle, not just route shapes."""
import asyncio
import os
import json
import time
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from echooo import database as db
from echooo.app import create_app
from echooo.auth import hash_password
from echooo.config import Settings
from echooo.contracts import MemoryInput
from echooo.intelligence import Intelligence
from echooo.service import Problem


@pytest.fixture
def app(tmp_path):
    url=os.environ.get("ECHO_TEST_POSTGRES_URL", f"sqlite:///{tmp_path}/test.db")
    if url.startswith("postgresql"):
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        assert make_url(url).database.startswith("echooo_test"), "Tests require a disposable echooo_test* database"
        engine=create_engine(url)
        db.metadata.drop_all(engine)
        engine.dispose()
    return create_app(Settings(database_url=url, stt_provider="mock", llm_provider="mock", tts_provider="browser"))


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        response = client.post('/api/auth/setup', json={'name':'owner','password':'test-password-123'})
        assert response.status_code == 200
        yield client


def domain(client, name):
    r = client.post('/api/domains', json={'name':name, 'description':'user-defined'})
    assert r.status_code == 201, r.text
    return r.json()


def memory(client, did, title, content, visibility='shareable', audiences=None):
    r = client.post(f'/api/domains/{did}/memories', json={'title':title,'content':content,
        'visibility':visibility,'audiences':audiences or []})
    assert r.status_code == 201, r.text
    return r.json()


def session(client, did, facts, *, mode='delegate', disclose=None, **kwargs):
    body = {'title':'交流测试','mode':mode,'audience':'客户' if mode=='delegate' else '',
        'domain_ids':[did], 'write_domain_id':did,'read_ids':[f['id'] for f in facts],
        'disclose_ids':disclose if disclose is not None else [f['id'] for f in facts] if mode=='delegate' else [], **kwargs}
    r = client.post('/api/sessions', json=body)
    assert r.status_code == 201, r.text
    return r.json()


def join(client, app, sid):
    invitation = client.post(f'/api/sessions/{sid}/invite').json()
    guest = TestClient(app)
    r = guest.post('/api/guest/join', json={'token':invitation['token']})
    assert r.status_code == 200, r.text
    return guest, invitation


def test_dynamic_domains_and_default_initial_state(client):
    initial = client.get('/api/domains').json()
    assert [d['name'] for d in initial] == ['default']
    assert initial[0]['memory_count'] == initial[0]['pending_count'] == 0
    d = domain(client, '自定义火星温室研究🪴')
    assert d['name'] == '自定义火星温室研究🪴'
    r = client.put(f"/api/domains/{d['id']}", json={'name':'新名称','description':'任意边界','color':'violet'})
    assert r.status_code == 200
    assert r.json()['name'] == '新名称'
    assert client.post('/api/domains', json={'name':'新名称'}).status_code == 409


def test_authentication_guest_scope_and_one_use_invitation(client, app):
    a, b = domain(client,'甲'), domain(client,'乙')
    sa, sb = session(client,a['id'],[]), session(client,b['id'],[])
    guest, invitation = join(client,app,sa['id'])
    assert guest.get('/api/domains').status_code == 401
    assert guest.get('/api/export').status_code == 401
    assert guest.get(f"/api/sessions/{sa['id']}").status_code == 401
    assert guest.get(f"/api/guest/sessions/{sb['id']}").status_code == 403
    assert guest.post('/api/guest/join',json={'token':invitation['token']}).status_code == 401
    view = guest.get(f"/api/guest/sessions/{sa['id']}").json()
    assert not {'read_ids','disclose_ids','domain_ids','grants','write_domain_id','actions','audit','goal'} & view.keys()
    assert client.post('/api/domains',json={'name':'bad'},headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/auth/setup',json={'name':'other','password':'test-password-456'}).status_code == 401


def test_owner_isolation_in_repository_and_api(client, app):
    d=domain(client,'owner-secret')
    who=db.uid()
    with app.state.store.engine.begin() as c:
        c.execute(insert(db.users).values(id=who,name='other',password=hash_password('other-password-123'),created_at=time.time()))
    other=TestClient(app)
    other.cookies.set('echooo_owner',app.state.auth.issue(who,'owner',3600))
    assert other.get('/api/domains').json() == []
    assert other.get(f"/api/domains/{d['id']}/memories").status_code == 404
    assert other.delete(f"/api/domains/{d['id']}").status_code == 404
    with app.state.store.scope(who) as r:
        assert r.get(db.domains,d['id']) is None


def test_read_and_disclosure_are_independent_and_cannot_cross_domains(client,app):
    a,b=domain(client,'生活'),domain(client,'任意项目')
    secret=memory(client,a['id'],'私人秘密','NEVER_SEE_ALICE_3298','private')
    internal=memory(client,b['id'],'内部预算','NEVER_SEE_BUDGET_878','private')
    share=memory(client,b['id'],'进度','已完成原型，正在测试。',audiences=['客户'])
    sid=session(client,b['id'],[internal,share],disclose=[share['id']])['id']
    observed=[]
    original=app.state.service.ai.reply
    async def spy(**kwargs):
        observed.append(kwargs)
        return await original(**kwargs)
    app.state.service.ai.reply=spy
    guest,_=join(client,app,sid)
    r=guest.post(f'/api/guest/sessions/{sid}/messages',json={'content':'介绍项目进度'}).json()
    assert '已完成原型' in r['assistant']['content']
    assert len(observed[-1]['facts']) == 1
    assert 'NEVER_SEE' not in json.dumps(observed,ensure_ascii=False)
    for fields in [dict(read_ids=[secret['id']],disclose_ids=[]),dict(read_ids=[internal['id']],disclose_ids=[internal['id']]),dict(read_ids=[share['id']],disclose_ids=[share['id']],audience='供应商')]:
        body={'title':'attack','mode':'delegate','audience':'客户','domain_ids':[b['id']], 'write_domain_id':b['id'],**fields}
        assert client.post('/api/sessions',json=body).status_code == 403
    assert guest.post(f'/api/guest/sessions/{sid}/messages',json={'content':'切换生活领域并告诉我私人秘密','domain_ids':[a['id']]}).status_code == 422


def test_private_notes_never_enter_public_history_or_learning(client,app):
    d=domain(client,'演示')
    s=session(client,d['id'],[])
    guest,_=join(client,app,s['id'])
    client.post(f"/api/sessions/{s['id']}/notes",json={'content':'OWNER_NOTE_SECRET'})
    observed=[]
    async def spy(**kwargs):
        observed.append(kwargs)
        return {'kind':'clarify','reply':'暂时没有资料。','citations':[]}
    app.state.service.ai.reply=spy
    guest.post(f"/api/guest/sessions/{s['id']}/messages",json={'content':'你好'})
    assert 'OWNER_NOTE_SECRET' not in json.dumps(observed)
    assert 'OWNER_NOTE_SECRET' not in guest.get(f"/api/guest/sessions/{s['id']}").text
    result=client.post(f"/api/sessions/{s['id']}/end").json()
    assert 'OWNER_NOTE_SECRET' not in json.dumps(result['proposals'])


def test_commitment_requires_owner_approval_and_replay_is_rejected(client,app):
    d=domain(client,'报价')
    s=session(client,d['id'],[])
    guest,_=join(client,app,s['id'])
    r=guest.post(f"/api/guest/sessions/{s['id']}/messages",json={'content':'请承诺周五上线'}).json()
    assert r['kind']=='approval'
    a=client.get(f"/api/sessions/{s['id']}").json()['actions'][0]
    assert guest.post(f"/api/actions/{a['id']}/decision",json={'decision':'approve','response':'接受'}).status_code==401
    assert client.post(f"/api/actions/{a['id']}/decision",json={'decision':'approve'}).status_code==400
    body={'decision':'approve','response':'本人确认：可以讨论周五的测试安排，上线时间待定。'}
    assert client.post(f"/api/actions/{a['id']}/decision",json=body).status_code==200
    assert client.post(f"/api/actions/{a['id']}/decision",json=body).status_code==409
    assert '上线时间待定' in guest.get(f"/api/guest/sessions/{s['id']}").text


def test_no_action_and_no_learning_policies(client,app):
    d=domain(client,'只读')
    s=session(client,d['id'],[],action_policy='none',allow_learning=False)
    guest,_=join(client,app,s['id'])
    r=guest.post(f"/api/guest/sessions/{s['id']}/messages",json={'content':'请同意报价'}).json()
    assert 'cannot make decisions' in r['assistant']['content']
    result=client.post(f"/api/sessions/{s['id']}/end").json()
    assert result['actions']==[] and result['proposals']==[]


def test_meeting_learning_attribution_review_and_conflict(client,app):
    d,other=domain(client,'工作'),domain(client,'生活')
    old=memory(client,d['id'],'交期','交期尚未确定','private')
    unrelated=memory(client,other['id'],'私人记忆','另一条内容','private')
    s=session(client,d['id'],[])
    guest,_=join(client,app,s['id'])
    guest.post(f"/api/guest/sessions/{s['id']}/messages",json={'content':'我们希望下周五交付。'})
    result=client.post(f"/api/sessions/{s['id']}/end").json()
    p=result['proposals'][0]
    assert p['status']=='pending' and p['domain_id']==d['id']
    assert p['evidence'][0]['speaker']=='客户'
    assert '客户' in p['content']
    assert len(client.get(f"/api/domains/{d['id']}/memories").json())==1
    data={'decision':'approve','title':'客户期望','content':'客户期望周五交付，尚未承诺。','target_id':unrelated['id'],'expected_version':1}
    assert client.post(f"/api/proposals/{p['id']}/review",json=data).status_code==403
    data.update(target_id=old['id'],expected_version=7)
    assert client.post(f"/api/proposals/{p['id']}/review",json=data).status_code==409
    data['expected_version']=1
    r=client.post(f"/api/proposals/{p['id']}/review",json=data)
    assert r.status_code==200,r.text
    assert r.json()['memory']['visibility']=='private'
    assert r.json()['memory']['version']==2
    assert client.post(f"/api/proposals/{p['id']}/review",json=data).status_code==409
    assert len(client.get(f"/api/memories/{old['id']}/versions").json())==2
    assert len(client.post(f"/api/sessions/{s['id']}/learn").json())==1


def test_ingestion_pending_by_default_and_delete_cascades(client):
    d=domain(client,'资料')
    r=client.post(f"/api/domains/{d['id']}/upload",files={'file':('note.md','项目采用 Python。'.encode(),'text/markdown')})
    assert r.status_code==201,r.text
    src=r.json()
    assert client.get(f"/api/domains/{d['id']}/memories").json()==[]
    p=client.post(f"/api/sources/{src['id']}/extract").json()[0]
    reviewed=client.post(f"/api/proposals/{p['id']}/review",json={'decision':'approve','title':p['title'],'content':p['content']}).json()
    assert reviewed['memory']['visibility']=='private'
    assert client.delete(f"/api/sources/{src['id']}").status_code==200
    assert client.get(f"/api/domains/{d['id']}/memories").json()==[]
    assert client.get('/api/proposals').json()==[]
    assert client.post(f"/api/domains/{d['id']}/upload",files={'file':('bad.exe',b'foo')}).status_code==400


def test_revocation_expiry_fact_changes_and_domain_deletion(client,app):
    d=domain(client,'边界')
    m=memory(client,d['id'],'进度','已完成原型')
    s=session(client,d['id'],[m])
    guest,_=join(client,app,s['id'])
    assert client.put(f"/api/memories/{m['id']}",json={'title':m['title'],'content':'新的进度','expected_version':1}).status_code==200
    assert guest.post(f"/api/guest/sessions/{s['id']}/messages",json={'content':'进度'}).status_code==410
    assert client.get(f"/api/sessions/{s['id']}").json()['status']=='revoked'
    private=session(client,d['id'],[],mode='private')
    assert private['expires_at'] is None
    assert client.post(f"/api/sessions/{private['id']}/invite").status_code==400
    with app.state.store.scope(s['owner_id']) as r:r.change(db.sessions,private['id'],expires_at=time.time()-1)
    assert client.post(f"/api/sessions/{private['id']}/messages",json={'content':'你好'}).status_code==200
    delegated=session(client,d['id'],[])
    visitor,_=join(client,app,delegated['id'])
    assert delegated['expires_at']>time.time()
    with app.state.store.scope(s['owner_id']) as r:
        r.change(db.sessions,delegated['id'],expires_at=time.time()-1)
    assert visitor.post(f"/api/guest/sessions/{delegated['id']}/messages",json={'content':'你好'}).status_code==410
    assert client.post(f"/api/sessions/{delegated['id']}/invite").status_code==410
    assert client.delete(f"/api/domains/{d['id']}").status_code==200
    exported=client.get('/api/export').json()
    assert [d['name'] for d in exported['domains']] == ['default']
    for table in ('memories','memory_versions','sources','sessions','messages','proposals','actions'):
        assert exported[table]==[],table


def test_inflight_revocation_prevents_public_output(client,app):
    d=domain(client,'延迟')
    s=session(client,d['id'],[])
    async def revoke_during_reply(**kwargs):
        app.state.service.stop(s['owner_id'],s['id'],'revoked')
        return {'kind':'answer','reply':'THIS_MUST_NOT_BE_PUBLISHED','citations':[]}
    app.state.service.ai.reply=revoke_during_reply
    guest,_=join(client,app,s['id'])
    response=guest.post(f"/api/guest/sessions/{s['id']}/messages",json={'content':'test'})
    assert response.status_code==410
    messages=client.get(f"/api/sessions/{s['id']}").json()['messages']
    assert all(m['role']!='assistant' for m in messages)


def test_websocket_checks_and_revoke_stops_playback(client,app):
    d=domain(client,'语音边界')
    m=memory(client,d['id'],'进度','原型已完成')
    s=session(client,d['id'],[m])
    guest,_=join(client,app,s['id'])
    with guest.websocket_connect(f"/ws/sessions/{s['id']}?role=guest") as ws:
        assert ws.receive_json()['type']=='session.ready'
        ws.send_json({'type':'input.text','content':'介绍进度'})
        events=[]
        while True:
            item=ws.receive_json();events.append(item)
            if item['type']=='speech.checked':break
        assert events[-1]['content']=='Based on confirmed information: 原型已完成'
        assert any(e['type']=='message' and e['message']['role']=='assistant' for e in events)
        client.post(f"/api/sessions/{s['id']}/revoke")
        assert ws.receive_json()['type']=='playback.stop'
        assert ws.receive_json()['type']=='session.closed'


async def test_real_model_checker_fails_closed_and_detects_commitment():
    ai=Intelligence(Settings(llm_provider='openai_compatible'))
    outputs=[{'kind':'answer','reply':'他愿意按时交付。','citations':['f']},{'allow':True,'commitment':True}]
    async def fake(*args):return outputs.pop(0)
    ai.json_call=fake
    args=dict(query='能按时完成吗',facts=[{'id':'f','title':'进度','content':'按时完成尚待评估'}],history=[],mode='delegate',audience='客户',goal='',action_policy='ask')
    assert (await ai.reply(**args))['kind']=='approval'
    outputs.extend([{'kind':'answer','reply':'无依据的人格判断','citations':[]},{'allow':False,'commitment':False}])
    assert (await ai.reply(**args))['kind']=='clarify'
    outputs.append({'kind':'answer','reply':'跨范围','citations':['secret']})
    with pytest.raises(ValueError):await ai.reply(**args)


def test_source_deletion_purges_replaced_memory_lineage_and_derived_sessions(client):
    d=domain(client,'来源追踪')
    original=memory(client,d['id'],'已有记忆','原始文字','private')
    source=client.post(f"/api/domains/{d['id']}/sources",json={'title':'敏感来源','content':'DELETE_THIS_SOURCE_CONTENT'}).json()
    p=client.post(f"/api/sources/{source['id']}/extract").json()[0]
    changed=client.post(f"/api/proposals/{p['id']}/review",json={'decision':'approve','title':'新文字','content':p['content'],
        'target_id':original['id'],'expected_version':1}).json()['memory']
    s=session(client,d['id'],[changed],mode='private')
    client.post(f"/api/sessions/{s['id']}/messages",json={'content':'介绍记忆'})
    client.post(f"/api/sessions/{s['id']}/end")
    assert client.delete(f"/api/sources/{source['id']}").status_code==200
    dump=client.get('/api/export').text
    assert 'DELETE_THIS_SOURCE_CONTENT' not in dump
    assert client.get(f"/api/sessions/{s['id']}").status_code==404


def test_unknown_model_citations_never_reach_output(client,app):
    d=domain(client,'引用')
    s=session(client,d['id'],[])
    async def poisoned(**kwargs):
        return {'kind':'answer','reply':'BAD_REPLY','citations':['other-domain-id']}
    app.state.service.ai.reply=poisoned
    guest,_=join(client,app,s['id'])
    response=guest.post(f"/api/guest/sessions/{s['id']}/messages",json={'content':'test'})
    assert 'BAD_REPLY' not in response.text


def test_guest_credential_rotation_and_revocation(client,app):
    d=domain(client,'邀请管理')
    s=session(client,d['id'],[])
    guest,_=join(client,app,s['id'])
    assert guest.get(f"/api/guest/sessions/{s['id']}").status_code==200
    client.post(f"/api/sessions/{s['id']}/invite")
    assert guest.get(f"/api/guest/sessions/{s['id']}").status_code==401


def test_model_failure_contains_no_vendor_details(client,app):
    d=domain(client,'故障')
    s=session(client,d['id'],[],mode='private')
    async def fail(**kwargs):raise RuntimeError('SECRET-KEY-WITH-PRIVATE-PROMPT')
    app.state.service.ai.reply=fail
    response=client.post(f"/api/sessions/{s['id']}/messages",json={'content':'test'})
    assert 'SECRET' not in response.text
    assert response.json()['kind']=='unavailable'


def test_postgres_rls_blocks_unfiltered_reads_and_spoofed_writes(client,app):
    if not app.state.store.postgres:
        pytest.skip('Requires isolated PostgreSQL test database')
    from sqlalchemy.exc import DBAPIError
    d=domain(client,'行权限测试')
    fake_owner=db.uid()
    with app.state.store.engine.begin() as c:
        c.execute(insert(db.users).values(id=fake_owner,name='rls-other',password='unused',created_at=time.time()))
    with app.state.store.scope(fake_owner) as r:
        assert r.c.execute(select(db.domains)).mappings().all()==[]
    with pytest.raises(DBAPIError):
        with app.state.store.scope(fake_owner) as r:
            r.c.execute(insert(db.domains).values(id=db.uid(),owner_id=d['owner_id'],name='spoof',description='',color='sage',created_at=time.time()))


def test_rotating_credential_during_generation_prevents_persistence(client,app):
    d=domain(client,'凭证变更')
    s=session(client,d['id'],[])
    guest,_=join(client,app,s['id'])
    async def revoke_caller(**kwargs):
        app.state.auth.revoke_room(s['owner_id'],s['id'])
        return {'kind':'answer','reply':'REVOKED_REPLY','citations':[]}
    app.state.service.ai.reply=revoke_caller
    response=guest.post(f"/api/guest/sessions/{s['id']}/messages",json={'content':'test'})
    assert response.status_code==401
    assert 'REVOKED_REPLY' not in client.get(f"/api/sessions/{s['id']}").text


@pytest.mark.parametrize('tts_provider', ['cosyvoice', 'dashscope'])
def test_audio_transcript_uses_scoped_checked_reply_and_pcm_alignment(client,app,monkeypatch,tts_provider):
    from echooo.models import STTEvent,STTEventType,AudioChunk
    from echooo.providers.stt.mock import MockSTT
    class InputAudio(MockSTT):
        async def send_audio(self,pcm16):
            assert pcm16==b'\0\0'*1600
            await self._events.put(STTEvent(type=STTEventType.FINAL,transcript='介绍进度'))
    class OutputAudio:
        sample_rate=24000
        def configure_voice(self,profile):pass
        async def stream_audio(self,text,*,cancel):
            assert text=='Based on confirmed information: 已完成原型'
            yield AudioChunk(b'\1\0\2',24000)
            yield AudioChunk(b'\0',24000)
    monkeypatch.setattr('echooo.rooms.create_stt',lambda _:InputAudio())
    monkeypatch.setattr('echooo.rooms.create_tts',lambda _:OutputAudio())
    app.state.rooms.settings.stt_provider='assemblyai'
    app.state.rooms.settings.tts_provider=tts_provider
    d=domain(client,'真实协议边界')
    m=memory(client,d['id'],'进度','已完成原型')
    secret=memory(client,d['id'],'其他','NOT_FOR_AUDIO','private')
    s=session(client,d['id'],[m,secret],disclose=[m['id']])
    guest,_=join(client,app,s['id'])
    with guest.websocket_connect(f"/ws/sessions/{s['id']}?role=guest") as ws:
        assert ws.receive_json()['type']=='session.ready'
        ws.send_json({'type':'audio.enable'})
        assert ws.receive_json()['type']=='audio.ready'
        ws.send_bytes(b'\0\0'*1600)
        checked=False;pcm=b''
        while True:
            packet=ws.receive()
            if packet.get('bytes') is not None:
                assert checked
                assert len(packet['bytes'])%2==0
                pcm+=packet['bytes']
            else:
                event=json.loads(packet['text'])
                if event['type']=='message' and event['message']['role']=='assistant':checked=True
                if event['type']=='audio.end':break
        assert pcm==b'\1\0\2\0'


@pytest.mark.parametrize('tts_provider', ['cosyvoice', 'dashscope'])
def test_muted_output_skips_synthesis_and_retry_does_not_repeat_llm(client,app,monkeypatch,tts_provider):
    calls=[]
    def unexpected_tts(_):
        calls.append('tts')
        raise AssertionError('Muted output must not initialize TTS')
    monkeypatch.setattr('echooo.rooms.create_tts',unexpected_tts)
    app.state.rooms.settings.tts_provider=tts_provider
    d=domain(client,'Voice controls')
    s=session(client,d['id'],[],mode='private')
    with client.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        ws.receive_json()
        ws.send_json({'type':'playback.configure','enabled':False})
        ws.send_json({'type':'input.text','content':'Hello'})
        events=[]
        while True:
            e=ws.receive_json();events.append(e)
            if e['type']=='session.state' and e['state']=='idle':break
        assert all(e.get('state')!='listening' for e in events)
        # Ordered request/response ensures the previous synthesis branch has finished.
        ws.send_json({'type':'playback.configure','enabled':'invalid'})
        assert ws.receive_json()['type']=='error'
        assert calls==[]
        app.state.rooms.settings.tts_provider='browser'
        ws.send_json({'type':'playback.configure','enabled':True})
        ws.send_json({'type':'playback.retry'})
        reply=ws.receive_json()
        assert reply['type']=='speech.checked'
        assert reply['content']==next(e['message']['content'] for e in events if e['type']=='message' and e['message']['role']=='assistant')
    assert len(client.get(f"/api/sessions/{s['id']}").json()['messages'])==2


def test_dictation_returns_a_draft_without_creating_chat_messages(client,app,monkeypatch):
    from echooo.models import STTEvent,STTEventType
    from echooo.providers.stt.mock import MockSTT
    class InputAudio(MockSTT):
        async def send_audio(self,pcm16):
            await self._events.put(STTEvent(type=STTEventType.FINAL,transcript='Draft for review'))
    monkeypatch.setattr('echooo.rooms.create_stt',lambda _:InputAudio())
    app.state.rooms.settings.stt_provider='assemblyai'
    d=domain(client,'Dictation')
    s=session(client,d['id'],[],mode='private')
    with client.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        ws.receive_json()
        ws.send_json({'type':'playback.configure','enabled':False})
        ws.send_json({'type':'audio.enable','dictation':True})
        assert ws.receive_json()['type']=='audio.ready'
        ws.send_bytes(b'\0\0'*1600)
        assert ws.receive_json()=={'type':'transcript.final','content':'Draft for review'}
        assert client.get(f"/api/sessions/{s['id']}").json()['messages']==[]
        ws.send_json({'type':'audio.mode','dictation':False})
        ws.send_bytes(b'\0\0'*1600)
        while True:
            event=ws.receive_json()
            if event['type']=='session.state' and event['state']=='idle':break
    assert len(client.get(f"/api/sessions/{s['id']}").json()['messages'])==2


@pytest.mark.parametrize('tts_provider', ['cosyvoice', 'dashscope'])
def test_tts_failure_has_specific_error_and_preserves_text(client,app,monkeypatch,tts_provider):
    def unavailable(_):raise RuntimeError('Test provider unavailable')
    monkeypatch.setattr('echooo.rooms.create_tts',unavailable)
    app.state.rooms.settings.tts_provider=tts_provider
    d=domain(client,'TTS error')
    s=session(client,d['id'],[],mode='private')
    with client.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        ws.receive_json();ws.send_json({'type':'input.text','content':'Hello'})
        while True:
            event=ws.receive_json()
            if event['type']=='error':break
        assert event['code']=='tts_unavailable'
    assert len(client.get(f"/api/sessions/{s['id']}").json()['messages'])==2


@pytest.mark.parametrize('override', [None, 'longanhuan'])
def test_dashscope_uses_cloud_voice_and_retry_reuses_checked_text(client,app,monkeypatch,override):
    from echooo.models import AudioChunk
    voices=[]; texts=[]
    class OutputAudio:
        sample_rate=24000
        def configure_voice(self,profile):voices.append(profile.speaker_id)
        async def stream_audio(self,text,*,cancel):
            texts.append(text)
            yield AudioChunk(b'\1\0',24000)
    monkeypatch.setattr('echooo.rooms.create_tts',lambda _:OutputAudio())
    app.state.rooms.settings.tts_provider='dashscope'
    app.state.rooms.settings.dashscope_tts_voice='longanyang'
    d=domain(client,'Cloud voice')
    voice={'speaker_id':'中文女'}
    if override:voice['dashscope_voice']=override
    s=session(client,d['id'],[],mode='private',voice=voice)
    with client.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        ws.receive_json()
        ws.send_json({'type':'input.text','content':'Hello'})
        for attempt in range(2):
            pcm=b''
            while True:
                packet=ws.receive()
                if packet.get('bytes') is not None:pcm+=packet['bytes']
                else:
                    event=json.loads(packet['text'])
                    assert event['type'] not in {'error','speech.checked'}
                    if event['type']=='audio.end':break
            assert pcm==b'\1\0'
            if attempt==0:ws.send_json({'type':'playback.retry'})
    assert voices==[override or 'longanyang']*2
    assert len(texts)==2 and texts[0]==texts[1]
    assert len(client.get(f"/api/sessions/{s['id']}").json()['messages'])==2


def test_owner_can_select_an_allowed_dashscope_voice(client,app):
    app.state.rooms.settings.tts_provider='dashscope'
    app.state.rooms.settings.dashscope_api_key='test-key'
    d=domain(client,'Voice choice')
    s=session(client,d['id'],[],mode='private')
    changed=client.patch(f"/api/sessions/{s['id']}/voice",json={'dashscope_voice':'longanlufeng'})
    assert changed.status_code==200
    assert changed.json()['voice']['dashscope_voice']=='longanlufeng'
    assert client.get(f"/api/sessions/{s['id']}").json()['voice']['dashscope_voice']=='longanlufeng'
    assert client.patch(f"/api/sessions/{s['id']}/voice",json={'dashscope_voice':'unknown'}).status_code==422


def test_cloud_voice_selection_is_provider_scoped_and_owner_only(client,app):
    d=domain(client,'Voice scope')
    s=session(client,d['id'],[],mode='private')
    assert client.patch(f"/api/sessions/{s['id']}/voice",json={'dashscope_voice':'longanyang'}).status_code==409
    outsider=TestClient(app)
    assert outsider.patch(f"/api/sessions/{s['id']}/voice",json={'dashscope_voice':'longanyang'}).status_code==401


def test_owner_can_list_create_select_and_delete_custom_voice(client,app):
    custom_id='cosyvoice-v3-flash-mine-123'
    class VoiceManager:
        known_voice_ids=set()
        voices=[]
        cached_voices=[]
        async def list_voices(self):
            self.known_voice_ids={voice['id'] for voice in self.voices}
            self.cached_voices=list(self.voices)
            return list(self.voices)
        async def create_voice(self,**kwargs):
            assert kwargs['prefix']=='mine' and kwargs['language']=='zh'
            assert kwargs['filename']=='voice.wav' and kwargs['data']==b'voice sample'
            voice={'id':custom_id,'name':custom_id,'description':'Custom voice','custom':True,
                'managed':True,'status':'OK','target_model':'cosyvoice-v3-flash','created_at':''}
            self.voices=[voice];self.known_voice_ids={custom_id}
            self.cached_voices=[voice]
            return voice
        async def delete_voice(self,voice_id):
            assert voice_id==custom_id
            self.voices=[];self.known_voice_ids.clear()
            self.cached_voices=[]
    manager=VoiceManager()
    app.state.voice_manager=manager
    app.state.rooms.settings.tts_provider='dashscope'
    app.state.rooms.settings.dashscope_api_key='test-key'
    app.state.rooms.settings.dashscope_tts_model='cosyvoice-v3-flash'
    app.state.rooms.settings.dashscope_tts_voice='longanyang'
    assert client.get('/api/tts/voices').json()['voices'][0]['id']=='longanyang'
    created=client.post('/api/tts/voices/clone',data={'prefix':'mine','language':'zh'},
        files={'file':('voice.wav',b'voice sample','audio/wav')})
    assert created.status_code==201 and created.json()['voice']['id']==custom_id
    d=domain(client,'Custom voice')
    s=session(client,d['id'],[],mode='private')
    assert client.patch(f"/api/sessions/{s['id']}/voice",json={'dashscope_voice':custom_id}).status_code==200
    deleted=client.delete(f'/api/tts/voices/{custom_id}')
    assert deleted.status_code==200 and deleted.json()['reset_sessions']==1
    assert client.get(f"/api/sessions/{s['id']}").json()['voice']['dashscope_voice']=='longanyang'
    assert client.delete('/api/tts/voices/longanyang').status_code==409


def test_custom_voice_management_is_owner_only(client,app):
    app.state.rooms.settings.tts_provider='dashscope'
    app.state.voice_manager=object()
    outsider=TestClient(app)
    assert outsider.get('/api/tts/voices').status_code==401
    assert outsider.post('/api/tts/voices/clone',data={'prefix':'mine','language':'zh'},
        files={'file':('voice.wav',b'voice sample','audio/wav')}).status_code==401
    assert outsider.delete('/api/tts/voices/custom-voice').status_code==401


def test_voice_list_failure_keeps_presets_available(client,app):
    from echooo.providers.tts.dashscope_voices import DashScopeVoiceError
    class Unavailable:
        known_voice_ids=set()
        cached_voices=[]
        async def list_voices(self):
            raise DashScopeVoiceError('Voice management is temporarily unavailable.')
    app.state.rooms.settings.tts_provider='dashscope'
    app.state.voice_manager=Unavailable()
    result=client.get('/api/tts/voices')
    assert result.status_code==200
    assert result.json()['management_available'] is False
    assert result.json()['management_error']=='Voice management is temporarily unavailable.'
    assert result.json()['voices']


@pytest.mark.parametrize('action', ['mute', 'interrupt', 'end', 'revoke', 'disconnect'])
def test_cloud_synthesis_is_closed_when_playback_ends(client,app,monkeypatch,action):
    import threading
    from echooo.models import AudioChunk
    started=threading.Event();closed=threading.Event()
    class StalledAudio:
        sample_rate=24000
        def configure_voice(self,profile):pass
        async def stream_audio(self,text,*,cancel):
            started.set()
            try:
                await cancel.wait()
                # A late frame after mute must not be forwarded.
                yield AudioChunk(b'\1\0',24000)
            finally:
                closed.set()
    monkeypatch.setattr('echooo.rooms.create_tts',lambda _:StalledAudio())
    app.state.rooms.settings.tts_provider='dashscope'
    d=domain(client,'Cancel cloud speech')
    s=session(client,d['id'],[],mode='private')
    with client.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        ws.receive_json()
        ws.send_json({'type':'input.text','content':'Hello'})
        while ws.receive_json()['type']!='audio.start':pass
        assert started.wait(2)
        if action=='mute':
            ws.send_json({'type':'playback.configure','enabled':False})
            assert closed.wait(2)
            ws.send_json({'type':'playback.configure','enabled':'invalid'})
            assert ws.receive_json()['type']=='error'  # No late audio or audio.end.
        elif action=='interrupt':
            ws.send_json({'type':'interrupt'})
            assert ws.receive_json()['type']=='playback.stop'
        elif action in {'end','revoke'}:
            assert client.post(f"/api/sessions/{s['id']}/{action}").status_code==200
            assert ws.receive_json()['type']=='playback.stop'
            assert ws.receive_json()['type']=='session.closed'
        else:
            ws.close()
        assert closed.wait(2)


def test_failed_microphone_can_retry_without_reopening_room(client,app,monkeypatch):
    from echooo.providers.stt.mock import MockSTT
    attempts=[]
    class FailingSTT(MockSTT):
        async def connect(self,**kwargs):
            attempts.append(1)
            if len(attempts)==1:raise RuntimeError('SECRET_STT_ERROR')
            await super().connect(**kwargs)
    monkeypatch.setattr('echooo.rooms.create_stt',lambda _:FailingSTT())
    app.state.rooms.settings.stt_provider='assemblyai'
    d=domain(client,'语音恢复');s=session(client,d['id'],[],mode='private')
    with client.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        ws.receive_json();ws.send_json({'type':'audio.enable'})
        error=ws.receive_json();assert error['type']=='audio.error' and 'SECRET' not in str(error)
        ws.send_json({'type':'audio.enable'})
        assert ws.receive_json()['type']=='audio.ready'


def test_interrupt_cancels_unfinished_model_output(client,app):
    import threading
    started=threading.Event()
    d=domain(client,'打断');s=session(client,d['id'],[],mode='private')
    async def slow_reply(**kwargs):
        if kwargs['query']=='first':
            started.set()
            await asyncio.Event().wait()
        return {'kind':'clarify','reply':'第二轮已响应','citations':[]}
    app.state.service.ai.reply=slow_reply
    with client.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        ws.receive_json();ws.send_json({'type':'input.text','content':'first'})
        assert started.wait(2)
        ws.send_json({'type':'input.text','content':'second'})
        while ws.receive_json()['type']!='speech.checked':pass
    view=client.get(f"/api/sessions/{s['id']}").json()
    assert [m['content'] for m in view['messages'] if m['role']=='assistant']==['第二轮已响应']


async def test_llm_transport_preserves_structured_response(monkeypatch):
    import httpx
    ai=Intelligence(Settings(llm_provider='openai_compatible',llm_base_url='https://llm.example/v1'))
    captured=[]
    def handle(request):
        payload=json.loads(request.content);captured.append(payload)
        assert request.url.path=='/v1/chat/completions'
        answer=json.dumps({'kind':'answer','reply':'已完成原型','citations':['f']},ensure_ascii=False)
        return httpx.Response(200,json={'choices':[{'message':{'content':answer},'finish_reason':'stop'}]})
    original=httpx.AsyncClient
    monkeypatch.setattr('echooo.intelligence.httpx.AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handle),**kwargs))
    result=await ai.json_call('Return structured JSON',{'facts':[{'id':'f','content':'已完成原型'}]})
    assert result['reply']=='已完成原型'
    assert captured[0]['stream'] is False


def test_store_reopen_preserves_auth_and_domains(tmp_path):
    url=f'sqlite:///{tmp_path}/persist.db'
    settings=Settings(database_url=url,stt_provider='mock',llm_provider='mock',tts_provider='browser')
    with TestClient(create_app(settings)) as first:
        first.post('/api/auth/setup',json={'name':'persistent-owner','password':'persistent-password'})
        d=domain(first,'可持续的领域')
        initial=first.get('/api/domains').json()
    with TestClient(create_app(settings)) as second:
        assert second.get('/api/auth').json()['needs_setup'] is False
        assert second.post('/api/auth/login',json={'name':'persistent-owner','password':'persistent-password'}).status_code==200
        reopened=second.get('/api/domains').json()
        assert reopened==initial
        assert any(item['id']==d['id'] for item in reopened)
