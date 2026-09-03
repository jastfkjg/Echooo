// Only checked server replies reach speech output. Recording is always opt-in.
export class Voice {
  constructor(socket, notify, onChange = () => {}) {
    Object.assign(this, {socket, notify, onChange, canSpeak: true, active: false, enabled: false,
      muted: false, dictation: false, closed: false, micPending: false, micReady: false,
      thinking: false, speaking: false, preparing: false, error: null, stream: null,
      captureContext: null, playContext: null, playReady: null, playback: null,
      micEpoch: 0, playEpoch: 0, receivingAudio: false, outputQueue: Promise.resolve()});
  }
  changed() { this.onChange(this); }
  send(event) {
    if (this.canSpeak && this.socket.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(event));
  }
  configureOutput() {
    this.enabled = this.active && !this.muted && !this.dictation && !this.closed;
    this.send({type: 'playback.configure', enabled: this.enabled});
  }
  fail(message, kind = 'playback') {
    if (this.closed) return;
    if (kind === 'microphone') this.end();
    else this.stopPlayback();
    this.error = {message, kind};
    this.changed();
  }
  async start() {
    if (this.closed || this.active) return;
    this.active = true;
    this.error = null;
    this.configureOutput();
    // Unlock output during the click, not later in a WebSocket callback.
    if (this.enabled) this.unlockPlayback().catch(() => {
      if (this.active) this.fail('Audio playback is blocked. Click Retry audio to enable it.');
    });
    await this.startMic();
  }
  async startMic() {
    if (this.closed || !this.active || this.stream || this.micPending) return;
    const epoch = ++this.micEpoch;
    this.micPending = true;
    this.changed();
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported');
      const context = new AudioContext();
      this.captureContext = context;
      const resumed = context.resume().catch(() => {});
      const stream = await navigator.mediaDevices.getUserMedia({audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
      }});
      if (this.closed || !this.active || epoch !== this.micEpoch || this.socket.readyState !== WebSocket.OPEN) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      await resumed;
      if (epoch !== this.micEpoch) { stream.getTracks().forEach(track => track.stop()); return; }
      this.stream = stream;
      stream.getAudioTracks().forEach(track => track.onended = () => {
        if (epoch === this.micEpoch) this.fail('Microphone disconnected. Reconnect it, then start voice again.', 'microphone');
      });
      this.send({type: 'audio.enable', dictation: this.dictation});
      this.micTimer = setTimeout(() => {
        if (epoch === this.micEpoch && !this.micReady) this.fail('Speech recognition did not connect. Please try again.', 'microphone');
      }, 20000);
    } catch (error) {
      if (epoch !== this.micEpoch || this.closed) return;
      this.fail(error.name === 'NotAllowedError'
        ? 'Microphone access was denied. Allow it in your browser, then try again.'
        : 'Microphone unavailable. Check your device and browser permissions.', 'microphone');
    }
  }
  async capture(rate = 16000) {
    if (!this.stream || this.closed || this.worklet || !this.captureContext) return;
    const context = this.captureContext, epoch = this.micEpoch;
    try {
      await context.audioWorklet.addModule('/static/capture-worklet.js');
      if (this.closed || !this.stream || epoch !== this.micEpoch) return;
      this.worklet = new AudioWorkletNode(context, 'pcm16-capture', {
        processorOptions: {targetSampleRate: rate, chunkSamples: Math.round(rate / 10)},
      });
      this.worklet.port.onmessage = ({data}) => {
        if (epoch === this.micEpoch && !this.closed && this.socket.readyState === WebSocket.OPEN && this.socket.bufferedAmount < 160000) this.socket.send(data);
      };
      this.source = context.createMediaStreamSource(this.stream);
      this.source.connect(this.worklet);
      this.silent = context.createGain();
      this.silent.gain.value = 0;
      this.worklet.connect(this.silent);
      this.silent.connect(context.destination);
      await context.resume();
      if (epoch !== this.micEpoch) return;
      clearTimeout(this.micTimer);
      this.micPending = false;
      this.micReady = true;
      this.changed();
    } catch {
      if (epoch === this.micEpoch) this.fail('Microphone setup failed. Please try again or use text input.', 'microphone');
    }
  }
  async unlockPlayback() {
    if (this.closed) return;
    if (!this.playContext) this.playContext = new AudioContext();
    const context = this.playContext;
    const resumed = context.resume();
    if (!this.playReady) {
      this.playReady = context.audioWorklet.addModule('/static/playback-worklet.js').then(() => {
        if (this.closed || this.playContext !== context) return;
        this.playback = new AudioWorkletNode(context, 'pcm16-playback');
        this.playback.connect(context.destination);
        this.playback.port.onmessage = ({data}) => {
          if (data.epoch !== this.playEpoch || this.closed) return;
          if (data.type === 'playing') { this.speaking = true; this.preparing = false; this.error = null; }
          if (data.type === 'ended') { this.speaking = false; this.preparing = false; }
          this.changed();
        };
      }).catch(error => { this.playReady = null; throw error; });
    }
    await Promise.all([resumed, this.playReady]);
    if (!this.closed && context.state !== 'running') throw new Error('Audio context suspended');
  }
  speak(text) {
    if (!this.enabled || this.closed) return;
    if (!('speechSynthesis' in window)) { this.fail('Speech playback is not supported by this browser.'); return; }
    this.stopPlayback();
    const epoch = this.playEpoch;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = /[\u4e00-\u9fff]/.test(text) ? 'zh-CN' : 'en-US';
    const voices = window.speechSynthesis.getVoices();
    utterance.voice = voices.find(v => v.lang.startsWith(utterance.lang.slice(0, 2)) && v.localService) || voices.find(v => v.lang.startsWith(utterance.lang.slice(0, 2))) || null;
    utterance.onstart = () => { if (epoch === this.playEpoch) { this.preparing = false; this.speaking = true; this.error = null; this.changed(); } };
    utterance.onend = () => { if (epoch === this.playEpoch) { this.speaking = false; this.preparing = false; this.changed(); } };
    utterance.onerror = event => {
      if (epoch === this.playEpoch && !['canceled', 'interrupted'].includes(event.error)) this.fail('Voice playback failed. Click Retry audio, or continue with text.');
    };
    this.utterance = utterance;
    this.preparing = true;
    this.changed();
    window.speechSynthesis.speak(utterance);
  }
  preparePlayback(rate) {
    if (!this.enabled || this.closed) return;
    this.stopPlayback();
    this.receivingAudio = true;
    const epoch = this.playEpoch;
    this.preparing = true;
    this.changed();
    this.outputQueue = this.outputQueue.then(async () => {
      if (epoch !== this.playEpoch || !this.enabled) return;
      await this.unlockPlayback();
      if (epoch !== this.playEpoch || !this.enabled || this.closed) return;
      this.playback?.port.postMessage({type: 'config', sampleRate: rate, epoch});
    }).catch(() => { if (epoch === this.playEpoch) this.fail('Audio playback is unavailable. Click Retry audio or continue with text.'); });
  }
  pcm(buffer) {
    if (!this.receivingAudio || !this.enabled || this.closed) return;
    const epoch = this.playEpoch;
    this.outputQueue = this.outputQueue.then(() => {
      if (this.enabled && !this.closed && epoch === this.playEpoch && this.playback) this.playback.port.postMessage({type: 'audio', buffer, epoch}, [buffer]);
    });
  }
  finishPlayback() {
    this.receivingAudio = false;
    const epoch = this.playEpoch;
    this.outputQueue = this.outputQueue.then(() => {
      if (!this.closed && epoch === this.playEpoch) this.playback?.port.postMessage({type: 'end', epoch});
    });
  }
  stopPlayback() {
    this.playEpoch++;
    this.receivingAudio = false;
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    this.playback?.port.postMessage({type: 'stop', epoch: this.playEpoch});
    this.outputQueue = Promise.resolve();
    this.utterance = null;
    this.speaking = false;
    this.preparing = false;
    this.changed();
  }
  interrupt() {
    this.stopPlayback();
    this.thinking = false;
    this.send({type: 'interrupt'});
    this.changed();
  }
  stopMic() {
    this.micEpoch++;
    clearTimeout(this.micTimer);
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = null;
    this.source?.disconnect();
    this.worklet?.disconnect();
    this.silent?.disconnect();
    this.captureContext?.close().catch(() => {});
    this.captureContext = null;
    this.worklet = null;
    this.micPending = false;
    this.micReady = false;
    this.send({type: 'audio.disable'});
    this.changed();
  }
  pauseMic() { if (this.stream || this.micPending) this.stopMic(); else return this.startMic(); }
  setMuted(muted) {
    this.muted = muted;
    this.configureOutput();
    if (!this.enabled) this.stopPlayback();
    else this.unlockPlayback().catch(() => this.fail('Audio playback is blocked. Click Retry audio to enable it.'));
    this.changed();
  }
  setDictation(dictation) {
    this.dictation = dictation;
    this.send({type: 'audio.mode', dictation});
    this.configureOutput();
    if (!this.enabled) this.stopPlayback();
    else this.unlockPlayback().catch(() => this.fail('Audio playback is blocked. Click Retry audio to enable it.'));
    this.changed();
  }
  end() {
    this.active = false;
    this.configureOutput();
    this.stopMic();
    this.interrupt();
    this.error = null;
    this.changed();
  }
  close() {
    this.closed = true;
    this.end();
    this.playContext?.close().catch(() => {});
    this.playContext = null;
    this.playback = null;
    this.changed();
  }
}
