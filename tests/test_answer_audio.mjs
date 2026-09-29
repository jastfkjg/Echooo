import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

function worklet(){
  const messages=[];let Processor;
  const context=vm.createContext({sampleRate:48000,currentTime:1,Float32Array,
    AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>messages.push(m)};}},
    registerProcessor:(_name,p)=>{Processor=p;}});
  vm.runInContext(readFileSync(new URL('../web/answer-audio-worklet.js',import.meta.url),'utf8'),context);
  const processor=new Processor({processorOptions:{sampleRate:24000}});
  const send=data=>processor.port.onmessage({data});
  const render=()=>{const out=new Float32Array(128);processor.process([],[ [out] ]);context.currentTime+=128/48000;return out;};
  return {messages,send,render};
}

test('first output waits for prebuffer, occurs before stream end, and pause retains samples',()=>{
  const w=worklet();w.send({type:'audio',samples:new Float32Array(2400).fill(.5).buffer});
  assert.ok(w.render().every(x=>x===0));assert.ok(!w.messages.some(m=>m.type==='playing'));
  w.send({type:'pause'});w.send({type:'audio',samples:new Float32Array(2400).fill(.5).buffer});
  assert.ok(w.render().every(x=>x===0));w.send({type:'resume'});w.render();
  assert.equal(w.messages.filter(m=>m.type==='playing').length,1);
  assert.ok(w.messages.find(m=>m.type==='playing').context_time>=1);
  w.send({type:'end'});for(let i=0;i<200;i++)w.render();
  assert.equal(w.messages.filter(m=>m.type==='ended').length,1);
  assert.equal(w.messages.find(m=>m.type==='ended').played_samples,4800);
});

test('short tails drain, while overflow and Stop cannot output stale data',()=>{
  const w=worklet();w.send({type:'audio',samples:new Float32Array(12).fill(.5).buffer});w.send({type:'end'});
  for(let i=0;i<50;i++)w.render();
  assert.equal(w.messages.find(m=>m.type==='ended').played_samples,12);
  const stopped=worklet();stopped.send({type:'audio',samples:new Float32Array(4800).fill(.5).buffer});stopped.send({type:'stop'});
  assert.ok(stopped.render().every(x=>x===0));assert.equal(stopped.messages.length,0);
  const full=worklet();full.send({type:'audio',samples:new Float32Array(24000*5).buffer});
  assert.equal(full.messages.at(-1).type,'error');assert.ok(full.render().every(x=>x===0));
});

test('capture clock anchors are opt-in and never alter ordinary conversation PCM packets',()=>{
  const source=readFileSync(new URL('../web/capture-worklet.js',import.meta.url),'utf8');
  const capture=reportAnchors=>{
    const messages=[];let Processor;
    vm.runInNewContext(source,{sampleRate:16000,currentTime:2,Int16Array,
      AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>messages.push(m)};}},
      registerProcessor:(_n,p)=>Processor=p});
    const p=new Processor({processorOptions:{targetSampleRate:16000,chunkSamples:1600,reportAnchors}});
    p.process([[new Float32Array(1600).fill(.25)]]);return messages;
  };
  const regular=capture(false),meeting=capture(true);
  assert.equal(regular.length,1);assert.ok(regular[0] instanceof ArrayBuffer);
  assert.equal(meeting.length,2);assert.equal(meeting[0].type,'capture_anchor');
  assert.equal(meeting[0].audioMs,100);assert.equal(meeting[0].contextTime,2.1);
  assert.deepEqual(new Int16Array(regular[0]),new Int16Array(meeting[1]));
});
