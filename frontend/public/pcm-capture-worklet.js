class KuralPcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = options.processorOptions?.targetRate || 16000;
    this.step = sampleRate / this.targetRate;
    this.position = 0;
    this.previous = 0;
    this.hasPrevious = false;
    this.pending = [];
    this.isSpeaking = false;

    this.port.onmessage = (event) => {
      if (event.data && typeof event.data.isSpeaking === "boolean") {
        this.isSpeaking = event.data.isSpeaking;
      }
    };
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
      let sumSq = 0;
      for (let i = 0; i < 320; i += 1) {
        sumSq += frame[i] * frame[i];
      }
      const rms = Math.sqrt(sumSq / 320);

      // Acoustic Gating & Silence Suppression:
      // 1. While assistant is actively speaking (this.isSpeaking):
      //    Suppress microphone frames to eliminate speaker feedback into STT,
      //    unless user is deliberately and loudly barging in (RMS >= 0.22).
      // 2. When listening in silence/ambient room noise (RMS < 0.005):
      //    Suppress transmission so pure silence is not streamed into neural ASR models (Whisper/Saaras),
      //    preventing phantom hallucinated transcripts ("Thanks, wonderful", "However").
      const isNoiseOrSilence = isNaN(rms) || rms < 0.005;
      const isAcousticLeakage = this.isSpeaking && rms < 0.22;
      if (isNoiseOrSilence || isAcousticLeakage) {
        continue;
      }

      const pcm = new Int16Array(320);
      for (let i = 0; i < 320; i += 1) {
        const s = Number.isFinite(frame[i]) ? frame[i] : 0;
        pcm[i] = Math.round(s * (s < 0 ? 32768 : 32767));
      }
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("kural-pcm-capture", KuralPcmCaptureProcessor);
