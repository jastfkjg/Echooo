"""Global entry, explicit memory destinations, and upgrade preservation."""
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert

from echooo import database as db
from echooo.app import create_app
from echooo.config import Settings
from echooo.auth import hash_password
from echooo.service import Problem


@pytest.fixture
def workspace(tmp_path):
    app=create_app(Settings(database_url=f'sqlite:///{tmp_path}/chat.db', stt_provider='mock',llm_provider='mock',tts_provider='browser'))
    with TestClient(app) as client:
        assert client.post('/api/auth/setup',json={'name':'owner','password':'test-password'}).status_code==200
        yield app,client


def chat(client, **changes):
    body={'mode':'private','allow_learning':False, **changes}
    r=client.post('/api/sessions',json=body)
    assert r.status_code==201,r.text
    return r.json()


def add_domain(client,name):
    r=client.post('/api/domains',json={'name':name})
    assert r.status_code==201,r.text
    return r.json()['id']


def test_chat_without_domains_and_automatic_title(workspace):
    app,c=workspace
    s=chat(c)
    assert s['domain_ids']==[] and s['read_ids']==[] and s['write_domain_id'] is None
    seen=[]
    async def reply(**kwargs):
        seen.append(kwargs)
        return {'kind':'answer','reply':'General answer','citations':[]}
    app.state.service.ai.reply=reply
    assert c.post(f"/api/sessions/{s['id']}/messages",json={'content':'How do I organize a short presentation?'}).status_code==200
    assert seen[0]['facts']==[] and seen[0]['history']==[]
    assert c.get(f"/api/sessions/{s['id']}").json()['title']=='How do I organize a short presentation?'
    ended=c.post(f"/api/sessions/{s['id']}/end").json()
    assert ended['proposals']==[]
    assert [d['name'] for d in c.get('/api/domains').json()]==['default']
    assert c.post(f"/api/sessions/{s['id']}/invite").status_code in (400,410)


def test_existing_personal_knowledge_is_not_loaded_into_general_chat(workspace):
    app,c=workspace
    did=add_domain(c,'Secret research')
    m=c.post(f'/api/domains/{did}/memories',json={'title':'Private','content':'SECRET_NOT_IN_GENERAL_CHAT'}).json()
    scoped=chat(c,domain_ids=[did],read_ids=[m['id']])
    c.post(f"/api/sessions/{scoped['id']}/messages",json={'content':'OLD_PRIVATE_CONVERSATION'})
    seen=[]
    async def spy(**kwargs):
        seen.append(kwargs)
        return {'kind':'answer','reply':'General response','citations':[]}
    app.state.service.ai.reply=spy
    general=chat(c)
    c.post(f"/api/sessions/{general['id']}/messages",json={'content':'What do you know about me?'})
    assert seen[0]['facts']==[] and seen[0]['history']==[]
    assert c.get(f"/api/sessions/{scoped['id']}").json()['messages']
    bad=c.post('/api/sessions',json={'mode':'private','allow_learning':False,'read_ids':[m['id']]})
    assert bad.status_code==403
    assert c.post('/api/sessions',json={'mode':'private','allow_learning':True}).status_code==422
    assert c.post('/api/sessions',json={'mode':'delegate','audience':'Client','allow_learning':False}).status_code==422


def test_general_chat_memory_requires_explicit_destination_and_review(workspace):
    app,c=workspace
    s=chat(c)
    reply=c.post(f"/api/sessions/{s['id']}/messages",json={'content':'I prefer meetings after lunch.'}).json()
    did=add_domain(c,'My schedule')
    body={'domain_id':did,'message_id':reply['user']['id'],'title':'Meeting preference','content':'I prefer meetings after lunch.'}
    assert c.post(f"/api/sessions/{s['id']}/memory-proposals",json={k:v for k,v in body.items() if k!='domain_id'}).status_code==422
    result=c.post(f"/api/sessions/{s['id']}/memory-proposals",json=body)
    assert result.status_code==201,result.text
    p=result.json()
    assert p['status']=='pending' and p['domain_id']==did and p['evidence'][0]['id']==reply['user']['id']
    assert c.get(f'/api/domains/{did}/memories').json()==[]
    assert c.get(f"/api/sessions/{s['id']}").json()['domain_ids']==[]
    reviewed=c.post(f"/api/proposals/{p['id']}/review",json={'decision':'approve','title':p['title'],'content':p['content']})
    assert reviewed.status_code==200 and reviewed.json()['memory']['visibility']=='private'
    assert c.post(f"/api/sessions/{s['id']}/memory-proposals",json={**body,'message_id':reply['assistant']['id']}).status_code==403
    other=chat(c)
    assert c.post(f"/api/sessions/{other['id']}/memory-proposals",json=body).status_code==403
    outsider=TestClient(app)
    assert outsider.post(f"/api/sessions/{s['id']}/memory-proposals",json=body).status_code==401


def test_scoped_chat_cannot_save_to_unselected_domain(workspace):
    app,c=workspace
    a,b=add_domain(c,'Selected'),add_domain(c,'Not selected')
    s=chat(c,domain_ids=[a],write_domain_id=a,allow_learning=True)
    msg=c.post(f"/api/sessions/{s['id']}/messages",json={'content':'New information'}).json()['user']
    body={'domain_id':b,'message_id':msg['id'],'title':'New','content':msg['content']}
    assert c.post(f"/api/sessions/{s['id']}/memory-proposals",json=body).status_code==403
    assert c.post(f"/api/sessions/{s['id']}/memory-proposals",json={**body,'domain_id':a}).status_code==201
    # A manual proposal must not silently disable normal end-of-chat extraction.
    result=c.post(f"/api/sessions/{s['id']}/end").json()
    assert len(result['proposals'])==2


def test_global_private_chat_uses_voice_room_without_a_domain(workspace):
    app,c=workspace
    s=chat(c)
    # Old private chats remain usable through the same validation as live voice.
    with app.state.store.scope(s['owner_id']) as r:
        r.change(db.sessions,s['id'],expires_at=time.time()-1)
    with c.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        assert ws.receive_json()['type']=='session.ready'
        ws.send_json({'type':'input.text','content':'Hello'})
        while True:
            event=ws.receive_json()
            if event['type']=='speech.checked':
                assert event['content']
                break


def test_default_chat_reads_and_learns_without_creating_a_domain(workspace):
    app,c=workspace
    default=c.get('/api/domains').json()[0]
    first=c.post('/api/sessions/quick-chat')
    assert first.status_code==201,first.text
    s=first.json()
    assert s['mode']=='private' and s['domain_ids']==[default['id']]
    assert s['read_ids']==s['disclose_ids']==[]
    assert s['allow_learning'] and s['write_domain_id']==default['id']
    assert c.post(f"/api/sessions/{s['id']}/invite").status_code==400
    with c.websocket_connect(f"/ws/sessions/{s['id']}?role=owner") as ws:
        assert ws.receive_json()['type']=='session.ready'
        ws.send_json({'type':'input.text','content':'I prefer meetings after lunch.'})
        while ws.receive_json()['type']!='speech.checked':
            pass
    ended=c.post(f"/api/sessions/{s['id']}/end")
    assert ended.status_code==200,ended.text
    p=ended.json()['proposals'][0]
    assert p['domain_id']==default['id'] and p['status']=='pending'
    assert c.get(f"/api/domains/{default['id']}/memories").json()==[]
    pending_chat=c.post('/api/sessions/quick-chat').json()
    assert pending_chat['read_ids']==[]
    approved=c.post(f"/api/proposals/{p['id']}/review",json={
        'decision':'approve','title':p['title'],'content':p['content']})
    assert approved.status_code==200,approved.text
    m=approved.json()['memory']
    assert m['visibility']=='private' and m['domain_id']==default['id']
    fresh=c.post('/api/sessions/quick-chat').json()
    assert fresh['read_ids']==[m['id']] and fresh['grants']=={m['id']:m['version']}
    response=c.post(f"/api/sessions/{fresh['id']}/messages",json={'content':'What are my meeting preferences?'})
    assert response.status_code==200,response.text
    assert response.json()['assistant']['citations']==[m['id']]
    assert [d['id'] for d in c.get('/api/domains').json()]==[default['id']]


def test_default_chat_excludes_other_domains_expired_memories_and_owners(workspace):
    app,c=workspace
    default=c.get('/api/domains').json()[0]
    secret=add_domain(c,'Private project')
    hidden=c.post(f'/api/domains/{secret}/memories',json={'title':'Secret','content':'PROJECT_SECRET'}).json()
    expired=c.post(f"/api/domains/{default['id']}/memories",json={'title':'Expired','content':'OLD_DEFAULT'}).json()
    with app.state.store.scope(default['owner_id']) as r:
        r.change(db.memories,expired['id'],expires_at=time.time()-1)
    scoped=chat(c,domain_ids=[secret],read_ids=[hidden['id']])
    c.post(f"/api/sessions/{scoped['id']}/messages",json={'content':'OTHER_DOMAIN_HISTORY'})
    seen=[]
    async def spy(**kwargs):
        seen.append(kwargs)
        return {'kind':'answer','reply':'A private answer','citations':[]}
    app.state.service.ai.reply=spy
    s=c.post('/api/sessions/quick-chat').json()
    assert s['domain_ids']==[default['id']] and s['read_ids']==[]
    assert c.post(f"/api/sessions/{s['id']}/messages",json={'content':'What do you know?'}).status_code==200
    assert seen[0]['facts']==seen[0]['history']==[]
    proposals=c.post(f"/api/sessions/{s['id']}/end").json()['proposals']
    assert proposals and all(p['domain_id']==default['id'] for p in proposals)
    who=db.uid()
    with app.state.store.engine.begin() as conn:
        conn.execute(insert(db.users).values(id=who,name='other',password=hash_password('p'),created_at=time.time()))
    other=TestClient(app)
    assert other.post('/api/sessions/quick-chat').status_code==401
    other.cookies.set('echooo_owner',app.state.auth.issue(who,'owner',3600))
    isolated=other.post('/api/sessions/quick-chat').json()
    assert isolated['owner_id']==who and isolated['domain_ids']!=s['domain_ids']
    assert isolated['read_ids']==[]
    assert c.post('/api/sessions/quick-chat',headers={'Origin':'https://evil.example'}).status_code==403


def test_deleting_default_recreates_empty_domain_without_restoring_data(workspace):
    app,c=workspace
    default=c.get('/api/domains').json()[0]
    old=c.post(f"/api/domains/{default['id']}/memories",json={'title':'Delete me','content':'REMOVED_DEFAULT'}).json()
    s=c.post('/api/sessions/quick-chat').json()
    assert s['read_ids']==[old['id']]
    assert c.delete(f"/api/domains/{default['id']}").status_code==200
    assert c.get(f"/api/sessions/{s['id']}").status_code==404
    new=c.post('/api/sessions/quick-chat').json()
    assert new['domain_ids']!=s['domain_ids'] and new['read_ids']==[]
    assert new['write_domain_id']==new['domain_ids'][0]
    assert 'REMOVED_DEFAULT' not in c.get('/api/export').text
    another=c.post('/api/sessions/quick-chat').json()
    assert another['domain_ids']==new['domain_ids']
    assert len(c.get('/api/domains').json())==1


def test_existing_empty_workspace_gets_default_once_at_startup(tmp_path):
    url=f'sqlite:///{tmp_path}/empty-legacy.db'
    engine=create_engine(url)
    db.metadata.create_all(engine)
    owner=db.uid()
    with engine.begin() as c:
        c.execute(insert(db.users).values(id=owner,name='old-owner',password=hash_password('p'),created_at=time.time()))
    engine.dispose()
    store=db.Store(url)
    with store.scope(owner) as r:
        initial=r.list(db.domains)
        assert len(initial)==1 and initial[0]['name']=='default'
    store.close()
    store=db.Store(url)
    with store.scope(owner) as r:
        assert r.list(db.domains)==initial
    store.close()


def test_quick_chat_reuses_only_latest_compatible_empty_chat(workspace):
    app,c=workspace
    first=c.post('/api/sessions/quick-chat').json()
    again=c.post('/api/sessions/quick-chat').json()
    assert again['id']==first['id'] and again['expires_at']==first['expires_at']
    assert len(c.get('/api/sessions').json())==1
    c.post(f"/api/sessions/{first['id']}/messages",json={'content':'Hello'})
    second=c.post('/api/sessions/quick-chat').json()
    assert second['id']!=first['id']
    assert c.get('/api/sessions').json()[0]['message_count']==0
    assert c.get('/api/sessions').json()[1]['message_count']==2
    # Do not reopen an older empty chat when the latest private chat has content.
    third=chat(c)
    c.post(f"/api/sessions/{third['id']}/messages",json={'content':'Different chat'})
    fourth=c.post('/api/sessions/quick-chat').json()
    assert fourth['id'] not in (first['id'],second['id'],third['id'])
    # A new knowledge snapshot requires fresh authorization, even if still empty.
    did=fourth['domain_ids'][0]
    m=c.post(f'/api/domains/{did}/memories',json={'title':'Preference','content':'Quiet rooms'}).json()
    fifth=c.post('/api/sessions/quick-chat').json()
    assert fifth['id']!=fourth['id'] and fifth['read_ids']==[m['id']]


@pytest.mark.parametrize('status',['ended','revoked'])
def test_quick_chat_does_not_revive_inactive_empty_chat(workspace,status):
    app,c=workspace
    s=c.post('/api/sessions/quick-chat').json()
    with app.state.store.scope(s['owner_id']) as r:
        r.change(db.sessions,s['id'],status=status)
    assert c.post('/api/sessions/quick-chat').json()['id']!=s['id']


def test_private_chat_continues_after_legacy_deadline_with_history(workspace):
    app,c=workspace
    s=c.post('/api/sessions/quick-chat').json()
    assert s['expires_at'] is None
    with app.state.store.scope(s['owner_id']) as r:
        r.change(db.sessions,s['id'],expires_at=time.time()-86400)
    assert c.post('/api/sessions/quick-chat').json()['id']==s['id']
    first=c.post(f"/api/sessions/{s['id']}/messages",json={'content':'Remember our discussion here.'})
    assert first.status_code==200
    seen=[]
    async def reply(**kwargs):
        seen.append(kwargs)
        return {'kind':'answer','reply':'Continuing our chat.','citations':[]}
    app.state.service.ai.reply=reply
    assert c.post(f"/api/sessions/{s['id']}/messages",json={'content':'Continue please.'}).status_code==200
    assert any(m['content']=='Remember our discussion here.' for m in seen[0]['history'])
    view=c.get(f"/api/sessions/{s['id']}").json()
    assert view['status']=='active' and len(view['messages'])==4
    assert c.post(f"/api/sessions/{s['id']}/end").status_code==200
    assert c.post(f"/api/sessions/{s['id']}/messages",json={'content':'After ending'}).status_code==410


def test_concurrent_quick_chat_creates_one_empty_chat(workspace):
    app,c=workspace
    owner=c.get('/api/domains').json()[0]['owner_id']
    with ThreadPoolExecutor(max_workers=8) as pool:
        sessions=list(pool.map(lambda _:app.state.service.quick_chat(owner),range(16)))
    assert len({s['id'] for s in sessions})==1
    assert len(c.get('/api/sessions').json())==1


def test_session_rename_is_title_only_and_validated(workspace):
    app,c=workspace
    s=chat(c)
    result=c.patch(f"/api/sessions/{s['id']}",json={'title':'  Product planning  '})
    assert result.status_code==200 and result.json()['title']=='Product planning'
    assert result.json()['expires_at']==s['expires_at']
    for body in ({'title':' '},{'title':'x'*121},{'title':'New','domain_ids':[]}):
        assert c.patch(f"/api/sessions/{s['id']}",json=body).status_code==422
    c.post(f"/api/sessions/{s['id']}/messages",json={'content':'Hello'})
    assert c.get(f"/api/sessions/{s['id']}").json()['title']=='Product planning'
    assert c.patch('/api/sessions/missing',json={'title':'New'}).status_code==404


def test_deleting_chat_preserves_confirmed_memories_and_other_chats(workspace):
    app,c=workspace
    s=c.post('/api/sessions/quick-chat').json();sid=s['id'];did=s['domain_ids'][0]
    msg=c.post(f'/api/sessions/{sid}/messages',json={'content':'I prefer quiet rooms'}).json()['user']
    body={'domain_id':did,'message_id':msg['id'],'title':'Quiet','content':'I prefer quiet rooms'}
    proposal=c.post(f'/api/sessions/{sid}/memory-proposals',json=body).json()
    confirmed=c.post(f"/api/proposals/{proposal['id']}/review",json={'decision':'approve','title':'Quiet','content':body['content']}).json()['memory']
    pending=c.post(f'/api/sessions/{sid}/memory-proposals',json={**body,'title':'Still pending'}).json()
    other=c.post('/api/sessions/quick-chat').json()
    assert confirmed['id'] in other['read_ids']
    with c.websocket_connect(f'/ws/sessions/{sid}?role=owner') as ws:
        assert ws.receive_json()['type']=='session.ready'
        assert c.delete(f'/api/sessions/{sid}').status_code==200
        while ws.receive_json()['type']!='session.closed':
            pass
    assert c.get(f'/api/sessions/{sid}').status_code==404
    assert c.delete(f'/api/sessions/{sid}').status_code==404
    assert c.get(f"/api/sessions/{other['id']}").status_code==200
    assert c.post(f"/api/sessions/{other['id']}/messages",json={'content':'What do I prefer?'}).status_code==200
    with app.state.store.scope(s['owner_id']) as r:
        assert r.get(db.memories,confirmed['id'])['provenance']
        assert r.list(db.versions,db.versions.c.memory_id==confirmed['id'])
        assert not r.get(db.proposals,pending['id'])
        for table in (db.messages,db.actions,db.audit):
            assert not r.list(table,table.c.session_id==sid)


def test_session_management_requires_owner_and_revokes_guest_credentials(workspace):
    app,c=workspace
    default=c.get('/api/domains').json()[0]
    s=chat(c,mode='delegate',audience='Team',domain_ids=[default['id']]);sid=s['id']
    token=c.post(f'/api/sessions/{sid}/invite').json()['token']
    guest=TestClient(app)
    assert guest.post('/api/guest/join',json={'token':token}).status_code==200
    who=db.uid()
    with app.state.store.engine.begin() as conn:
        conn.execute(insert(db.users).values(id=who,name='other',password=hash_password('p'),created_at=time.time()))
    outsider=TestClient(app)
    outsider.cookies.set('echooo_owner',app.state.auth.issue(who,'owner',3600))
    for client,status in ((guest,401),(outsider,404)):
        assert client.patch(f'/api/sessions/{sid}',json={'title':'Not yours'}).status_code==status
        assert client.delete(f'/api/sessions/{sid}').status_code==status
    assert c.delete(f'/api/sessions/{sid}',headers={'Origin':'https://evil.example'}).status_code==403
    assert c.get(f'/api/sessions/{sid}').status_code==200
    assert c.delete(f'/api/sessions/{sid}').status_code==200
    assert guest.get(f'/api/guest/sessions/{sid}').status_code in (401,403)
    assert guest.post('/api/guest/join',json={'token':token}).status_code in (401,403)
    with app.state.store.engine.begin() as conn:
        assert not conn.execute(db.select(db.tokens).where(db.tokens.c.session_id==sid)).all()


@pytest.mark.asyncio
@pytest.mark.parametrize('learning',[False,True])
async def test_deletion_blocks_inflight_generation_and_learning(workspace,learning):
    app,c=workspace
    s=c.post('/api/sessions/quick-chat').json()
    ready,release=asyncio.Event(),asyncio.Event()
    if learning:
        c.post(f"/api/sessions/{s['id']}/messages",json={'content':'I prefer concise plans'})
        app.state.service.stop(s['owner_id'],s['id'],'ended')
        async def extract(records):
            ready.set();await release.wait()
            return [{'title':'Plan','content':'Concise','evidence_ids':[records[0]['id']]}]
        app.state.service.ai.extract=extract
        task=asyncio.create_task(app.state.service.learn_session(s['owner_id'],s['id']))
    else:
        async def reply(**kwargs):
            ready.set();await release.wait()
            return {'kind':'answer','reply':'Too late','citations':[]}
        app.state.service.ai.reply=reply
        task=asyncio.create_task(app.state.service.talk(s['owner_id'],s['id'],'Hello',guest=False))
    await asyncio.wait_for(ready.wait(),2)
    app.state.service.delete_session(s['owner_id'],s['id'])
    release.set()
    with pytest.raises(Problem) as error:
        await asyncio.wait_for(task,2)
    assert error.value.status==404
    with app.state.store.scope(s['owner_id']) as r:
        assert not r.list(db.messages,db.messages.c.session_id==s['id'])
        assert not r.list(db.proposals,db.proposals.c.session_id==s['id'])


@pytest.mark.parametrize('destination_required',[True,False])
def test_upgrade_preserves_old_sessions_children_and_foreign_keys(tmp_path,destination_required):
    url=f'sqlite:///{tmp_path}/legacy.db'
    engine=create_engine(url)
    # Reproduce the former NOT NULL constraint without mutating global metadata.
    legacy=db.metadata.tables['sessions'].to_metadata(db.MetaData())
    for table in db.metadata.sorted_tables:
        if table.name!='sessions':table.to_metadata(legacy.metadata)
    legacy.c.write_domain_id.nullable=not destination_required
    legacy.c.expires_at.nullable=False
    legacy.metadata.create_all(engine)
    owner,did,sid,mid=db.uid(),db.uid(),db.uid(),db.uid()
    with engine.begin() as c:
        c.execute(insert(db.users).values(id=owner,name='old-owner',password=hash_password('p'),created_at=time.time()))
        c.execute(insert(db.domains).values(id=did,owner_id=owner,name='Existing domain',description='',color='sage',created_at=time.time()))
        values=dict(owner_id=owner,title='Existing chat',audience='',goal='',domain_ids=[did],read_ids=[],disclose_ids=[],grants={},write_domain_id=did,allow_learning=1,action_policy='none',expires_at=time.time()-3600,summary={},voice={},created_at=time.time())
        c.execute(insert(db.sessions).values(**values,id=sid,mode='private',status='active'))
        delegate_id=db.uid()
        c.execute(insert(db.sessions).values(**values,id=delegate_id,mode='delegate',status='active'))
        closed_ids={status:db.uid() for status in ('ended','revoked')}
        for status,closed_id in closed_ids.items():
            c.execute(insert(db.sessions).values(**values,id=closed_id,mode='private',status=status))
        c.execute(insert(db.messages).values(id=mid,owner_id=owner,session_id=sid,role='owner',content='KEEP_THIS_MESSAGE',citations=[],delivery='received',created_at=time.time()))
    engine.dispose()
    store=db.Store(url)
    with store.scope(owner) as r:
        assert r.get(db.sessions,sid)['write_domain_id']==did
        assert r.get(db.sessions,sid)['expires_at'] is None
        assert r.get(db.sessions,sid)['status']=='active'
        assert r.get(db.sessions,delegate_id)['expires_at']==values['expires_at']
        for status,closed_id in closed_ids.items():
            assert r.get(db.sessions,closed_id)['status']==status
        assert r.get(db.messages,mid)['content']=='KEEP_THIS_MESSAGE'
        assert list(r.c.exec_driver_sql('PRAGMA foreign_key_check'))==[]
        assert r.c.exec_driver_sql('PRAGMA foreign_keys').scalar()==1
        assert not next(row[3] for row in r.c.exec_driver_sql('PRAGMA table_info(sessions)') if row[1]=='write_domain_id')
        assert not next(row[3] for row in r.c.exec_driver_sql('PRAGMA table_info(sessions)') if row[1]=='expires_at')
        r.remove(db.sessions,sid)
        assert r.get(db.messages,mid) is None
    store.close()
    # Upgrade is idempotent, including after actual writes.
    store=db.Store(url)
    with store.scope(owner) as r:assert r.get(db.domains,did)['name']=='Existing domain'
    store.close()
