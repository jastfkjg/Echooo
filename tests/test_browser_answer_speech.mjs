import test from 'node:test';
import assert from 'node:assert/strict';
import {BrowserAnswerSpeech} from '../web/browser-answer-speech.js';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup({ack=true}={}){
  const packets=[],utterances=[],errors=[];
  let cancelled=0;
  const speech=new BrowserAnswerSpeech({
    synthesis:{getVoices:()=>[],speak:u=>{utterances.push(u);u.onstart();},cancel:()=>cancelled++},
    Utterance:class{constructor(text){this.text=text;}},error:message=>errors.push(message),
  });
  const socket={readyState:1,send:text=>{
    const p=JSON.parse(text);packets.push(p);
    if(ack&&p.request_id)queueMicrotask(()=>speech.receive({type:'direct_ack',request_id:p.request_id,ok:true,question:'Use Telegram.'}));
  }};
  speech.attach(socket);
  return {speech,socket,packets,utterances,errors,get cancelled(){return cancelled;}};
}
const offer={type:'direct_offer',id:'event',token:'ephemeral'};

test('only a live offer starts exact reply audio; snapshots and status never replay',async()=>{
  const s=setup();
  assert.equal(s.speech.receive({type:'snapshot',browser_answers:[{status:'spoken',response:'old'}]}),false);
  s.speech.receive({type:'direct_status',id:'old',status:'spoken',response:'old'});
  assert.equal(s.utterances.length,0);
  s.speech.receive(offer);await tick();
  assert.equal(s.utterances[0].text,'Use Telegram.');
  s.utterances[0].onend();await tick();
  assert.deepEqual(s.packets.filter(p=>p.action).map(p=>p.action),['start','spoken']);
  s.speech.close();
});

test('server interruption cancels synthesis and late completion cannot mark spoken',async()=>{
  const s=setup();s.speech.receive(offer);await tick();
  const late=s.utterances[0].onend;
  s.speech.receive({type:'direct_cancel',id:offer.id});late();await tick();
  assert.equal(s.cancelled,1);
  assert.equal(s.packets.filter(p=>p.action==='spoken').length,0);
  assert.equal(s.packets.filter(p=>p.action==='cancelled').length,1);
  s.speech.close();
});

test('closing while waiting for start prevents playback even after late acknowledgement',async()=>{
  const s=setup({ack:false});s.speech.receive(offer);
  const start=s.packets.find(p=>p.action==='start');
  s.speech.close();
  s.speech.receive({type:'direct_ack',request_id:start.request_id,ok:true,question:'Never play'});
  await tick();
  assert.equal(s.utterances.length,0);assert.equal(s.speech.pending.size,0);
});

test('stop cancels pending generation even before an utterance exists',()=>{
  const s=setup();s.speech.cancelAnswer();
  assert.equal(s.packets.at(-1).type,'direct_stop');s.speech.close();
});

test('browser playback errors report failure and preserve the response text',async()=>{
  const s=setup();let displayed;
  s.speech.status=p=>displayed=p.response;
  s.speech.receive({type:'direct_status',id:offer.id,status:'sending',response:'Use Telegram.'});
  s.speech.receive(offer);await tick();
  s.utterances[0].onerror({error:'not-allowed'});await tick();
  assert.match(s.errors[0],/blocked by the browser/);
  assert.equal(displayed,'Use Telegram.');
  assert.equal(s.packets.at(-1).action,'failed');s.speech.close();
});

test('host-approved speech waits for shared guard acknowledgement',async()=>{
  const s=setup({ack:false});let ready=false;
  const pending=s.speech.guard(true).then(()=>ready=true);
  assert.equal(ready,false);
  const guard=s.packets.at(-1);
  assert.equal(guard.type,'local_speech_guard');assert.equal(guard.active,true);
  s.speech.receive({type:'direct_ack',request_id:guard.request_id,ok:true});await pending;
  assert.equal(ready,true);s.speech.close();
});
