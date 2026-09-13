// The same PCM engine runs in AudioWorklet and in the offline continuity tests.
// Input samples retain their original rate; interpolation crosses packet boundaries.
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

const echoooWorkletSource = `${EchoooPCMBuffer.toString()}
class EchoooProcessor extends AudioWorkletProcessor {
 constructor() { super(); this.pcm = null; this.port.onmessage = ({data:m}) => {
   try {
    if (m.action === 'start') this.pcm = new EchoooPCMBuffer(m.sample_rate, sampleRate);
    else if (m.action === 'chunk') this.pcm.push(m.samples);
    else if (m.action === 'finish') this.pcm.finished = true;
    else if (m.action === 'pause') this.pcm.paused = true;
    else if (m.action === 'resume') { this.pcm.paused = false; this.pcm.fade = 0; }
    else if (m.action === 'stop') this.pcm = null;
    this.port.postMessage({request:m.request, ...this.pcm?.status()});
   } catch (_) { this.port.postMessage({request:m.request,error:'Invalid audio stream'}); }
 }; }
 process(inputs, outputs) { const out=outputs[0][0]; if(this.pcm) this.pcm.render(out); else out.fill(0); return true; }
}
registerProcessor('echooo-continuous-pcm', EchoooProcessor);`;

function installEchoooStreamingAudio(BotOutputManager) {
    BotOutputManager.prototype.echoooAudio = async function(message) {
        if (!this.echoooWorklet) {
            this._createSourceAudioTrack();
            // Bot speech belongs only on its virtual microphone, never local speakers.
            try { this.gainNode.disconnect(this.audioContext.destination); } catch (_) {}
            const url = URL.createObjectURL(new Blob([echoooWorkletSource], {type:'text/javascript'}));
            try { await this.audioContext.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
            this.echoooWorklet = new AudioWorkletNode(this.audioContext, 'echooo-continuous-pcm',
                {numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[1]});
            this.echoooWorklet.connect(this.gainNode);
            this.echoooRequests = new Map(); this.echoooRequestId = 0;
            this.echoooWorklet.port.onmessage = ({data}) => {
                const done = this.echoooRequests.get(data.request);
                if (done) { this.echoooRequests.delete(data.request); done(data); }
            };
        }
        if (message.action === 'start') {
            this.echoooStreamId = message.stream_id;
            await this.audioContext.resume();
            // Open once per answer, not once per PCM packet.
            this.ensureMicOn();
        } else if (message.stream_id !== this.echoooStreamId) throw new Error('Stale audio stream');
        const data = {...message, request: ++this.echoooRequestId};
        if (data.action === 'chunk') {
            const bytes = atob(data.chunk); delete data.chunk;
            if (bytes.length % 2) throw new Error('Incomplete PCM sample');
            data.samples = new Float32Array(bytes.length / 2);
            for(let i=0;i<data.samples.length;i++) {
                let value = bytes.charCodeAt(i*2) | bytes.charCodeAt(i*2+1)<<8;
                if (value >= 32768) value -= 65536;
                data.samples[i] = value / 32768;
            }
        }
        const result = await new Promise((resolve, reject) => {
            const timer = setTimeout(()=>{this.echoooRequests.delete(data.request);reject(new Error('Audio worklet timeout'));},3000);
            this.echoooRequests.set(data.request, value=>{clearTimeout(timer);value.error?reject(new Error(value.error)):resolve(value);});
            this.echoooWorklet.port.postMessage(data, data.samples ? [data.samples.buffer] : []);
        });
        if (message.action === 'stop' || result.done) this.disableMic();
        return result;
    };
}
if (typeof module !== 'undefined') module.exports = {EchoooPCMBuffer, installEchoooStreamingAudio};
