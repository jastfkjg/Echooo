import test from 'node:test';
import assert from 'node:assert/strict';
import {LocalQuestionSpeech} from '../web/local-question-speech.js';

const receipt={id:'p',revision:2,token:'secret'};
function setup(api){
  const actions=[],muted=[],utterances=[];
  const synthesis={getVoices:()=>[],speak:u=>{utterances.push(u);u.onstart();},cancel:()=>{}};
  const speech=new LocalQuestionSpeech({api:api|| (async(url,method,data)=>{actions.push(data.action);return {question:'批准的原文',status:'speaking'};}),base:'/meetings/m',synthesis,
    Utterance:class{constructor(text){this.text=text;}},mute:value=>muted.push(value)});
  return {speech,actions,muted,utterances};
}
test('speaks only the approved response without muting capture, reports actual completion',async()=>{
  const {speech,actions,muted,utterances}=setup();
  await speech.play(receipt);
  assert.equal(utterances[0].text,'批准的原文');
  assert.equal(utterances[0].lang,'zh-CN');
  assert.deepEqual(muted,[]);
  utterances[0].onend();
  assert.deepEqual(actions,['start','spoken']);
  assert.deepEqual(muted,[]);
});
test('cancel invalidates late speech callbacks without touching capture',async()=>{
  const {speech,actions,muted,utterances}=setup();
  await speech.play(receipt);
  const late=utterances[0].onend;
  speech.stop();late();
  assert.deepEqual(actions,['start','cancelled']);
  assert.deepEqual(muted,[]);
});
test('stop while awaiting recheck never starts speech',async()=>{
  let resolve;
  const {speech,utterances}=setup(async(url,method,data)=>data.action==='start'?new Promise(r=>resolve=r):{});
  const pending=speech.play(receipt);speech.stop();
  resolve({question:'Do not play'});await pending;
  assert.equal(utterances.length,0);
});
test('old snapshots do not cancel a new approval; remote cancellation does',async()=>{
  const {speech,actions}=setup();
  await speech.play(receipt);
  speech.sync({recording:true,status:'active',interventions:[{id:'p',revision:1,status:'proposed'}]});
  assert.ok(speech.active);
  speech.sync({recording:true,status:'active',interventions:[{id:'p',revision:3,status:'cancelled'}]});
  assert.equal(speech.active,null);assert.equal(actions.at(-1),'cancelled');
});
test('stopped recording cancels speech and never claims completion',async()=>{
  const {speech,actions}=setup();await speech.play(receipt);
  speech.sync({recording:false,status:'active',interventions:[{id:'p',revision:2,status:'speaking'}]});
  assert.equal(actions.at(-1),'cancelled');
});
test('partial snapshots do not silently cancel a valid receipt',async()=>{
  const {speech}=setup();await speech.play(receipt);
  speech.sync({status:'active',interventions:[{id:'p',revision:2,status:'speaking'}]});
  assert.ok(speech.active);speech.stop();
});
test('paused synthesis is resumed before speaking and browser errors are specific',async()=>{
  const {speech,utterances}=setup();let resumed=false,message='';
  speech.synthesis.paused=true;speech.synthesis.resume=()=>resumed=true;
  speech.error=text=>message=text;
  await speech.play(receipt);assert.ok(resumed);
  utterances[0].onerror({error:'not-allowed'});
  assert.match(message,/blocked by the browser/);assert.equal(speech.active,null);
});
