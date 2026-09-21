// One-shot, owner-approved browser speech. Never resume it after navigation/reload.
export class LocalQuestionSpeech {
  constructor({api,base,changed=()=>{},error=()=>{},synthesis=globalThis.speechSynthesis,Utterance=globalThis.SpeechSynthesisUtterance}){
    Object.assign(this,{api,base,changed,error,synthesis,Utterance});
    this.active=null;
  }
  get available(){return !!(this.synthesis&&this.Utterance);}
  request(receipt,action){return this.api(`${this.base}/interventions/${receipt.id}/browser-speech`,'POST',{revision:receipt.revision,token:receipt.token,action});}
  async play(receipt){
    if(!this.available)throw new Error('Local speech is not supported by this browser.');
    this.stop();
    const run={...receipt};this.active=run;this.changed();
    try{
      const result=await this.request(run,'start');
      if(this.active!==run){this.request(run,'cancelled').catch(()=>{});return;}
      const utterance=new this.Utterance(result.question);
      run.utterance=utterance;
      utterance.lang=/[\u4e00-\u9fff]/.test(result.question)?'zh-CN':'en-US';
      const voices=this.synthesis.getVoices();
      utterance.voice=voices.find(v=>v.localService&&v.lang.startsWith(utterance.lang.slice(0,2)))||voices.find(v=>v.lang.startsWith(utterance.lang.slice(0,2)))||null;
      utterance.onstart=()=>{if(this.active===run){run.started=true;clearTimeout(run.startTimer);}};
      utterance.onend=()=>{if(this.active===run)this.finish(run.started?'spoken':'failed');};
      utterance.onerror=()=>{if(this.active===run){this.error('Local playback failed. Review the question to try again.');this.finish('failed');}};
      run.startTimer=setTimeout(()=>{if(this.active===run&&!run.started){this.error('Playback did not start. Check browser audio permissions and review again.');this.finish('failed');}},5000);
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
      this.synthesis.speak(utterance);
      this.changed();
    }catch(e){
      if(this.active===run){this.finish('failed');throw e;}
    }
  }
  finish(status){
    const run=this.active;if(!run)return;
    this.active=null;clearInterval(run.timer);clearTimeout(run.startTimer);
    if(run.utterance){run.utterance.onstart=run.utterance.onend=run.utterance.onerror=null;this.synthesis.cancel();}
    this.changed();
    this.request(run,status).then(()=>this.changed()).catch(()=>{if(status==='spoken')this.error('Playback finished, but completion could not be confirmed.');});
  }
  stop(){this.finish('cancelled');}
  sync(meeting){
    const run=this.active;if(!run)return;
    const p=meeting.interventions?.find(p=>p.id===run.id);
    if(p&&p.revision<run.revision)return; // An older refresh must not cancel a newer approval.
    if(!p||p.revision!==run.revision||!['approved','speaking'].includes(p.status)||meeting.status==='ended'||!meeting.recording)this.stop();
  }
}
