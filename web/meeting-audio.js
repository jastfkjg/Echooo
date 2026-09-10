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
    try {
      if (includeTab) {
        if (!this.mediaDevices?.getDisplayMedia) {
          throw new Error('Tab audio sharing is unavailable. Use desktop Chrome or choose Microphone only.');
        }
        // This must be the first permission request, while the click is active.
        const shared = this.keep(await this.mediaDevices.getDisplayMedia({
          video: true,
          audio: {suppressLocalAudioPlayback: false},
          preferCurrentTab: false,
          selfBrowserSurface: 'exclude',
          systemAudio: 'exclude',
          surfaceSwitching: 'exclude',
        }));
        if (!shared.getAudioTracks().length) {
          throw new Error('No shared audio. Choose the meeting or video tab and enable “Share tab audio”, then try again.');
        }
      }
      this.keep(await this.mediaDevices.getUserMedia({
        audio: {echoCancellation: true, noiseSuppression: true},
      }));
      if (this.closed) throw new Error('Recording setup was cancelled.');
      return this;
    } catch (error) {
      this.close();
      if (error.name === 'NotAllowedError' || error.name === 'AbortError') {
        throw new Error('Recording was not started. Allow microphone access and, for tab recording, share the meeting or video tab with audio.');
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
