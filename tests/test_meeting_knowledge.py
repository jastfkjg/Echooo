import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from echooo import database as db
from echooo.meeting_agent import MeetingAgent
from echooo.meeting_knowledge import KnowledgeInput
from test_meeting_agent import app, client, Socket
from test_meeting_bots import invite


def domain(client, name):
    return client.post('/api/domains', json={'name': name}).json()['id']


def memory(client, did, content='Release on Friday.', **extra):
    return client.post(f'/api/domains/{did}/memories', json={
        'title': content[:80], 'content': content, 'visibility': 'shareable', **extra}).json()


def meeting(client, did=None):
    return client.post('/api/meetings', json={'title': 'Project review', 'project_id': did}).json()


def configure(client, mid, did, memories=(), **extra):
    base=f'/api/meetings/{mid}/knowledge'
    revision=client.get(base).json()['revision']
    return client.put(base,json={'revision':revision,'project_id':did,
        'memory_ids':[m['id'] for m in memories],'share_with_meeting':True,**extra})


def connect_agent(client, app, mid):
    base='/api/meetings/'+mid
    invite(client,base,'https://zoom.us/j/123456789')
    manager=app.state.meeting_bots;row=next(r for r in manager.rows() if r['meeting_id']==mid)
    manager.update(row,state='joined_recording')
    agent=MeetingAgent(manager,row);manager.agents[row['id']]=agent
    return agent


def test_project_selection_default_isolation_and_explicit_disclosure(client, app):
    a,b=domain(client,'Project A'),domain(client,'Project B')
    approved=memory(client,a,'A release is Friday.')
    private=memory(client,a,'Private budget',visibility='private')
    restricted=memory(client,a,'Internal only',audiences=['Engineering'])
    other=memory(client,b,'B release is secret.')
    m=meeting(client,a);mid=m['id']; k=app.state.meeting_knowledge
    assert not k.context(m['owner_id'],mid,'release')[0]['knowledge']
    for fact in [private,restricted,other]:
        assert configure(client,mid,a,[fact]).status_code==403
    assert configure(client,mid,a,[approved],share_with_meeting=False).status_code==400
    assert configure(client,mid,a,[approved]).status_code==200
    context,scope=k.context(m['owner_id'],mid,'secret budget release')
    assert [x['id'] for x in context['knowledge']]==[approved['id']]
    assert other['content'] not in str(context) and private['content'] not in str(context)
    assert TestClient(app).get(f'/api/meetings/{mid}/knowledge').status_code==401
    no_project=meeting(client)
    assert not k.context(m['owner_id'],no_project['id'],'release')[0]['knowledge']
    assert client.get('/api/meetings').json()[0]['project_name'] is None


def test_project_lock_reference_grants_and_optimistic_revision(client):
    a,b=domain(client,'A'),domain(client,'B'); ref=memory(client,b)
    m=meeting(client,a);mid=m['id']
    cfg=configure(client,mid,a,[ref],reference_ids=[b]).json()
    assert cfg['shared_count']==1
    assert client.put(f'/api/meetings/{mid}/knowledge',json={'project_id':a,'revision':0}).status_code==409
    client.post(f'/api/meetings/{mid}/utterances',json={'content':'Started discussion.'})
    assert configure(client,mid,b).status_code==409
    assert configure(client,mid,a,[]).status_code==200  # Revocation stays available.
    assert client.patch(f'/api/meetings/{mid}',json={'title':'Rename','project_id':b}).status_code==400


async def test_cited_answers_use_selected_knowledge_and_revoke_old_history(client,app):
    did=domain(client,'A'); fact=memory(client,did)
    m=meeting(client,did);configure(client,m['id'],did,[fact])
    agent=connect_agent(client,app,m['id'])
    await agent.accept('first','When do we release?','public','')
    event=agent.queue.get_nowait();await agent.answer(event)
    assert event['status']=='submitted' and fact['content'] in event['response']
    citations=agent.events()[0]['citations']
    assert citations[0]['id']==fact['id'] and citations[0]['version']==1
    old_scope=agent.manager.knowledge.snapshot(agent.who,agent.mid)[4]
    client.put('/api/memories/'+fact['id'],json={'title':'Changed','content':'Now Monday.',
        'visibility':'shareable','expected_version':1})
    assert not agent.manager.knowledge.valid(agent.who,agent.mid,old_scope)
    assert not agent.manager.knowledge.context(agent.who,agent.mid,'release')[0]['knowledge']
    assert not agent.context({'id':'next','request':'When?','audience':'voice'})['recent_questions']
    assert agent.events()[0]['citations'][0]['changed']


async def test_revocation_during_generation_prevents_send_and_foreign_citations_fail(client,app):
    did=domain(client,'A'); fact=memory(client,did); m=meeting(client,did)
    configure(client,m['id'],did,[fact]);agent=connect_agent(client,app,m['id'])
    agent.settings=replace(agent.settings,llm_provider='openai_compatible')
    async def revoke(*args,**kwargs):
        cfg=agent.manager.knowledge.view(agent.who,agent.mid)
        agent.manager.knowledge.save(agent.who,agent.mid,KnowledgeInput(project_id=did,revision=cfg['revision']))
        return {'reply':'Friday','citations':[fact['id']]}
    agent.intelligence.json_call=revoke
    await agent.accept('first','When?','public','');event=agent.queue.get_nowait()
    with pytest.raises(ValueError,match='changed'):
        await agent.answer(event)
    assert not agent.manager.client.chats
    async def foreign(*args,**kwargs):return {'reply':'Friday','citations':['not-authorized']}
    agent.intelligence.json_call=foreign
    await agent.accept('second','When?','public','')
    with pytest.raises(ValueError,match='citation'):
        await agent.answer(agent.queue.get_nowait())
    assert not agent.manager.client.chats


async def test_revocation_stops_audio_but_allows_remote_stop(client,app):
    did=domain(client,'A');fact=memory(client,did);m=meeting(client,did)
    configure(client,m['id'],did,[fact]);agent=connect_agent(client,app,m['id'])
    agent.speech_scope=agent.manager.knowledge.snapshot(agent.who,agent.mid)[4]
    socket=agent.manager.sockets[agent.cid]=Socket(agent)
    await agent.playback.start(24000)
    client.delete('/api/memories/'+fact['id'])
    with pytest.raises(ValueError,match='revoked'):
        await agent.playback.chunk(b'\0\0'*100)
    await agent.playback.stop()
    assert socket.packets[-1]['data']['action']=='stop'
    agent.manager.sockets.pop(agent.cid)


def test_meeting_memory_review_and_next_meeting_cycle(client,app):
    did=domain(client,'A');other=domain(client,'B');m=meeting(client,did);base='/api/meetings/'+m['id']
    passage=client.post(base+'/utterances',json={'speaker':'Alice','content':'We decided to release on Friday.'}).json()
    assert client.post(base+'/memory-proposals').status_code==409
    client.post(base+'/end')
    p=client.post(base+'/memory-proposals').json()[0]
    assert client.get(f'/api/domains/{did}/memories').json()==[]
    assert client.post(base+'/memory-proposals').json()[0]['id']==p['id']
    result=client.post(f"/api/proposals/{p['id']}/review",json={'decision':'approve','title':p['title'],
        'content':p['content'],'visibility':'shareable'}).json()
    saved=result['memory'];assert saved['domain_id']==did
    assert saved['provenance']['meeting_id']==m['id']
    next_meeting=meeting(client,did);configure(client,next_meeting['id'],did,[saved])
    context,_=app.state.meeting_knowledge.context(m['owner_id'],next_meeting['id'],'release')
    assert context['knowledge'][0]['content']==passage['content']
    assert configure(client,meeting(client,other)['id'],other,[saved]).status_code==403
    assert client.delete(base).status_code==200
    assert client.get(f'/api/domains/{did}/memories').json()==[]
    assert client.get('/api/proposals').json()==[]


def test_corrected_evidence_blocks_approval_and_dismiss_allows_regeneration(client):
    did=domain(client,'A');m=meeting(client,did);base='/api/meetings/'+m['id']
    u=client.post(base+'/utterances',json={'content':'Friday was proposed.'}).json()
    client.post(base+'/end');p=client.post(base+'/memory-proposals').json()[0]
    client.patch(base+'/utterances/'+u['id'],json={'content':'Monday was proposed.'})
    data={'decision':'approve','title':p['title'],'content':p['content']}
    assert client.post(f"/api/proposals/{p['id']}/review",json=data).status_code==409
    data['decision']='reject';assert client.post(f"/api/proposals/{p['id']}/review",json=data).status_code==200
    drafts=client.post(base+'/memory-proposals').json()
    assert any(p['status']=='pending' and 'Monday' in p['content'] for p in drafts)


def test_learning_filters_forged_evidence_foreign_targets_and_assistant_echo(client,app):
    did=domain(client,'A');foreign=memory(client,domain(client,'B'))
    m=meeting(client,did);base='/api/meetings/'+m['id']
    u=client.post(base+'/utterances',json={'speaker':'Alice','content':'Maybe Friday, not confirmed.'}).json()
    client.post(base+'/utterances',json={'speaker':'Echooo AI','content':'Definitely Monday.'})
    client.post(base+'/end')
    captured=[]
    async def generate(system,data,**kwargs):
        captured.append(data)
        return {'updates':[
            {'title':'Invalid','content':'Wrong','evidence_ids':['foreign'],'target_id':None,'kind':'new'},
            {'title':'Cross project','content':'Wrong','evidence_ids':[u['id']],'target_id':foreign['id'],'kind':'revision'},
            {'title':'Unconfirmed date','content':'Alice proposed Friday; it remains unconfirmed.', 'evidence_ids':[u['id']],'target_id':None,'kind':'new'}]}
    app.state.service.ai.settings.llm_provider='openai_compatible'
    app.state.service.ai.json_call=generate
    drafts=client.post(base+'/memory-proposals').json()
    assert len(drafts)==1 and drafts[0]['title']=='Unconfirmed date'
    assert 'Definitely Monday' not in str(captured) and foreign['id'] not in str(captured)


def test_foreign_owner_project_and_memory_cannot_be_selected(client,app):
    import time
    who=db.uid()
    with app.state.store.engine.begin() as c:
        c.execute(db.users.insert().values(id=who,name='foreign-owner',password='unused',created_at=time.time()))
    with app.state.store.scope(who) as r:
        d=r.add(db.domains,name='Foreign project',description='',color='sage')
        fact=r.add(db.memories,domain_id=d['id'],title='Private owner data',content='Foreign owner content',
            visibility='shareable',audiences=[],expires_at=None,source_id=None,provenance={},version=1,updated_at=time.time())
    assert client.post('/api/meetings',json={'title':'Forbidden','project_id':d['id']}).status_code==404
    own=domain(client,'Own project');m=meeting(client,own)
    assert configure(client,m['id'],own,[fact]).status_code==404
    assert configure(client,m['id'],own,reference_ids=[d['id']]).status_code==404


def test_review_cannot_overwrite_new_target_version_or_other_project(client,app):
    did=domain(client,'A');fact=memory(client,did,'Release is Friday.')
    foreign=memory(client,domain(client,'B'),'Other project')
    m=meeting(client,did);base='/api/meetings/'+m['id']
    u=client.post(base+'/utterances',json={'speaker':'Alice','content':'Release moves from Friday to Monday.'}).json()
    client.post(base+'/end')
    async def extract(*args,**kwargs):
        return {'updates':[{'title':'Release change','content':'Release is now Monday.',
            'evidence_ids':[u['id']],'target_id':fact['id'],'kind':'revision'}]}
    app.state.service.ai.settings.llm_provider='openai_compatible';app.state.service.ai.json_call=extract
    p=client.post(base+'/memory-proposals').json()[0]
    assert p['expected_version']==1
    data={'decision':'approve','title':p['title'],'content':p['content'],'target_id':foreign['id'],'expected_version':1}
    assert client.post('/api/proposals/'+p['id']+'/review',json=data).status_code==403
    client.put('/api/memories/'+fact['id'],json={'title':'Release updated','content':'Release is Tuesday.','expected_version':1,'visibility':'shareable'})
    data.update(target_id=fact['id'],expected_version=2)
    assert client.post('/api/proposals/'+p['id']+'/review',json=data).status_code==409
    assert client.get('/api/domains/'+did+'/memories').json()[0]['content']=='Release is Tuesday.'


def test_model_failure_preserves_transcript_and_creates_no_partial_drafts(client,app):
    did=domain(client,'A');m=meeting(client,did);base='/api/meetings/'+m['id']
    client.post(base+'/utterances',json={'content':'We discussed the release.'});client.post(base+'/end')
    async def fail(*args,**kwargs):raise ValueError('PRIVATE_PROVIDER_ERROR')
    app.state.service.ai.settings.llm_provider='openai_compatible';app.state.service.ai.json_call=fail
    response=client.post(base+'/memory-proposals')
    assert response.status_code==503 and 'PRIVATE_PROVIDER_ERROR' not in response.text
    assert client.get(base).json()['utterances']
    assert not client.get('/api/proposals').json()


def test_additive_schema_upgrade_preserves_existing_meetings_and_memories(tmp_path):
    import time
    url='sqlite:///'+str(tmp_path/'upgrade.db');store=db.Store(url);who=db.uid()
    with store.engine.begin() as c:
        c.execute(db.users.insert().values(id=who,name='legacy-owner',password='unused',created_at=time.time()))
    with store.scope(who) as r:
        d=r.add(db.domains,name='Legacy',description='',color='sage')
        m=r.add(db.meetings,title='Existing meeting',status='ended',revision=1)
        u=r.add(db.utterances,meeting_id=m['id'],recording_id=None,speaker='Alice',content='Preserve this passage.',start_ms=0,end_ms=0)
    db.metadata.drop_all(store.engine,tables=[db.meeting_answer_sources,db.meeting_proposal_links,db.meeting_knowledge])
    store.engine.dispose();upgraded=db.Store(url)
    with upgraded.scope(who) as r:
        assert r.get(db.meetings,m['id'])['title']=='Existing meeting'
        assert r.get(db.utterances,u['id'])['content']=='Preserve this passage.'
        assert not r.list(db.meeting_knowledge)
        assert r.get(db.domains,d['id'])['name']=='Legacy'
    upgraded.engine.dispose()


async def test_transcript_citations_show_corrections_instead_of_replacing_evidence(client,app):
    m=meeting(client);base='/api/meetings/'+m['id']
    u=client.post(base+'/utterances',json={'speaker':'Alice','content':'Friday is only a proposal.'}).json()
    agent=connect_agent(client,app,m['id']);agent.settings=replace(agent.settings,llm_provider='openai_compatible')
    async def reply(*args,**kwargs):return {'reply':'Friday is a proposal, not a commitment.','citations':[u['id']]}
    agent.intelligence.json_call=reply
    await agent.accept('cited','What did Alice say?','public','');event=agent.queue.get_nowait();await agent.answer(event)
    assert agent.events()[0]['citations'][0]['content']==u['content']
    client.patch(base+'/utterances/'+u['id'],json={'speaker':'Alice','content':'Monday is only a proposal.'})
    source=agent.events()[0]['citations'][0]
    assert source['changed'] and not source['content']
