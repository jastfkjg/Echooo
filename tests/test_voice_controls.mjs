import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {Voice} from '../web/voice.js';
import {updateVoiceUI} from '../web/chat-ui.js';

class AudioContextMock {
  state='suspended';
  destination={};
  audioWorklet={addModule:async()=>{}};
  resume(){this.state='running';return Promise.resolve();}
  close(){this.state='closed';return Promise.resolve();}
  createMediaStreamSource(){return {connect(){},disconnect(){}};}
  createGain(){return {gain:{value:1},connect(){},disconnect(){}};}
}
class WorkletMock {
  messages=[];
  port={postMessage:message=>this.messages.push(message),onmessage:null};
  connect(){}
  disconnect(){}
}
function setup(getUserMedia) {
  const track={stopped:false,stop(){this.stopped=true;}};
  const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:getUserMedia||(async()=>stream)}}});
  globalThis.WebSocket={OPEN:1};
  globalThis.AudioContext=AudioContextMock;
  globalThis.AudioWorkletNode=WorkletMock;
  globalThis.SpeechSynthesisUtterance=class{constructor(text){this.text=text;}};
  const synth={cancel(){},getVoices:()=>[],speak(u){this.last=u;}};
  globalThis.window={speechSynthesis:synth};
  const socket={readyState:1,bufferedAmount:0,sent:[],send(raw){this.sent.push(typeof raw==='string'?JSON.parse(raw):raw);}};
  const voice=new Voice(socket,()=>{});
  return {voice,socket,stream,track,synth};
}

test('Start voice enables input and replies; Listening waits for capture readiness',async()=>{
  const {voice,socket,track}=setup();
  await voice.start();
  assert.equal(voice.active,true);assert.equal(voice.enabled,true);
  assert.equal(voice.micReady,false);assert.equal(voice.micPending,true);
  assert.deepEqual(socket.sent.slice(0,2),[{type:'playback.configure',enabled:true},{type:'audio.enable',dictation:false}]);
  await voice.capture();assert.equal(voice.micReady,true);assert.equal(voice.micPending,false);
  voice.end();assert.equal(track.stopped,true);assert.equal(voice.active,false);assert.equal(voice.enabled,false);
  assert.equal(voice.captureContext,null);assert.ok(socket.sent.some(e=>e.type==='interrupt'));voice.close();
});
test('End voice cancels a pending permission request without reopening the mic',async()=>{
  let resolve;const pending=new Promise(r=>resolve=r);
  const {voice,stream,track,socket}=setup(()=>pending);
  const starting=voice.start();voice.end();resolve(stream);await starting;
  assert.equal(track.stopped,true);assert.equal(voice.stream,null);
  assert.equal(voice.micPending,false);assert.equal(socket.sent.some(e=>e.type==='audio.enable'),false);voice.close();
});
test('Permission denied produces a persistent error and releases resources',async()=>{
  const {voice}=setup(async()=>{throw Object.assign(new Error(),{name:'NotAllowedError'});});
  await voice.start();assert.equal(voice.active,false);assert.equal(voice.enabled,false);
  assert.match(voice.error.message,/denied/);assert.equal(voice.captureContext,null);voice.close();
});
test('Pause mic keeps the voice session; mute changes output without stopping input',async()=>{
  const {voice,track}=setup();await voice.start();await voice.capture();
  voice.setMuted(true);assert.equal(voice.enabled,false);assert.equal(voice.micReady,true);
  voice.pauseMic();assert.equal(track.stopped,true);assert.equal(voice.active,true);assert.equal(voice.micReady,false);
  voice.setMuted(false);assert.equal(voice.enabled,true);voice.close();
});
test('Dictation mode asks for drafts and never enables playback',async()=>{
  const {voice,socket}=setup();voice.setDictation(true);await voice.start();
  assert.equal(voice.enabled,false);assert.deepEqual(socket.sent.at(-1),{type:'audio.enable',dictation:true});
  voice.setDictation(false);assert.ok(socket.sent.some(e=>e.type==='audio.mode'&&e.dictation===false));voice.close();
});
test('Browser speech reflects actual start/end and exposes playback errors',async()=>{
  const {voice,synth}=setup();await voice.start();voice.speak('你好');
  assert.equal(voice.speaking,false);assert.equal(voice.preparing,true);
  assert.equal(synth.last.lang,'zh-CN');synth.last.onstart();assert.equal(voice.speaking,true);
  synth.last.onend();assert.equal(voice.speaking,false);
  voice.speak('Hello');synth.last.onerror({error:'not-allowed'});assert.match(voice.error.message,/failed/);voice.close();
});
test('Late browser callbacks after interrupt cannot restore speaking state',async()=>{
  const {voice,synth}=setup();await voice.start();voice.speak('Hello');const utterance=synth.last;
  voice.interrupt();utterance.onstart();assert.equal(voice.speaking,false);voice.close();
});
test('Supervision-only connections never send microphone or playback controls',()=>{
  const {voice,socket}=setup();voice.canSpeak=false;voice.configureOutput();voice.close();
  assert.equal(socket.sent.length,0);
});
test('Visible controls distinguish connecting, listening, speaking, and ended voice',async()=>{
  const {voice,socket}=setup();
  const nodes=new Map();
  function node(key){if(!nodes.has(key))nodes.set(key,{dataset:{},classList:{toggle(){}},attrs:{},setAttribute(k,v){this.attrs[k]=v;},querySelector(k){return node(key+' '+k);}});return nodes.get(key);}
  const root={querySelector:node};
  socket.readyState=0;updateVoiceUI(voice,{root,icon:()=>''});
  assert.equal(node('[data-action=voice]').disabled,true);
  assert.equal(node('#voice-status').textContent,'Connecting…');
  socket.readyState=1;await voice.start();await voice.capture();updateVoiceUI(voice,{root,icon:()=>''});
  assert.equal(node('#voice-status').textContent,'Listening');
  assert.match(node('[data-action=voice]').innerHTML,/End voice/);
  voice.speaking=true;updateVoiceUI(voice,{root,icon:()=>''});
  assert.equal(node('#voice-status').textContent,'Echooo is speaking');assert.equal(node('[data-action=interrupt]').hidden,false);
  voice.end();updateVoiceUI(voice,{root,icon:()=>''});assert.equal(node('#voice-status').textContent,'Voice is off');
  assert.equal(node('[data-action=pause-mic]').hidden,true);voice.close();
});
test('PCM is ordered, reports playback, and ignores packets after stop',async()=>{
  const {voice}=setup();await voice.start();
  voice.preparePlayback(24000);voice.pcm(new ArrayBuffer(4));voice.finishPlayback();await voice.outputQueue;
  const messages=voice.playback.messages;assert.deepEqual(messages.slice(-3).map(e=>e.type),['config','audio','end']);
  voice.playback.port.onmessage({data:{type:'playing',epoch:voice.playEpoch}});assert.equal(voice.speaking,true);
  voice.playback.port.onmessage({data:{type:'ended',epoch:voice.playEpoch}});assert.equal(voice.speaking,false);
  voice.interrupt();const count=messages.length;voice.pcm(new ArrayBuffer(4));await voice.outputQueue;
  assert.equal(messages.length,count);voice.close();
});
test('An end signal waits for the worklet queue to drain',async()=>{
  let Processor;
  vm.runInNewContext(await readFile(new URL('../web/playback-worklet.js',import.meta.url),'utf8'),{
    AudioWorkletProcessor:class{port={messages:[],postMessage(m){this.messages.push(m);}};},
    sampleRate:24000,registerProcessor:(_,C)=>{Processor=C;},
  });
  const p=new Processor();
  p.port.onmessage({data:{type:'config',sampleRate:24000,epoch:2}});
  p.port.onmessage({data:{type:'audio',buffer:new Int16Array(256).fill(100).buffer,epoch:2}});
  p.port.onmessage({data:{type:'end',epoch:2}});
  p.process([],[[new Float32Array(128)]]);assert.equal(p.port.messages.at(-1).type,'playing');
  p.process([],[[new Float32Array(128)]]);assert.equal(p.port.messages.at(-1).type,'ended');
  const count=p.port.messages.length;p.process([],[[new Float32Array(128)]]);assert.equal(p.port.messages.length,count);
  p.port.onmessage({data:{type:'stop',epoch:3}});
  p.port.onmessage({data:{type:'audio',buffer:new Int16Array(4).buffer,epoch:2}});assert.equal(p.queue.length,0);
});
