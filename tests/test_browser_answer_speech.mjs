import test from 'node:test';
import assert from 'node:assert/strict';
import {BrowserAnswerSpeech} from '../web/browser-answer-speech.js';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup({ack=true}={}){
  const packets=[],streams=[],errors=[];
  class Audio {
    constructor(context,report){this.report=report;this.chunks=[];streams.push(this);}
    async start(){}
    write(audio){this.chunks.push(audio);}
    end(){this.ended=true;}
    pause(){this.pauses=(this.pauses||0)+1;}
    resume(){this.resumes=(this.resumes||0)+1;}
    stop(){this.stopped=true;}
  }
  const speech=new BrowserAnswerSpeech({StreamAudio:Audio,error:message=>errors.push(message),
    getContext:()=>({currentTime:5,outputLatency:.01}),getCaptureAnchor:()=>({contextTime:4,audioMs:2000})});
  const socket={readyState:1,send:text=>{
    const p=JSON.parse(text);packets.push(p);
    if(ack&&p.request_id)queueMicrotask(()=>speech.receive({type:'direct_ack',request_id:p.request_id,ok:true,question:'Use Telegram.',sample_rate:24000}));
  }};
  speech.attach(socket);
  return {speech,socket,packets,streams,errors};
}
const offer={type:'direct_offer',id:'event',token:'ephemeral',sample_rate:24000,question_end_ms:1800};
const chunk={...offer,type:'direct_audio',samples:1,audio:'AQA='};
const end={...offer,type:'direct_audio_end'};

test('only live offers start streams; first output is reported separately from authorization',async()=>{
  const s=setup();
  assert.equal(s.speech.receive({type:'snapshot',browser_answers:[{status:'spoken',response:'old'}]}),false);
  s.speech.receive({type:'direct_status',id:'old',status:'spoken',response:'old'});
  assert.equal(s.streams.length,0);
  s.speech.receive(offer);await tick();
  assert.deepEqual(s.packets.filter(p=>p.action).map(p=>p.action),['start']);
  s.speech.receive(chunk);
  assert.deepEqual(s.streams[0].chunks,['AQA=']);
  s.streams[0].report({type:'playing',played_samples:1,context_time:5.25});await tick();
  const playing=s.packets.find(p=>p.action==='playing');
  assert.deepEqual(playing.timing,{offer_to_first_audio_ms:250,question_to_first_audio_ms:1450,output_latency_ms:10});
  s.speech.receive(end);s.streams[0].report({type:'ended',played_samples:1});await tick();
  assert.deepEqual(s.packets.filter(p=>p.action).map(p=>p.action),['start','playing','spoken']);
  s.speech.close();
});

test('server interruption discards late audio and completion',async()=>{
  const s=setup();s.speech.receive(offer);await tick();
  s.speech.receive({type:'direct_cancel',id:offer.id});
  s.speech.receive(chunk);s.streams[0].report({type:'ended',played_samples:1});await tick();
  assert.ok(s.streams[0].stopped);assert.equal(s.streams[0].chunks.length,0);
  assert.equal(s.packets.filter(p=>p.action==='spoken').length,0);
  assert.equal(s.packets.filter(p=>p.action==='cancelled').length,1);s.speech.close();
});

test('closing during authorization stops the initialized worklet and ignores late ack',async()=>{
  const s=setup({ack:false});s.speech.receive(offer);await tick();
  const start=s.packets.find(p=>p.action==='start');s.speech.close();
  s.speech.receive({type:'direct_ack',request_id:start.request_id,ok:true});s.speech.receive(chunk);await tick();
  assert.ok(s.streams[0].stopped);assert.equal(s.streams[0].chunks.length,0);assert.equal(s.speech.pending.size,0);
});

test('stop also cancels generation before an offer exists',()=>{
  const s=setup();s.speech.cancelAnswer();assert.equal(s.packets.at(-1).type,'direct_stop');s.speech.close();
});

test('worklet error reports failure and keeps displayed text',async()=>{
  const s=setup();let displayed;s.speech.status=p=>displayed=p.response;
  s.speech.receive({type:'direct_status',id:offer.id,status:'sending',response:'Use Telegram.'});
  s.speech.receive(offer);await tick();s.streams[0].report({type:'error'});await tick();
  assert.match(s.errors[0],/Audio playback failed/);assert.equal(displayed,'Use Telegram.');
  assert.equal(s.packets.at(-1).action,'failed');s.speech.close();
});

test('host-approved speech waits for shared guard acknowledgement',async()=>{
  const s=setup({ack:false});let ready=false;const pending=s.speech.guard(true).then(()=>ready=true);
  assert.equal(ready,false);const guard=s.packets.at(-1);assert.equal(guard.type,'local_speech_guard');
  s.speech.receive({type:'direct_ack',request_id:guard.request_id,ok:true});await pending;
  assert.equal(ready,true);s.speech.close();
});

test('receipt-scoped pause and resume preserve the same stream, including before first output',async()=>{
  const s=setup();s.speech.receive(offer);await tick();
  const command={...offer,type:'direct_playback',action:'pause'};
  s.speech.receive({...command,token:'wrong'});assert.equal(s.streams[0].pauses,undefined);
  s.speech.receive(command);s.speech.receive(command);assert.equal(s.streams[0].pauses,1);
  s.speech.receive({...command,action:'resume'});assert.equal(s.streams[0].resumes,1);
  s.speech.cancelAnswer();s.speech.receive({...command,action:'resume'});
  assert.equal(s.streams[0].resumes,1);s.speech.close();
});

test('foreign and duplicate chunks cannot inject audio; malformed stream fails closed',async()=>{
  const s=setup();s.speech.receive(offer);await tick();
  s.speech.receive({...chunk,token:'wrong'});assert.equal(s.streams[0].chunks.length,0);
  s.speech.receive(chunk);s.speech.receive(chunk);await tick();
  assert.equal(s.streams[0].chunks.length,1);assert.equal(s.speech.active,null);
  assert.equal(s.packets.at(-1).action,'failed');s.speech.close();
});
