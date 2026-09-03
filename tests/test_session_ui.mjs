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
  const render=vm.runInNewContext(`${renderSource}; conversation`,{state,icon:()=>'',voiceControls:()=>'',empty:()=>''});
  const s={status:'active',messages:[]};
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
test('Expired status replaces Active without changing stored status',()=>{
  assert.equal(sessionStatus(chats[0],200),'expired');
  assert.equal(sessionStatus(chats[0],199),'active');
  assert.equal(sessionStatus(chats[1],300),'ended');
  assert.equal(chats[0].status,'active');
});
test('Domain entry names the action and exposes all names accessibly',()=>{
  const html=domainControl({...chats[0],domain_ids:['a','b','c']},helpers);
  assert.match(html,/Change domains: default, Product &amp; design, Research/);
  assert.match(html,/aria-haspopup="dialog"/);assert.match(html,/>Domains</);assert.match(html,/>\+1</);
  assert.match(domainControl(chats[1],helpers),/data-action="context"/);
});
test('Header has management actions and no tiny scope chip',()=>{
  const html=sessionHeader({...chats[0],actions:[]},helpers);
  assert.match(html,/data-action="rename-session"/);assert.match(html,/data-action="delete-session"/);
  assert.doesNotMatch(html,/scope-label/);
});
test('Private picker escapes user text and collapses permission details',()=>{
  const html=privateContextForm([{id:'a',name:'<script>',description:'"quoted"',color:'sage'}],[],['a'],true,helpers);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  assert.match(html,/Chat without memory/);assert.match(html,/id="memory-access"/);
  assert.match(html,/class="picker-section advanced-options"/);assert.doesNotMatch(html,/<details[^>]+ open/);
  assert.match(html,/review every suggestion/);
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
