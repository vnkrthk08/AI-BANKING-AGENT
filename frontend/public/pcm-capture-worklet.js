class KuralPcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = options.processorOptions?.targetRate || 16000;
    this.step = sampleRate / this.targetRate;
    this.position = 0;
    this.previous = 0;
    this.hasPrevious = false;
    this.pending = [];
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel?.length) return true;
    const source = this.hasPrevious ? [this.previous, ...channel] : Array.from(channel);
    const output = [];
    while (this.position + 1 < source.length) {
      const index = Math.floor(this.position);
      const fraction = this.position - index;
      const value = source[index] + (source[index + 1] - source[index]) * fraction;
      output.push(Math.max(-1, Math.min(1, value)));
      this.position += this.step;
    }
    this.position -= source.length - 1;
    this.previous = source[source.length - 1];
    this.hasPrevious = true;
    this.pending.push(...output);

    while (this.pending.length >= 320) {
      const frame = this.pending.splice(0, 320);
      const pcm = new Int16Array(320);
      for (let i = 0; i < 320; i += 1) pcm[i] = Math.round(frame[i] * (frame[i] < 0 ? 32768 : 32767));
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("kural-pcm-capture", KuralPcmCaptureProcessor);
