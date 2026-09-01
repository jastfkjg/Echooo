class PCM16CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = options.processorOptions?.targetSampleRate || 16000;
    this.chunkSamples = options.processorOptions?.chunkSamples || 1600;
    this.buffer = new Int16Array(this.chunkSamples);
    this.offset = 0;
    this.phase = 0;
    this.sum = 0;
    this.count = 0;
    this.enabled = true;
    this.port.onmessage = ({ data }) => {
      if (data?.type === "enabled") this.enabled = Boolean(data.value);
    };
  }

  process(inputs) {
    if (!this.enabled) return true;
    const input = inputs[0]?.[0];
    if (!input) return true;

    for (let index = 0; index < input.length; index += 1) {
      this.sum += input[index];
      this.count += 1;
      this.phase += this.targetRate;
      if (this.phase < sampleRate) continue;

      this.phase -= sampleRate;
      const value = Math.max(-1, Math.min(1, this.sum / this.count));
      this.buffer[this.offset] = value < 0 ? value * 0x8000 : value * 0x7fff;
      this.offset += 1;
      this.sum = 0;
      this.count = 0;

      if (this.offset === this.buffer.length) {
        const ready = this.buffer;
        this.port.postMessage(ready.buffer, [ready.buffer]);
        this.buffer = new Int16Array(this.chunkSamples);
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm16-capture", PCM16CaptureProcessor);

