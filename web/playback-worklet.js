class PCM16PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.current = null;
    this.offset = 0;
    this.sourceRate = 24000;
    this.epoch = 0;
    this.playing = false;
    this.ended = false;
    this.port.onmessage = ({ data }) => {
      if (data?.type === "config") {
        this.sourceRate = data.sampleRate || 24000;
        this.epoch = data.epoch;
        this.ended = false;
      } else if (data?.type === "audio") {
        if (data.epoch !== this.epoch) return;
        this.queue.push(this.resample(new Int16Array(data.buffer)));
      } else if (data?.type === "end") {
        if (data.epoch === this.epoch) this.ended = true;
      } else if (data?.type === "stop") {
        this.epoch = data.epoch;
        this.playing = false;
        this.ended = false;
        this.queue.length = 0;
        this.current = null;
        this.offset = 0;
      }
    };
  }

  resample(pcm) {
    if (this.sourceRate === sampleRate) {
      return Float32Array.from(pcm, (value) => value / 32768);
    }
    const outputLength = Math.max(1, Math.floor(pcm.length * sampleRate / this.sourceRate));
    const output = new Float32Array(outputLength);
    const ratio = this.sourceRate / sampleRate;
    for (let index = 0; index < outputLength; index += 1) {
      const position = index * ratio;
      const left = Math.floor(position);
      const right = Math.min(left + 1, pcm.length - 1);
      const fraction = position - left;
      output[index] = ((pcm[left] * (1 - fraction)) + (pcm[right] * fraction)) / 32768;
    }
    return output;
  }

  process(_inputs, outputs) {
    const channel = outputs[0]?.[0];
    if (!channel) return true;
    channel.fill(0);
    let writeAt = 0;
    while (writeAt < channel.length) {
      if (!this.current || this.offset >= this.current.length) {
        this.current = this.queue.shift() || null;
        this.offset = 0;
        if (!this.current) break;
      }
      const count = Math.min(channel.length - writeAt, this.current.length - this.offset);
      if (!this.playing) {
        this.playing = true;
        this.port.postMessage({type: 'playing', epoch: this.epoch});
      }
      channel.set(this.current.subarray(this.offset, this.offset + count), writeAt);
      this.offset += count;
      writeAt += count;
    }
    if (this.ended && !this.queue.length && (!this.current || this.offset >= this.current.length)) {
      this.ended = false;
      this.playing = false;
      this.port.postMessage({type: 'ended', epoch: this.epoch});
    }
    return true;
  }
}

registerProcessor("pcm16-playback", PCM16PlaybackProcessor);
