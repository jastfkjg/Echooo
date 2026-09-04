import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {filterSessions, sessionStatus, domainControl, privateContextForm, bindPrivateContext} from '../web/session-ui.js';
import {sessionHeader} from '../web/chat-ui.js';

const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const helpers={esc,icon:()=>'<svg aria-hidden="true"></svg>',domainName:id=>({a:'default',b:'Product & design',c:'Research'}[id]),prefs:{}};
const chats=[{id:'1',title:'Planning',audience:'',mode:'private',domain_ids:['a'],message_count:0,status:'active',expires_at:200},
  {id:'2',title:'Follow up',audience:'Team',mode:'delegate',domain_ids:['b'],message_count:2,status:'ended',expires_at:200}];

test('Private composer omits redundant footnotes; guest privacy disclosures remain',async()=>{
  const source=await readFile(new URL('../web/app.js',import.meta.url),'utf8');
  const renderSource=source.match(/function conversation\(s, canSpeak\) \{[\s\S]+?\n\}/)[0];
  const state={guest:false};
  const render=vm.runInNewContext(`${renderSource}; conversation`,{state,sessionStatus,icon:()=>'',voiceControls:()=>'',empty:()=>''});
  const s={status:'active',mode:'private',messages:[]};
  const privateHTML=render(s,true);
  assert.doesNotMatch(privateHTML,/composer-caption|Memories are only saved|Enter to send|Shift \+ Enter/);
  assert.match(privateHTML,/aria-label="Message"/);
  assert.match(privateHTML,/aria-label="Send message"/);
  assert.match(render(s,false),/Private notes are never sent to the guest/);
  state.guest=true;
  assert.match(render(s,true),/The owner can view this transcript/);
});

test('Conversation filters support title, domain, audience, and empty chats',()=>{
  assert.deepEqual(filterSessions(chats,' plan ','all',helpers.domainName).map(s=>s.id),['1']);
  assert.deepEqual(filterSessions(chats,'TEAM','all',helpers.domainName).map(s=>s.id),['2']);
  assert.deepEqual(filterSessions(chats,'design','delegate',helpers.domainName).map(s=>s.id),['2']);
  assert.deepEqual(filterSessions(chats,'','empty',helpers.domainName).map(s=>s.id),['1']);
  assert.equal(filterSessions(chats,'missing','all',helpers.domainName).length,0);
});
test('Only delegated conversations expire; ended and revoked chats stay closed',()=>{
  assert.equal(sessionStatus(chats[0],200),'active');
  assert.equal(sessionStatus({...chats[0],expires_at:null},300),'active');
  assert.equal(sessionStatus(chats[0],199),'active');
  assert.equal(sessionStatus({...chats[1],status:'active'},200),'expired');
  assert.equal(sessionStatus({...chats[1],status:'active'},199),'active');
  assert.equal(sessionStatus({...chats[1],status:'active',expires_at:null},199),'expired');
  assert.equal(sessionStatus(chats[1],300),'ended');
  assert.equal(sessionStatus({...chats[0],status:'revoked'},300),'revoked');
  assert.equal(chats[0].status,'active');
});

test('Empty conversation states match availability and never show review',async()=>{
  const source=await readFile(new URL('../web/app.js',import.meta.url),'utf8');
  const renderSource=source.match(/function conversation\(s, canSpeak\) \{[\s\S]+?\n\}/)[0];
  const state={guest:false};
  const render=vm.runInNewContext(`${renderSource}; conversation`,{
    state,sessionStatus,icon:()=>'',voiceControls:()=>'',
    empty:(title,description)=>`<h2>${title}</h2><p>${description}</p>`,
    summaryHTML:()=>'<section>Conversation review</section>',messageHTML:m=>m.content,
  });
  const base={...chats[0],messages:[]};
  const active=render(base,true);
  assert.match(active,/Ready to talk/);assert.match(active,/id="message-form"/);
  assert.doesNotMatch(active,/Conversation review|has expired|ended-note/);
  for(const status of ['ended','revoked']){
    const html=render({...base,status},true);
    assert.match(html,/No messages were sent/);
    assert.doesNotMatch(html,/Ready to talk|Start a voice conversation|Conversation review|id="message-form"/);
  }
  const expired={...base,mode:'delegate'};
  for(const guest of [false,true]){
    state.guest=guest;
    const html=render(expired,guest);
    assert.match(html,/Authorization expired/);
    assert.doesNotMatch(html,/Ready to talk|Follow the conversation|Create an invitation|Conversation review|id="message-form"/);
  }
  state.guest=false;
  assert.match(render({...base,status:'ended',messages:[{content:'Existing message'}]},true),/Existing message[\s\S]*Conversation review/);
});

test('Refreshing a private chat with an old deadline keeps the composer connected',async()=>{
  const source=await readFile(new URL('../web/app.js',import.meta.url),'utf8');
  const refreshSource=source.match(/async function refreshSession\(\) \{[\s\S]+?\n\}/)[0];
  const state={session:{...chats[0],messages:[]},guest:false};
  let disconnected=false,rendered=false;
  const refresh=vm.runInNewContext(`${refreshSource}; refreshSession`,{
    state,sessionStatus,api:async()=>({...state.session}),$:()=>null,
    disconnect:()=>{disconnected=true;},renderSession:()=>{rendered=true;},
    appendMessage:()=>{},toast:message=>assert.fail(message),
  });
  await refresh();assert.equal(disconnected,false);assert.equal(rendered,false);
  state.session.mode='delegate';
  await refresh();assert.equal(disconnected,true);assert.equal(rendered,true);
});
test('Domain entry names the action and exposes all names accessibly',()=>{
  const html=domainControl({...chats[0],domain_ids:['a','b','c']},helpers);
  assert.match(html,/Change domains: default, Product &amp; design, Research/);
  assert.match(html,/aria-haspopup="dialog"/);assert.match(html,/>Domains</);assert.match(html,/>\+2</);
  assert.match(html,/<span class="scope-names">default<\/span>/);
  assert.doesNotMatch(html,/conversation-scope|scope-action|Change domains<|View access</);
  assert.match(domainControl(chats[1],helpers),/data-action="context"/);
});
test('Header has management actions and no tiny scope chip',()=>{
  const html=sessionHeader({...chats[0],actions:[]},helpers);
  assert.match(html,/data-action="rename-session"/);assert.match(html,/data-action="delete-session"/);
  assert.doesNotMatch(html,/scope-label/);
  assert.doesNotMatch(html,/Private conversation|session-kind/);
  assert.doesNotMatch(html,/Conversation settings|dictation-toggle|mute-toggle/);
  assert.equal((html.match(/data-action="choose-domains"/g)||[]).length,1);
  assert.ok(html.indexOf('id="session-title"') < html.indexOf('class="domain-control"'));
  assert.ok(html.indexOf('class="domain-control"') < html.indexOf('class="session-tools"'));
  assert.match(sessionHeader({...chats[1],actions:[]},helpers),/Delegated conversation/);
});
test('No-memory scope remains explicit without an overflow count',()=>{
  const html=domainControl({...chats[0],domain_ids:[]},helpers);
  assert.match(html,/>No memory</);
  assert.doesNotMatch(html,/scope-extra/);
});
test('Private picker escapes user text and collapses permission details',()=>{
  const html=privateContextForm([{id:'a',name:'<script>',description:'"quoted"',color:'sage'}],[],['a'],true,helpers);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  assert.match(html,/Chat without memory/);assert.match(html,/id="memory-access"/);
  assert.match(html,/class="picker-section advanced-options"/);assert.doesNotMatch(html,/<details[^>]+ open/);
  assert.match(html,/review every suggestion/);
  assert.doesNotMatch(html,/duration_minutes|Memory access duration|Duration &amp; goal/);
});

test('Picker preserves unchecked memories and learning preference through scope changes',()=>{
  const domains=[{id:'a',name:'default'},{id:'b',name:'Project'}],memories=[{id:'m',domain_id:'a',title:'Choice',content:'A fact'}];
  const inputs=domains.map((d,i)=>({value:d.id,checked:i===0}));
  const nodes={'input[name=allow_learning]':{checked:true},'#f-write':{value:'a'},'#without-memory':{},'.learning-destination':{},'#memory-selection-count':{},'#learning-summary':{}};
  let facts=[];
  nodes['#private-fact-picker']={set innerHTML(html){facts=html.includes('name="read_ids"')?[{value:'m',checked:html.includes('value="m" checked')}]:[];}};
  const modal={querySelector:s=>nodes[s],querySelectorAll:s=>s==='input[name=domains]'?inputs:s==='input[name=domains]:checked'?inputs.filter(i=>i.checked):s==='input[name=read_ids]'?facts:facts.filter(i=>i.checked)};
  bindPrivateContext(modal,domains,memories,['m'],helpers);
  assert.equal(nodes['#memory-selection-count'].textContent,'1 memory selected');
  facts[0].checked=false;facts[0].onchange();
  inputs[1].checked=true;inputs[1].onchange();assert.equal(facts[0].checked,false);
  nodes['#without-memory'].onchange();assert.equal(nodes['input[name=allow_learning]'].disabled,true);
  assert.equal(nodes['.learning-destination'].hidden,true);
  inputs[0].checked=true;inputs[0].onchange();
  assert.equal(facts[0].checked,false);assert.equal(nodes['input[name=allow_learning]'].checked,true);
});
