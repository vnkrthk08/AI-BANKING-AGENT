import type { CaseRecord, SessionDetail, SessionResponse, TurnResponse } from "../types";

export interface VoiceTurnResponse {
  session_id: string;
  transcript: string;
  language_code: string | null;
  intent: string;
  state: string;
  response: string;
  ended: boolean;
  case_id: string | null;
  callback_id: string | null;
  policy_decision: "ALLOWED" | "BLOCKED";
  audio_base64: string | null;
  audio_content_type: string;
  tts_error: string | null;
}

export interface VoiceStreamHandlers {
  onMetadata: (metadata: VoiceTurnResponse) => void;
  onAudioChunk: (chunk: Uint8Array) => void;
  onTtsError: (message: string) => void;
}

export interface RealtimeVoiceHandlers {
  onMessage: (message: Record<string, unknown>) => void;
  onAudioChunk: (chunk: Uint8Array) => void;
  onClose: (code: number, reason: string) => void;
  onError: () => void;
}

export interface RealtimeVoiceConnection {
  sendAudio: (pcm16: ArrayBuffer) => void;
  sendTiming: (name: string, elapsedMs: number) => void;
  sendText: (text: string) => void;
  sendPlaybackStatus: (status: "playing" | "idle") => void;
  end: () => void;
  close: () => void;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `KURAL request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export const kuralApi = {
  health: () => request<{ status: string }>("/health"),
  createSession: () => request<SessionResponse>("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ customer_ref: "CUST001" }),
  }),
  sendMessage: (sessionId: string, text: string) => request<TurnResponse>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
    { method: "POST", body: JSON.stringify({ text }) },
  ),
  voiceTurn: async (sessionId: string, audio: Blob): Promise<VoiceTurnResponse> => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("audio", audio, "customer.webm");
    const response = await fetch("/api/v1/voice/turn", { method: "POST", body: form });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null;
      throw new Error(body?.detail ?? `Voice turn failed (${response.status})`);
    }
    return (await response.json()) as VoiceTurnResponse;
  },
  voiceTurnStream: (sessionId: string, audio: Blob, handlers: VoiceStreamHandlers): Promise<void> => {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${scheme}//${window.location.host}/api/v1/voice/turn/stream`);
    socket.binaryType = "arraybuffer";
    return new Promise((resolve, reject) => {
      let completed = false;
      let sawMetadata = false;
      const timeout = window.setTimeout(() => {
        socket.close();
        reject(new Error("Voice turn timed out. Please try again."));
      }, 90000);
      const finish = () => {
        completed = true;
        window.clearTimeout(timeout);
        socket.close();
        resolve();
      };
      socket.onopen = () => {
        socket.send(JSON.stringify({ type: "start", session_id: sessionId, content_type: audio.type || "audio/webm" }));
        void audio.arrayBuffer().then((bytes) => {
          if (socket.readyState === WebSocket.OPEN) socket.send(bytes);
        }).catch(() => reject(new Error("Could not read the microphone recording.")));
      };
      socket.onmessage = (event: MessageEvent<ArrayBuffer | string>) => {
        if (event.data instanceof ArrayBuffer) {
          handlers.onAudioChunk(new Uint8Array(event.data));
          return;
        }
        let message: { type?: string; detail?: string; data?: VoiceTurnResponse };
        try { message = JSON.parse(event.data) as typeof message; }
        catch { reject(new Error("The voice service returned an invalid response.")); socket.close(); return; }
        if (message.type === "metadata" && message.data) {
          sawMetadata = true;
          handlers.onMetadata(message.data);
        } else if (message.type === "tts_error") {
          handlers.onTtsError(message.detail ?? "AVA speech audio is unavailable. You can still read the response.");
        } else if (message.type === "error") {
          window.clearTimeout(timeout);
          socket.close();
          reject(new Error(message.detail ?? "Voice turn failed. Please try again."));
        } else if (message.type === "audio_complete") {
          if (!sawMetadata) {
            window.clearTimeout(timeout);
            socket.close();
            reject(new Error("Voice metadata was missing from the response."));
            return;
          }
          finish();
        }
      };
      socket.onerror = () => {
        window.clearTimeout(timeout);
        reject(new Error("Voice connection failed. Check the backend and try again."));
      };
      socket.onclose = () => {
        if (!completed) {
          window.clearTimeout(timeout);
          reject(new Error("Voice connection closed before the response completed."));
        }
      };
    });
  },
  connectRealtimeVoice: (
    sessionId: string,
    handlers: RealtimeVoiceHandlers,
    resume = false,
  ): Promise<RealtimeVoiceConnection> => {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${scheme}//${window.location.host}/api/v1/voice/realtime`);
    socket.binaryType = "arraybuffer";
    return new Promise((resolve, reject) => {
      let settled = false;
      const timeout = window.setTimeout(() => {
        socket.close();
        if (!settled) reject(new Error("Voice connection timed out. Check the backend and try again."));
      }, 20000);
      socket.onopen = () => {
        socket.send(JSON.stringify({ type: "start", session_id: sessionId, resume }));
        settled = true;
        window.clearTimeout(timeout);
        resolve({
          sendAudio: (pcm16) => { if (socket.readyState === WebSocket.OPEN) socket.send(pcm16); },
          sendTiming: (name, elapsedMs) => {
            if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "client_timing", name, elapsed_ms: elapsedMs }));
          },
          sendText: (text) => {
            if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "user_text", text }));
          },
          sendPlaybackStatus: (status) => {
            if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "playback_status", status }));
          },
          end: () => {
            if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "end" }));
          },
          close: () => socket.close(),
        });
      };
      socket.onmessage = (event: MessageEvent<ArrayBuffer | string>) => {
        if (event.data instanceof ArrayBuffer) {
          handlers.onAudioChunk(new Uint8Array(event.data));
          return;
        }
        try { handlers.onMessage(JSON.parse(event.data) as Record<string, unknown>); }
        catch { handlers.onError(); }
      };
      socket.onerror = () => {
        handlers.onError();
        if (!settled) {
          settled = true;
          window.clearTimeout(timeout);
          reject(new Error("Voice connection failed. Check the backend and try again."));
        }
      };
      socket.onclose = (event) => {
        window.clearTimeout(timeout);
        handlers.onClose(event.code, event.reason);
        if (!settled) {
          settled = true;
          reject(new Error("Voice connection closed before it started."));
        }
      };
    });
  },
  session: (sessionId: string) => request<SessionDetail>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`),
  cases: () => request<CaseRecord[]>("/api/v1/cases"),
  resetDemo: () =>
    request<{ status: string; message: string }>("/api/demo/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }),
};

