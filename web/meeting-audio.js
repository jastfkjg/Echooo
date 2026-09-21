// Own both permission requests and their tracks, including late permission results.
export class MeetingAudio {
  constructor({mediaDevices = navigator.mediaDevices, onEnded = () => {}} = {}) {
    this.mediaDevices = mediaDevices;
    this.onEnded = onEnded;
    this.streams = [];
    this.nodes = [];
    this.listeners = [];
    this.closed = false;
  }

  keep(stream) {
    if (this.closed) {
      stream.getTracks().forEach(track => track.stop());
      throw new Error('Recording setup was cancelled.');
    }
    this.streams.push(stream);
    for (const track of stream.getTracks()) {
      const ended = () => {
        if (this.closed) return;
        this.close();
        this.onEnded();
      };
      track.addEventListener('ended', ended);
      this.listeners.push([track, ended]);
      if (track.readyState === 'ended') {
        ended();
        throw new Error('The audio source stopped. Start recording again.');
      }
    }
    return stream;
  }

  async open(includeTab = true) {
    let requestingTab = includeTab;
    try {
      if (includeTab) {
        if (!this.mediaDevices?.getDisplayMedia) {
          throw new Error('Tab audio sharing is unavailable. Use desktop Chrome or choose Microphone only.');
        }
        // This must be the first permission request, while the click is active.
        const shared = this.keep(await this.mediaDevices.getDisplayMedia({
          video: {displaySurface: 'browser'},
          audio: {suppressLocalAudioPlayback: false},
          preferCurrentTab: false,
          selfBrowserSurface: 'exclude',
          systemAudio: 'exclude',
          windowAudio: 'exclude',
          monitorTypeSurfaces: 'exclude',
          surfaceSwitching: 'exclude',
        }));
        // Picker preferences are hints; reject unsupported sources before asking for the mic.
        const surface = shared.getVideoTracks()[0]?.getSettings?.().displaySurface;
        if (surface && surface !== 'browser') {
          throw new Error('Choose a Chrome tab, not a window or screen, and enable “Share tab audio”.');
        }
        if (!shared.getAudioTracks().length) {
          throw new Error('No shared audio. Choose a tab and enable “Share tab audio”.');
        }
      }
      requestingTab = false;
      const microphone = this.keep(await this.mediaDevices.getUserMedia({
        audio: {echoCancellation: true, noiseSuppression: true},
      }));
      // Cancel local speaker output in the microphone path, never the shared tab.
      // Capability-gated: older browsers keep their ordinary AEC. Do not gate
      // capture or remove matching transcript text: people may quote the assistant.
      for (const track of microphone.getAudioTracks()) {
        if (track.getCapabilities?.().echoCancellation?.includes('all') && track.applyConstraints) {
          try { await track.applyConstraints({echoCancellation: {exact: 'all'}}); }
          catch { /* Keep the initially requested ordinary AEC and continuous capture. */ }
        }
      }
      if (this.closed) throw new Error('Recording setup was cancelled.');
      return this;
    } catch (error) {
      this.close();
      if (error.name === 'NotAllowedError' || error.name === 'AbortError') {
        throw new Error(requestingTab ? 'Recording not started. Share a tab with audio to retry.' : 'Recording not started. Allow microphone access to retry.');
      }
      throw error;
    }
  }

  connect(context, destination) {
    if (this.closed) throw new Error('The audio source stopped. Start recording again.');
    for (const stream of this.streams) {
      const source = context.createMediaStreamSource(stream);
      const gain = context.createGain();
      // Downmix stereo tabs before capture (the PCM worklet reads one channel).
      // Half gain per source leaves headroom for simultaneous full-scale speech.
      gain.channelCount = 1;
      gain.channelCountMode = 'explicit';
      gain.channelInterpretation = 'speakers';
      gain.gain.value = 1 / this.streams.length;
      this.nodes.push(source, gain);
      source.connect(gain);
      gain.connect(destination);
    }
  }

  close() {
    this.closed = true;
    this.listeners.splice(0).forEach(([track, ended]) => track.removeEventListener('ended', ended));
    this.nodes.splice(0).forEach(node => node.disconnect());
    this.streams.splice(0).forEach(stream => stream.getTracks().forEach(track => track.stop()));
  }
}
