import type { STTProvider } from "./STTProvider";

interface SpeechResultEvent extends Event {
  readonly resultIndex: number;
  readonly results: ArrayLike<ArrayLike<{ transcript: string; confidence: number }> & { isFinal: boolean }>;
}

interface BrowserRecognition extends EventTarget {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: Event & { error?: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

interface RecognitionWindow extends Window {
  SpeechRecognition?: new () => BrowserRecognition;
  webkitSpeechRecognition?: new () => BrowserRecognition;
}

export class BrowserSTTProvider implements STTProvider {
  private recognition: BrowserRecognition | null = null;
  private rejectActive: ((reason: Error) => void) | null = null;

  get available(): boolean {
    const browserWindow = window as RecognitionWindow;
    return Boolean(browserWindow.SpeechRecognition ?? browserWindow.webkitSpeechRecognition);
  }

  listen(onPartial?: (text: string) => void): Promise<string> {
    const browserWindow = window as RecognitionWindow;
    const Recognition = browserWindow.SpeechRecognition ?? browserWindow.webkitSpeechRecognition;
    if (!Recognition) return Promise.reject(new Error("Browser voice input unavailable — use text mode."));
    this.stop();
    const recognition = new Recognition();
    this.recognition = recognition;
    recognition.lang = "en-IN";
    recognition.interimResults = true;
    recognition.continuous = false;
    return new Promise((resolve, reject) => {
      this.rejectActive = reject;
      let finalText = "";
      recognition.onresult = (event) => {
        let interim = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          if (result.isFinal) finalText += result[0].transcript;
          else interim += result[0].transcript;
        }
        onPartial?.(finalText || interim);
      };
      recognition.onerror = (event) => {
        const detail = event.error === "not-allowed" || event.error === "service-not-allowed"
          ? "Microphone permission was denied. Allow microphone access or use text mode."
          : `Speech recognition failed${event.error ? ` (${event.error})` : ""}. Use text mode to continue.`;
        this.recognition = null;
        this.rejectActive = null;
        reject(new Error(detail));
      };
      recognition.onend = () => {
        this.recognition = null;
        this.rejectActive = null;
        if (finalText.trim()) resolve(finalText.trim());
        else reject(new Error("No speech was detected. Try again or use text mode."));
      };
      try {
        recognition.start();
      } catch (error) {
        this.recognition = null;
        this.rejectActive = null;
        reject(error instanceof Error ? error : new Error("Could not start microphone input."));
      }
    });
  }

  stop(): void {
    const recognition = this.recognition;
    if (!recognition) return;
    this.recognition = null;
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    recognition.abort();
    this.rejectActive?.(new Error("Microphone input stopped."));
    this.rejectActive = null;
  }
}
