const modules = new WeakMap();

export class AnswerAudio {
  constructor(context, report) { this.context=context; this.report=report; this.closed=false; }
  async start(rate) {
    const context=this.context;
    if(!context?.audioWorklet)throw new Error('Streaming playback is unavailable.');
    if(!modules.has(context))modules.set(context,context.audioWorklet.addModule('/static/answer-audio-worklet.js?v=1').catch(error=>{modules.delete(context);throw error;}));
    await modules.get(context);
    if(this.closed)return;
    await context.resume();
    if(this.closed)return;
    if(context.state!=='running')throw new Error('Allow sound for this site and try again.');
    this.node=new AudioWorkletNode(context,'answer-audio',{numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[1],processorOptions:{sampleRate:rate}});
    this.node.port.onmessage=({data})=>{if(!this.closed)this.report(data);};
    this.node.connect(context.destination);
  }
  write(encoded) {
    const bytes=atob(encoded);
    if(!bytes.length||bytes.length%2)throw new Error('Invalid speech audio.');
    const samples=new Float32Array(bytes.length/2);
    for(let i=0;i<samples.length;i++){
      let value=bytes.charCodeAt(i*2)|(bytes.charCodeAt(i*2+1)<<8);
      if(value>=32768)value-=65536;
      samples[i]=value/32768;
    }
    this.node.port.postMessage({type:'audio',samples:samples.buffer},[samples.buffer]);
  }
  end(){this.node.port.postMessage({type:'end'});}
  pause(){this.node.port.postMessage({type:'pause'});}
  resume(){this.node.port.postMessage({type:'resume'});}
  stop(){
    this.closed=true;
    if(this.node){this.node.port.onmessage=null;this.node.port.postMessage({type:'stop'});this.node.disconnect();this.node.port.close();}
  }
}
