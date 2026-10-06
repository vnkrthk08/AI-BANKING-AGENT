export interface TTSProvider {
  readonly available: boolean;
  speak(text: string): Promise<void>;
  stop(): void;
}
