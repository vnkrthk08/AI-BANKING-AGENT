import type { TTSProvider } from "./TTSProvider";

export class BrowserTTSProvider implements TTSProvider {
  get available(): boolean {
    return typeof window !== "undefined" && "speechSynthesis" in window;
  }

  speak(text: string): Promise<void> {
    if (!this.available) return Promise.reject(new Error("Browser speech output is unavailable."));
    this.stop();
    return new Promise((resolve, reject) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "en-IN";
      utterance.rate = 0.96;
      utterance.onend = () => resolve();
      utterance.onerror = () => reject(new Error("Browser speech output could not finish."));
      window.speechSynthesis.speak(utterance);
    });
  }

  stop(): void {
    if (this.available) window.speechSynthesis.cancel();
  }
}
