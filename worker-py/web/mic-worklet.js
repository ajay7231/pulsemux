/* Capture on the audio thread, preserving the resampling phase across blocks. */
class CallMicrophone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 8000;
    this.weight = 0;
    this.sum = 0;
    this.frame = [];
  }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const sample of input) {
      let remaining = 1;
      while (remaining > 1e-9) {
        const take = Math.min(remaining, this.ratio - this.weight);
        this.sum += sample * take;
        this.weight += take;
        remaining -= take;
        if (this.weight >= this.ratio - 1e-9) {
          this.frame.push(this.sum / this.ratio);
          this.weight = 0;
          this.sum = 0;
          if (this.frame.length === 160) {
            const frame = new Float32Array(this.frame);
            this.port.postMessage(frame, [frame.buffer]);
            this.frame = [];
          }
        }
      }
    }
    return true;
  }
}
registerProcessor('call-microphone', CallMicrophone);
