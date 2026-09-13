import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {EchoooPCMBuffer}=createRequire(import.meta.url)('../deploy/attendee/streaming-audio.js');

test('continuous sine survives irregular packet boundaries without periodic clicks',()=>{
  const rate=24000, outputRate=48000, pcm=new EchoooPCMBuffer(rate,outputRate);
  const source=Float32Array.from({length:rate*2},(_,i)=>.6*Math.sin(2*Math.PI*440*i/rate));
  const lengths=[4800,137,463,5900,111,4321];let offset=0;
  while(offset<source.length){const n=lengths[offset%lengths.length];pcm.push(source.subarray(offset,offset+n));offset+=n;}
  pcm.finished=true;
  const rendered=new Float32Array(source.length*2);
  for(let i=0;i<rendered.length;i+=128)pcm.render(rendered.subarray(i,i+128));
  let maxError=0;
  for(let i=480;i<rendered.length-4;i++){
    const x=i/2,expected=(source[Math.floor(x)]+source[Math.ceil(x)])/2;
    maxError=Math.max(maxError,Math.abs(rendered[i]-expected));
  }
  assert.ok(maxError<1e-6,`packet-boundary distortion ${maxError}`);
  assert.equal(pcm.played,source.length);assert.equal(pcm.underruns,0);
});
test('200 ms prebuffer absorbs jitter and underflow counts recovery, not every frame',()=>{
  const pcm=new EchoooPCMBuffer(16000,48000),out=new Float32Array(480);
  pcm.push(new Float32Array(1600).fill(.4));pcm.render(out);assert.ok(out.every(x=>x===0));
  pcm.push(new Float32Array(1600).fill(.4));pcm.render(out);assert.ok(out.at(-1)>.39);
  for(let i=0;i<40;i++)pcm.render(out);
  assert.equal(pcm.underruns,1);
  pcm.push(new Float32Array(4800).fill(.4));pcm.render(out);assert.ok(out.at(-1)>.39);
});
test('temporary pause retains samples and resume continues at the same position',()=>{
  const pcm=new EchoooPCMBuffer(24000,48000),out=new Float32Array(480);
  pcm.push(new Float32Array(12000).fill(.3));pcm.render(out);
  const played=pcm.played;pcm.paused=true;
  for(let i=0;i<20;i++)pcm.render(out);
  assert.equal(pcm.played,played);assert.ok(Math.abs(out.at(-1))<.00001);
  pcm.paused=false;pcm.fade=0;pcm.render(out);assert.ok(pcm.played>played);
});
test('short final tail drains exactly and oversized buffers are rejected',()=>{
  const pcm=new EchoooPCMBuffer(24000,44100),out=new Float32Array(128);
  pcm.push(new Float32Array(1234).fill(.2));pcm.finished=true;
  for(let i=0;i<100;i++)pcm.render(out);
  assert.equal(pcm.played,1234);assert.equal(pcm.status().done,true);
  const full=new EchoooPCMBuffer(8000,48000);
  assert.throws(()=>full.push(new Float32Array(32001)),/overflow/);
});
