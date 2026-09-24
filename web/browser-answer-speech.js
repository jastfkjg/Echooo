import {AnswerAudio} from './answer-audio.js?v=1';

// Receipts exist only in this capture socket. History/snapshots cannot start speech.
export class BrowserAnswerSpeech {
  constructor(options={}){
    this.error=options.error||(()=>{});this.active=null;
    this.getContext=options.getContext||(()=>null);this.getCaptureAnchor=options.getCaptureAnchor||(()=>null);
    this.Audio=options.StreamAudio||AnswerAudio;
    this.status=options.status||(()=>{});
    this.beforePlay=options.beforePlay||(()=>{});
    this.pending=new Map();this.sequence=0;this.socket=null;this.eventId=null;
  }
  attach(socket){this.close();this.socket=socket;}
  send(packet){
    if(this.socket?.readyState!==1)throw new Error('Recording disconnected. Nothing will replay automatically.');
    this.socket.send(JSON.stringify(packet));
  }
  rpc(packet){
    const request_id=String(++this.sequence);
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(request_id);reject(new Error('Playback confirmation timed out.'));},4000);
      this.pending.set(request_id,{resolve,reject,timer});
      try{this.send({...packet,request_id});}
      catch(error){clearTimeout(timer);this.pending.delete(request_id);reject(error);}
    });
  }
  async request(receipt,action,extra={}){
    const result=await this.rpc({type:'direct_speech',id:receipt.id,token:receipt.token,action,played_samples:receipt.played||0,...extra});
    if(action==='heartbeat'&&result.playback)this.playback({...receipt,action:result.playback==='paused'?'pause':'resume'});
    return result;
  }
  playback(packet){
    const run=this.active;
    if(!run||run.id!==packet.id||run.token!==packet.token||!run.authorized)return;
    if(packet.action==='pause'&&!run.paused){
      run.audio.pause();run.paused=true;
      this.status({id:run.id,status:'paused'});
    }else if(packet.action==='resume'&&run.paused){
      run.audio.resume();run.paused=false;
      this.status({id:run.id,status:'speaking'});
    }
  }
  async play(receipt){
    this.stop();
    const context=this.getContext(),run={...receipt,played:0,received:0,offerAt:context?.currentTime};
    this.active=run;
    const fail=message=>{if(this.active===run){this.error(message);this.finish('failed');}};
    try{
      run.audio=new this.Audio(context,data=>{
        if(this.active!==run)return;
        run.played=data.played_samples??run.played;
        if(data.type==='playing'&&!run.started){
          run.started=true;clearTimeout(run.startTimer);
          const timing={offer_to_first_audio_ms:(data.context_time-run.offerAt)*1000,
            output_latency_ms:(context?.outputLatency||context?.baseLatency||0)*1000};
          const anchor=this.getCaptureAnchor();
          if(anchor&&Number.isFinite(run.question_end_ms))timing.question_to_first_audio_ms=
            (data.context_time-anchor.contextTime)*1000+anchor.audioMs-run.question_end_ms;
          this.request(run,'playing',{timing}).catch(()=>fail('Playback confirmation failed.'));
        }else if(data.type==='ended'){
          if(!run.ended||!run.started)return fail('Audio playback ended early.');
          this.finish('spoken');
        }else if(data.type==='error')fail('Audio playback failed. Your text reply is still available.');
        else if(data.type==='progress'&&run.authorized&&!run.checking){
          run.checking=true;
          this.request(run,'heartbeat').then(()=>{run.lastConfirmed=performance.now();}).catch(()=>fail('Playback connection was lost.')).finally(()=>{run.checking=false;});
        }
      });
      await run.audio.start(run.sample_rate);
      if(this.active!==run)return;
      // Mark ready before requesting: ordered chunks can immediately follow the ack.
      run.authorized=true;
      run.lastConfirmed=performance.now();
      await this.request(run,'start');
      if(this.active!==run)return;
      if(!run.started)run.startTimer=setTimeout(()=>fail('Playback did not start. Check browser audio permissions.'),5000);
      run.timer=setInterval(()=>{
        if(performance.now()-run.lastConfirmed>6000)fail('Playback connection was lost.');
      },1000);
    }catch(error){fail(error.message);}
  }
  finish(action){
    const run=this.active;if(!run)return;
    this.active=null;clearTimeout(run.startTimer);clearInterval(run.timer);
    try{run.audio?.stop();}catch{}
    this.request(run,action).catch(()=>{if(action==='spoken')this.error('Playback completion could not be confirmed.');});
  }
  stop(){this.finish('cancelled');}
  configure(enabled,echoCancellation=null){this.send({type:'direct_config',enabled,echo_cancellation:echoCancellation});if(!enabled)this.cancelAnswer();}
  cancelAnswer(){this.stop();try{this.send({type:'direct_stop'});}catch{} }
  async guard(active){
    if(active)this.cancelAnswer();
    return this.rpc({type:'local_speech_guard',active});
  }
  receive(packet){
    if(packet.type==='direct_ack'){
      const item=this.pending.get(packet.request_id);
      if(item){clearTimeout(item.timer);this.pending.delete(packet.request_id);packet.ok?item.resolve(packet):item.reject(new Error(packet.error));}
    }else if(packet.type==='direct_offer'){
      this.eventId=packet.id;
      this.beforePlay();
      this.play(packet).catch(error=>this.error(error.message));
    }else if(packet.type==='direct_audio'||packet.type==='direct_audio_end'){
      const run=this.active;
      if(!run||run.id!==packet.id||run.token!==packet.token||!run.authorized)return true;
      try{
        if(packet.type==='direct_audio'){
          if(run.ended||!Number.isInteger(packet.samples)||packet.samples<=run.received||
              atob(packet.audio).length!==(packet.samples-run.received)*2)throw new Error('Invalid speech audio sequence.');
          run.received=packet.samples;run.audio.write(packet.audio);
        }else{run.ended=true;run.audio.end();}
      }catch{this.error('Audio playback failed. Your text reply is still available.');this.finish('failed');}
    }else if(packet.type==='direct_playback'){
      try{this.playback(packet);}catch(error){this.error('Playback control failed. Please ask again.');this.stop();}
    }else if(packet.type==='direct_cancel'){
      if(this.active?.id===packet.id)this.stop();
    }else if(packet.type==='direct_status'){
      this.eventId=packet.id;this.status(packet);
    }else return false;
    return true;
  }
  close(){
    this.cancelAnswer();this.socket=null;this.eventId=null;
    for(const item of this.pending.values()){clearTimeout(item.timer);item.reject(new Error('Recording disconnected.'));}
    this.pending.clear();
  }
}
