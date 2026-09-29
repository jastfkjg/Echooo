import test from 'node:test';
import assert from 'node:assert/strict';
import {MeetingAudio} from '../web/meeting-audio.js';

class Track extends EventTarget {
  constructor(kind) {super();this.kind=kind;this.readyState='live';this.stops=0;}
  stop() {this.readyState='ended';this.stops++;}
  end() {this.readyState='ended';this.dispatchEvent(new Event('ended'));}
}
const stream=(...kinds)=>{
  const tracks=kinds.map(kind=>new Track(kind));
  return {getTracks:()=>tracks,getVideoTracks:()=>tracks.filter(t=>t.kind==='video'),getAudioTracks:()=>tracks.filter(t=>t.kind==='audio')};
};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

test('local-output echo cancellation only processes microphone, with safe legacy fallback',async()=>{
  for(const mode of ['all','legacy','rejected','unknown']) {
    const shared=stream('video','audio'),mic=stream('audio'),calls=[];
    const track=mic.getAudioTracks()[0];
    if(mode!=='unknown')track.getCapabilities=()=>({echoCancellation:mode==='legacy'?[true,false]:[true,false,'all']});
    let effective=true;
    track.getSettings=()=>({echoCancellation:effective});
    track.applyConstraints=async value=>{calls.push(value);if(mode==='rejected')throw new Error('Unavailable');effective='all';};
    shared.getAudioTracks()[0].applyConstraints=()=>assert.fail('Shared tab must not be filtered');
    const input=new MeetingAudio({mediaDevices:{getDisplayMedia:async()=>shared,getUserMedia:async options=>{
      assert.equal(options.audio.echoCancellation,true);return mic;
    }}});
    await input.open();
    assert.equal(input.echoCancellation,mode==='all'?'all':true);
    assert.deepEqual(calls,['all','rejected'].includes(mode)?[{echoCancellation:{exact:'all'}}]:[]);
    assert.ok([...shared.getTracks(),track].every(t=>t.readyState==='live'));
    input.close();
  }
});

test('closing while echo constraints are pending releases tracks and cannot start capture',async()=>{
  const mic=stream('audio'),pending=deferred(),track=mic.getAudioTracks()[0];
  track.getCapabilities=()=>({echoCancellation:[true,'all']});
  track.applyConstraints=()=>pending.promise;
  const input=new MeetingAudio({mediaDevices:{getUserMedia:async()=>mic}});
  const opened=input.open(false);await Promise.resolve();input.close();pending.resolve();
  await assert.rejects(opened,/cancelled/);assert.equal(track.stops,1);
});

test('tab permission is first; audio missing from a shared screen fails before microphone capture',async()=>{
  const shared=stream('video');let micCalls=0;
  const input=new MeetingAudio({mediaDevices:{getDisplayMedia:async options=>{
    assert.equal(options.video.displaySurface,'browser');assert.equal(options.monitorTypeSurfaces,'exclude');assert.equal(options.windowAudio,'exclude');assert.equal(options.systemAudio,'exclude');assert.equal(options.audio.suppressLocalAudioPlayback,false);
    assert.equal(options.selfBrowserSurface,'exclude');return shared;
  },getUserMedia:async()=>{micCalls++;}}});
  await assert.rejects(input.open(),/Share tab audio/);
  assert.equal(micCalls,0);assert.equal(shared.getTracks()[0].readyState,'ended');
});

test('microphone denial releases the already shared tab',async()=>{
  const shared=stream('video','audio');const calls=[];
  const input=new MeetingAudio({mediaDevices:{getDisplayMedia:async()=>{calls.push('tab');return shared;},getUserMedia:async()=>{
    calls.push('mic');throw Object.assign(new Error(),{name:'NotAllowedError'});
  }}});
  await assert.rejects(input.open(),/Allow microphone/);
  assert.deepEqual(calls,['tab','mic']);assert.ok(shared.getTracks().every(t=>t.stops===1));
});

test('leaving during either permission prompt stops tracks returned later',async()=>{
  for(const phase of ['tab','mic']) {
    const pending=deferred(),shared=stream('video','audio'),mic=stream('audio');let micCalls=0;
    const input=new MeetingAudio({mediaDevices:{getDisplayMedia:()=>phase==='tab'?pending.promise:Promise.resolve(shared),getUserMedia:()=>{micCalls++;return pending.promise;}}});
    const opened=input.open();await Promise.resolve();input.close();pending.resolve(phase==='tab'?shared:mic);
    await assert.rejects(opened,/cancelled/);
    assert.ok(shared.getTracks().every(t=>t.stops===1));
    assert.equal(micCalls,phase==='mic'?1:0);
    if(phase==='mic')assert.equal(mic.getTracks()[0].stops,1);
  }
});

test('ending either input or screen sharing ends the session once and releases all tracks',async()=>{
  for(const index of [0,1,2]) {
    const shared=stream('video','audio'),mic=stream('audio');let ended=0;
    const input=new MeetingAudio({mediaDevices:{getDisplayMedia:async()=>shared,getUserMedia:async()=>mic},onEnded:()=>ended++});
    await input.open();const tracks=[...shared.getTracks(),...mic.getTracks()];
    tracks[index].end();tracks[(index+1)%3].end();input.close();
    assert.equal(ended,1);assert.ok(tracks.every(t=>t.stops===1));
  }
});

test('sharing ends during microphone permission: late mic is released and recording cannot start',async()=>{
  const shared=stream('video','audio'),mic=stream('audio'),pending=deferred();
  const input=new MeetingAudio({mediaDevices:{getDisplayMedia:async()=>shared,getUserMedia:()=>pending.promise}});
  const opened=input.open();await Promise.resolve();shared.getTracks()[0].end();pending.resolve(mic);
  await assert.rejects(opened,/cancelled/);assert.equal(mic.getTracks()[0].stops,1);
});

test('microphone-only mode works without display capture; mixed sources have mono downmix and headroom',async()=>{
  for(const includeTab of [false,true]) {
    const shared=stream('video','audio'),mic=stream('audio'),sources=[],gains=[];
    const input=new MeetingAudio({mediaDevices:{getDisplayMedia:includeTab?async()=>shared:undefined,getUserMedia:async()=>mic}});
    await input.open(includeTab);
    const node=()=>({connect(target){this.target=target;},disconnect(){this.disconnected=true;}});
    const context={createMediaStreamSource(s){const n=node();n.stream=s;sources.push(n);return n;},createGain(){const n={...node(),gain:{value:1}};gains.push(n);return n;}};
    const destination={};input.connect(context,destination);
    assert.deepEqual(sources.map(s=>s.stream),includeTab?[shared,mic]:[mic]);
    for(const gain of gains){assert.equal(gain.channelCount,1);assert.equal(gain.channelCountMode,'explicit');assert.equal(gain.gain.value,includeTab?0.5:1);assert.equal(gain.target,destination);}
    input.close();assert.ok([...sources,...gains].every(n=>n.disconnected));
  }
});

test('unsupported surfaces release all tracks before requesting microphone, even with audio',async()=>{
  for(const surface of ['window','monitor']) {
    const shared=stream('video','audio');let micCalls=0;
    shared.getVideoTracks()[0].getSettings=()=>({displaySurface:surface});
    const input=new MeetingAudio({mediaDevices:{getDisplayMedia:async()=>shared,getUserMedia:async()=>{micCalls++;}}});
    await assert.rejects(input.open(),/Choose a Chrome tab, not a window or screen/);
    assert.equal(micCalls,0);assert.ok(shared.getTracks().every(t=>t.stops===1));
  }
});
