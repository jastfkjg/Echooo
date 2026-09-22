import {LocalQuestionSpeech} from './local-question-speech.js?v=3';

// Receipts exist only in this capture socket. History/snapshots cannot start speech.
export class BrowserAnswerSpeech extends LocalQuestionSpeech {
  constructor(options={}){
    super(options);
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
  async request(receipt,action){
    const result=await this.rpc({type:'direct_speech',id:receipt.id,token:receipt.token,action});
    if(action==='heartbeat'&&result.playback)this.playback({...receipt,action:result.playback==='paused'?'pause':'resume'});
    return result;
  }
  playback(packet){
    const run=this.active;
    if(!run||run.id!==packet.id||run.token!==packet.token||!run.started)return;
    if(packet.action==='pause'&&!run.paused){
      this.synthesis.pause();run.paused=true;
      this.status({id:run.id,status:'paused'});
    }else if(packet.action==='resume'&&run.paused){
      this.synthesis.resume();run.paused=false;
      this.status({id:run.id,status:'speaking'});
    }
  }
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
