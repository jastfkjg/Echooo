// Bounded continuous PCM playback with interpolation across packet boundaries.
class EchoooPCMBuffer {
    constructor(inputRate, outputRate) {
        this.inputRate = inputRate; this.outputRate = outputRate;
        this.ring = new Float32Array(inputRate * 4);
        this.read = 0; this.write = 0; this.count = 0; this.fraction = 0;
        this.started = false; this.finished = false; this.paused = false;
        this.played = 0; this.received = 0; this.underruns = 0;
        this.last = 0; this.fade = 0;
    }
    push(samples) {
        if (this.finished || this.count + samples.length > this.ring.length) throw new Error('Audio buffer overflow');
        for (const sample of samples) { this.ring[this.write] = sample; this.write = (this.write + 1) % this.ring.length; }
        this.count += samples.length; this.received += samples.length;
    }
    render(output) {
        const step = this.inputRate / this.outputRate;
        const ramp = Math.max(1, Math.round(this.outputRate * .005));
        for (let i = 0; i < output.length; i++) {
            if (!this.started && !this.paused && (this.count >= this.inputRate * .2 || this.finished && this.count)) {
                this.started = true; this.fade = 0;
            }
            if (this.paused || !this.started || !this.count || !this.finished && this.count < 2) {
                if (this.started && !this.paused && !this.finished) { this.underruns++; this.started = false; }
                // Ramp to zero only at an interruption/underrun/end, never per packet.
                this.last *= 1 - 1 / ramp;
                output[i] = Math.abs(this.last) < .00001 ? 0 : this.last;
                continue;
            }
            const a = this.ring[this.read], b = this.count > 1 ? this.ring[(this.read + 1) % this.ring.length] : a;
            this.fade = Math.min(1, this.fade + 1 / ramp);
            this.last = (a + (b - a) * this.fraction) * this.fade;
            output[i] = this.last;
            this.fraction += step;
            const consumed = Math.min(this.count, Math.floor(this.fraction));
            this.read = (this.read + consumed) % this.ring.length; this.count -= consumed;
            this.fraction -= consumed; this.played += consumed;
        }
    }
    status() { return {buffered_ms: this.count * 1000 / this.inputRate,
        played_samples: this.played, received_samples: this.received,
        done: this.finished && !this.count && Math.abs(this.last) < .00001, underruns: this.underruns}; }
}

class AnswerAudioProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.pcm = new EchoooPCMBuffer(options.processorOptions.sampleRate, sampleRate);
    this.first = false; this.ended = false; this.frames = 0;
    this.port.onmessage = ({data}) => {
      try {
        if(data.type === 'audio') this.pcm.push(new Float32Array(data.samples));
        if(data.type === 'end') this.pcm.finished = true;
        if(data.type === 'pause') this.pcm.paused = true;
        if(data.type === 'resume') this.pcm.paused = false;
        if(data.type === 'stop') this.ended = true;
      } catch { this.port.postMessage({type:'error'}); this.ended = true; }
    };
  }
  process(_inputs, outputs) {
    const out = outputs[0][0];
    if(this.ended) { out.fill(0); return false; }
    this.pcm.render(out);
    const progress = this.pcm.status();
    if(!this.first && progress.played_samples > 0) {
      this.first = true;
      this.port.postMessage({type:'playing', context_time:currentTime, ...progress});
    }
    this.frames += out.length;
    if(this.frames >= sampleRate / 5) {
      this.frames = 0; this.port.postMessage({type:'progress', ...progress});
    }
    if(progress.done) {
      this.ended = true; this.port.postMessage({type:'ended', ...progress});
    }
    return !this.ended;
  }
}
registerProcessor('answer-audio', AnswerAudioProcessor);
