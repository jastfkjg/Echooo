// Only checked server replies reach speech output. Microphone use is opt-in.
export class Voice {
  constructor(socket, notify) {
    this.socket=socket;this.notify=notify;this.enabled=false;this.stream=null;
    this.captureContext=null;this.playContext=null;this.worklet=null;this.playback=null;
    this.closed=false;this.micPending=false;this.playReady=null;this.playEpoch=0;
  }
  async toggleMic() {
    if(this.micPending||this.closed)return false;
    if(this.stream){this.stopMic();this.socket.send(JSON.stringify({type:'audio.disable'}));return false;}
    this.micPending=true;
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1}});
      if(this.closed||this.socket.readyState!==WebSocket.OPEN){stream.getTracks().forEach(t=>t.stop());return false;}
      this.stream=stream;this.socket.send(JSON.stringify({type:'audio.enable'}));return true;
    }finally{this.micPending=false;}
  }
  async capture(rate=16000) {
    if(!this.stream||this.closed||this.captureContext)return;
    const context=new AudioContext();this.captureContext=context;
    try{
      await context.audioWorklet.addModule('/static/capture-worklet.js');
      if(this.closed||!this.stream||this.captureContext!==context){await context.close().catch(()=>{});return;}
      this.worklet=new AudioWorkletNode(context,'pcm16-capture',{processorOptions:{targetSampleRate:rate,chunkSamples:Math.round(rate/10)}});
      this.worklet.port.onmessage=({data})=>{if(!this.closed&&this.socket.readyState===WebSocket.OPEN&&this.socket.bufferedAmount<160000)this.socket.send(data);};
      this.source=context.createMediaStreamSource(this.stream);this.source.connect(this.worklet);
      this.silent=context.createGain();this.silent.gain.value=0;this.worklet.connect(this.silent);this.silent.connect(context.destination);
      await context.resume();
    }catch{this.stopMic();if(this.socket.readyState===WebSocket.OPEN)this.socket.send(JSON.stringify({type:'audio.disable'}));this.notify('麦克风初始化失败，请使用文字输入。');}
  }
  speak(text) {
    if(!this.enabled||this.closed||!('speechSynthesis' in window))return;
    window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(text);
    u.lang=/[\u4e00-\u9fff]/.test(text)?'zh-CN':'en-US';
    const voices=window.speechSynthesis.getVoices();u.voice=voices.find(v=>v.lang.startsWith(u.lang.slice(0,2))&&v.localService)||voices.find(v=>v.lang.startsWith(u.lang.slice(0,2)))||null;
    window.speechSynthesis.speak(u);
  }
  async preparePlayback(rate) {
    if(!this.enabled||this.closed)return;
    const epoch=this.playEpoch;
    if(!this.playReady){
      this.playReady=(async()=>{
        const context=new AudioContext();this.playContext=context;
        await context.audioWorklet.addModule('/static/playback-worklet.js');
        if(this.closed||this.playContext!==context)return;
        this.playback=new AudioWorkletNode(context,'pcm16-playback');this.playback.connect(context.destination);
      })().catch(()=>{this.playReady=null;this.notify('音频播放暂不可用，请阅读文字回复。');});
    }
    await this.playReady;
    if(this.closed||epoch!==this.playEpoch||!this.playback)return;
    this.playback.port.postMessage({type:'config',sampleRate:rate});await this.playContext.resume();
  }
  async pcm(buffer) {
    const epoch=this.playEpoch;await this.playReady;
    if(this.enabled&&!this.closed&&epoch===this.playEpoch&&this.playback)this.playback.port.postMessage({type:'audio',buffer},[buffer]);
  }
  stopPlayback(){this.playEpoch++;if('speechSynthesis'in window)window.speechSynthesis.cancel();this.playback?.port.postMessage({type:'stop'});}
  stopMic(){this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;this.source?.disconnect();this.worklet?.disconnect();this.captureContext?.close().catch(()=>{});this.captureContext=null;this.worklet=null;}
  close(){this.closed=true;this.stopPlayback();this.stopMic();this.playContext?.close().catch(()=>{});this.playContext=null;this.playback=null;}
}
