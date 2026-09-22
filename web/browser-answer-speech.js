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
  request(receipt,action){return this.rpc({type:'direct_speech',id:receipt.id,token:receipt.token,action});}
  configure(enabled){this.send({type:'direct_config',enabled});if(!enabled)this.cancelAnswer();}
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
