import {serverAudioURL} from './server-audio.js?v=1';
// One-shot, owner-approved browser speech. Never resume it after navigation/reload.
export class LocalQuestionSpeech {
  constructor({api,base,changed=()=>{},error=()=>{},Audio=globalThis.Audio}){
    Object.assign(this,{api,base,changed,error,Audio});
    this.active=null;
  }
  get available(){return !!this.Audio;}
  request(receipt,action){return this.api(`${this.base}/interventions/${receipt.id}/browser-speech`,'POST',{revision:receipt.revision,token:receipt.token,action});}
  async play(receipt){
    if(!this.available)throw new Error('Local speech is not supported by this browser.');
    this.stop();
    const run={...receipt};this.active=run;this.changed();
    try{
      const result=await this.request(run,'start');
      if(this.active!==run){this.request(run,'cancelled').catch(()=>{});return;}
      if(typeof result.audio!=='string'||!result.audio)throw new Error('The speech service returned no audio. Your text reply is still available.');
      run.url=serverAudioURL(result.audio);
      const audio=new this.Audio(run.url);
      run.audio=audio;
      audio.onplaying=()=>{if(this.active===run){run.started=true;clearTimeout(run.startTimer);}};
      audio.onended=()=>{if(this.active===run)this.finish(run.started?'spoken':'failed');};
      audio.onerror=()=>{if(this.active===run){this.error('Audio playback failed. Your text reply is still available.');this.finish('failed');}};
      run.startTimer=setTimeout(()=>{if(this.active===run&&!run.started){this.error('Playback did not start. Check browser audio permissions.');this.finish('failed');}},5000);
      run.lastConfirmed=Date.now();
      run.timer=setInterval(async()=>{
        if(this.active!==run)return;
        if(Date.now()-run.lastConfirmed>6000){this.error('Playback stopped because the connection was lost.');this.finish('cancelled');return;}
        if(run.checking)return;
        run.checking=true;
        try{await this.request(run,'heartbeat');run.lastConfirmed=Date.now();}
        catch{if(this.active===run){this.error('Playback stopped. Review the latest discussion before trying again.');this.finish('cancelled');}}
        finally{run.checking=false;}
      },1000);
      await audio.play();
      this.changed();
    }catch(e){
      if(this.active===run){this.finish('failed');throw new Error(e.name==='NotAllowedError'?'Playback was blocked by the browser. Allow sound for this site and try again.':e.message);}
    }
  }
  finish(status){
    const run=this.active;if(!run)return;
    this.active=null;clearInterval(run.timer);clearTimeout(run.startTimer);
    if(run.audio){run.audio.onplaying=run.audio.onended=run.audio.onerror=null;try{run.audio.pause();}catch{}run.audio.removeAttribute('src');run.audio.load();}
    if(run.url)URL.revokeObjectURL(run.url);
    this.changed();
    this.request(run,status).then(()=>this.changed()).catch(()=>{if(status==='spoken')this.error('Playback finished, but completion could not be confirmed.');});
  }
  stop(){this.finish('cancelled');}
  sync(meeting){
    const run=this.active;if(!run)return;
    const p=meeting.interventions?.find(p=>p.id===run.id);
    if(p&&p.revision<run.revision)return; // An older refresh must not cancel a newer approval.
    if(!p||p.revision!==run.revision||!['approved','speaking'].includes(p.status)||meeting.status==='ended'||meeting.recording===false){
      this.error('Local playback was cancelled because the approval or recording changed. Nothing will replay automatically.');
      this.stop();
    }
  }
}
