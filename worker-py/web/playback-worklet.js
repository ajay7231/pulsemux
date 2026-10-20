'use strict';

// Continuous 24kHz PCM resampling on the audio rendering thread. Chunk arrival
// timing never resets the resampler or the call's downstream filter state.
class CallPlayback extends AudioWorkletProcessor {
  constructor() {
    super();
    this.rate = 24000;
    this.buffer = new Float32Array(this.rate * 3);
    this.epoch = 0;
    this.fadeFrames = Math.max(1, Math.round(sampleRate * 0.003));
    this.last = 0; this.fade = 0;
    this.reset();
    this.port.onmessage = ({data}) => {
      if (data.type === 'reset') {
        this.epoch = data.epoch; this.reset(); return;
      }
      if (data.epoch !== this.epoch) return;
      if (data.type === 'finish') { this.finished = true; return; }
      if (data.type !== 'audio') return;
      const samples = data.samples;
      if (!(samples instanceof Float32Array) || !samples.length || samples.length > 480 || this.finished ||
          this.write - this.read + samples.length > this.buffer.length) {
        this.port.postMessage({type:'error', epoch:this.epoch});
        return;
      }
      for (let i = 0; i < samples.length; i++) this.buffer[this.write++ % this.buffer.length] = samples[i];
    };
  }
  reset() {
    this.buffer.fill(0);
    this.read = 0; this.write = 0; this.phase = 0;
    this.playing = false; this.finished = false; this.drained = false;
    this.fade = this.fadeFrames; this.attack = 0;
  }
  process(_inputs, outputs) {
    const out = outputs[0]?.[0];
    if (!out) return true;
    for (let i = 0; i < out.length; i++) {
      let available = this.write - this.read;
      if (!this.playing && (available >= this.rate * 0.08 || (this.finished && available > 0))) {
        this.playing = true; this.attack = this.fadeFrames; this.fade = 0;
        this.port.postMessage({type:'started', epoch:this.epoch});
      }
      if (this.playing && available < (this.finished ? 1 : 2)) {
        this.playing = false; this.fade = this.fadeFrames;
        if (!this.finished) this.port.postMessage({type:'underrun', epoch:this.epoch});
      }
      if (this.playing) {
        const a = this.buffer[this.read % this.buffer.length];
        const b = available > 1 ? this.buffer[(this.read + 1) % this.buffer.length] : a;
        let value = a + (b - a) * this.phase;
        this.phase += this.rate / sampleRate;
        const advance = Math.floor(this.phase);
        this.read = Math.min(this.write, this.read + advance);
        this.phase -= advance;
        if (this.attack > 0) value *= 1 - this.attack-- / this.fadeFrames;
        out[i] = value; this.last = value;
      } else {
        // Brief fades suppress clicks at real underruns, interruption and end.
        out[i] = this.fade > 0 ? this.last * this.fade-- / this.fadeFrames : 0;
      }
      if (this.finished && this.read === this.write && !this.playing && this.fade === 0 && !this.drained) {
        this.drained = true;
        this.port.postMessage({type:'drained', epoch:this.epoch});
      }
    }
    return true;
  }
}
registerProcessor('call-playback', CallPlayback);
