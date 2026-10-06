export interface STTProvider {
  readonly available: boolean;
  listen(onPartial?: (text: string) => void): Promise<string>;
  stop(): void;
}
