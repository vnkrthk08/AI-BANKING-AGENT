import { useEffect, useRef, useState } from "react";
import { HandPalm, Microphone, MicrophoneSlash, Phone, PhoneDisconnect } from "@phosphor-icons/react";
import { apiJson } from "../services/http";
import { kuralApi } from "../services/kuralApi";
import type { RealtimeVoiceConnection } from "../services/kuralApi";
import type { PolicyDecision, TranscriptMessage, VoiceState } from "../types";

const TIMING_LABELS: Record<string, string> = {
  mic_capture_started: "Microphone capture",
  mic_audio_start: "First PCM sent",
  first_stt_partial: "First STT partial",
  final_stt: "Final transcript / VAD",
  gemini_request_start: "Gemini request start",
  gemini_response_start: "Gemini response received",
  tts_request_start: "TTS request start",
  first_tts_audio_chunk: "First TTS audio chunk",
  browser_playback_started: "Playback scheduled",
  final_audio: "Final audio chunk",
};

interface DemoScenario {
  id: string;
  label: string;
  text: string;
  badge: string;
}

export const MASTER_DEMO_STEPS: DemoScenario[] = [
  { id: "step-1", label: "Step 1: Confirm Identity", text: "Yes, speaking.", badge: "Turn 1" },
  { id: "step-2", label: "Step 2: Give Permission", text: "Sure.", badge: "Turn 2" },
  { id: "step-3", label: "Step 3: App Installed", text: "Yes.", badge: "Turn 3" },
  { id: "step-4", label: "Step 4: Not Updated", text: "No.", badge: "Turn 4" },
  { id: "step-5", label: "Step 5: Storage Full + OTP", text: "Wait - it's failing. It says not enough storage. Also I got an OTP, it's 4819", badge: "Turn 5 (Guard)" },
  { id: "step-6", label: "Step 6: Escalate to Human", text: "I'd rather talk to someone.", badge: "Turn 6" },
  { id: "step-7", label: "Step 7: Hinglish Callback", text: "Kal shaam ko.", badge: "Turn 7 (R20)" },
  { id: "step-8", label: "Step 8: Change Time", text: "Actually make it 5.", badge: "Turn 8" },
  { id: "step-9", label: "Step 9: Confirm & Finish", text: "Yes.", badge: "Turn 9 (Done)" },
];

export const GOLDEN_SCENARIOS: DemoScenario[] = [
  { id: "g-02", label: "Busy Callback", text: "I'm busy right now, call me tomorrow at 3 pm", badge: "G-02 Callback" },
  { id: "g-04", label: "Sensitive OTP Guard", text: "My OTP is 123456.", badge: "G-04 OTP Guard" },
  { id: "g-05", label: "Scam Inquiry", text: "Is this a scam call? Why should I trust you?", badge: "G-05 Scam Check" },
  { id: "g-06", label: "Opt-Out Request", text: "Stop calling me, take me off your list.", badge: "G-06 Opt-Out" },
  { id: "g-07", label: "AI Inquiry", text: "Are you an AI or a real human?", badge: "G-07 AI Check" },
  { id: "g-08", label: "Wrong Person", text: "No, this is not Rahul. Wrong number.", badge: "G-08 Wrong No." },
  { id: "g-10", label: "Sunday Policy", text: "Call me this Sunday at 11 am.", badge: "G-10 Sunday Rule" },
];

function formatTime(date = new Date()): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  }).format(date);
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

interface TurnTelemetry {
  turn: number;
  provider: string;
  model: string;
  fallback_used: boolean;
  secondary_question?: string | null;
  timings: {
    t0_customer_speech_end_ms: number;
    t1_vad_endpoint_ms: number;
    t2_stt_final_ms: number;
    t3_llm_start_ms: number;
    t4_llm_response_ms: number;
    t5_kural_decision_ms: number;
    t6_tts_start_ms: number;
    t7_first_audio_ms: number;
  };
  stages: {
    stt_ms: number;
    llm_ms: number;
    kural_ms: number;
    tts_first_chunk_ms: number;
    total_turn_response_ms: number;
  };
}

function calculatePercentiles(latencies: number[]) {
  if (!latencies.length) return { p50: 0, p95: 0, p99: 0 };
  const sorted = [...latencies].sort((a, b) => a - b);
  const p50 = sorted[Math.floor(sorted.length * 0.5)] || 0;
  const p95 = sorted[Math.floor(sorted.length * 0.95)] || sorted[sorted.length - 1];
  const p99 = sorted[Math.floor(sorted.length * 0.99)] || sorted[sorted.length - 1];
  return { p50, p95, p99 };
}

export function TestConsolePage() {
  const audioContextRef = useRef<AudioContext | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const captureNodeRef = useRef<AudioWorkletNode | null>(null);
  const voiceConnectionRef = useRef<RealtimeVoiceConnection | null>(null);
  const playingSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const nextAudioTimeRef = useRef(0);
  const audioFormatRef = useRef({ sampleRate: 24000, channels: 1 });
  const pcmCarryRef = useRef<Uint8Array>(new Uint8Array());
  const callStartedAtRef = useRef(0);
  const lastFinalAtRef = useRef<number | null>(null);
  const intentionalCloseRef = useRef(false);
  const timerIntervalRef = useRef<number | null>(null);
  const callEndingPendingRef = useRef(false);
  const allTtsChunksReceivedRef = useRef(false);
  const endingFinalizeTimerRef = useRef<number | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);

  const [online, setOnline] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [voiceState, setVoiceState] = useState<VoiceState>("READY");
  const [audioEnergy, setAudioEnergy] = useState(0);
  const [audioDb, setAudioDb] = useState(-60);

  const [kuralState, setKuralState] = useState("DISCLOSURE");
  const [intent, setIntent] = useState("");
  const [policy, setPolicy] = useState<PolicyDecision | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [callbackRequested, setCallbackRequested] = useState(false);
  const [secondaryQuestion, setSecondaryQuestion] = useState<string | null>(null);
  const [fallbackUsed, setFallbackUsed] = useState(false);
  const [turnTelemetry, setTurnTelemetry] = useState<TurnTelemetry | null>(null);
  const [telemetryHistory, setTelemetryHistory] = useState<TurnTelemetry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [voiceErrorRecoverable, setVoiceErrorRecoverable] = useState(false);
  const [micFramesTransmitted, setMicFramesTransmitted] = useState(0);
  const [serverFramesCount, setServerFramesCount] = useState(0);
  const micFramesCountRef = useRef(0);
  const [partialText, setPartialText] = useState("");
  const [connected, setConnected] = useState(false);
  const [callEnded, setCallEnded] = useState(false);
  const [callDuration, setCallDuration] = useState(0);
  const [finalDuration, setFinalDuration] = useState(0);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [timings, setTimings] = useState<Record<string, number>>({});
  const [isMuted, setIsMuted] = useState(false);
  const [composerText, setComposerText] = useState("");
  const [playingVoice, setPlayingVoice] = useState<string | null>(null);
  const [resetNotice, setResetNotice] = useState<string | null>(null);
  const sampleAudioRef = useRef<HTMLAudioElement | null>(null);

  // Customer context
  const [customerInfo, setCustomerInfo] = useState({
    name: "",
    customerRef: "",
    phone: "",
    accountType: "",
    language: "",
    campaign: "Voice Studio session",
  });
  const [customersError, setCustomersError] = useState<string | null>(null);
  void customersError;
  const [availableCustomers, setAvailableCustomers] = useState<Array<Record<string, unknown>>>([]);
  const [showCustomerPicker, setShowCustomerPicker] = useState(false);

  useEffect(() => {
    apiJson<Array<Record<string, unknown>>>("/api/customers?limit=50")
      .then((data) => {
        if (Array.isArray(data) && data.length === 0) setCustomersError("No customers are registered yet. Add or import customers in the Calls hub before starting a call.");
        if (Array.isArray(data) && data.length > 0) {
          setAvailableCustomers(data);
          const first = data[0] as Record<string, string>;
          setCustomerInfo({
            name: first.full_name || "",
            customerRef: first.customer_ref || "",
            phone: first.masked_phone || first.phone || "",
            accountType: `${first.account_type || ""} account`,
            language: first.preferred_language || "",
            campaign: "Voice Studio session",
          });
        }
      })
      .catch((e: unknown) => setCustomersError(e instanceof Error ? e.message : "Customers could not be loaded."));
  }, []);

  function playVoiceSample(sampleUrl: string, voiceId: string) {
    if (playingVoice === voiceId) {
      sampleAudioRef.current?.pause();
      setPlayingVoice(null);
      return;
    }
    if (sampleAudioRef.current) {
      sampleAudioRef.current.pause();
    }
    const audio = new Audio(sampleUrl);
    sampleAudioRef.current = audio;
    setPlayingVoice(voiceId);
    audio.onended = () => setPlayingVoice(null);
    audio.onerror = () => setPlayingVoice(null);
    void audio.play().catch(() => setPlayingVoice(null));
  }

  async function handleResetDemo() {
    try {
      if (sampleAudioRef.current) sampleAudioRef.current.pause();
      setPlayingVoice(null);
      setResetNotice("Started a fresh session. No stored data was deleted.");
      window.setTimeout(() => setResetNotice(null), 4000);
      await startNewSession();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reset failed");
    }
  }

  const timingsRef = useRef<Record<string, number>>({});

  function recordTiming(name: string, value = performance.now() - callStartedAtRef.current) {
    timingsRef.current = { ...timingsRef.current, [name]: value };
    setTimings((current) => ({ ...current, [name]: value }));
  }

  function sendClientTiming(name: string) {
    const elapsed = Math.round(performance.now() - callStartedAtRef.current);
    recordTiming(name, elapsed);
    voiceConnectionRef.current?.sendTiming(name, elapsed);
  }

  function stopMicrophone() {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    analyserRef.current?.disconnect();
    analyserRef.current = null;
    setAudioEnergy(0);
    setAudioDb(-60);
    captureNodeRef.current?.disconnect();
    captureNodeRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
  }

  function stopPlayback() {
    playingSourcesRef.current.forEach((src) => {
      try {
        src.stop();
        src.disconnect();
      } catch {
        /* already stopped */
      }
    });
    playingSourcesRef.current.clear();
    nextAudioTimeRef.current = 0;
    pcmCarryRef.current = new Uint8Array();
    captureNodeRef.current?.port.postMessage({ isSpeaking: false });
    voiceConnectionRef.current?.sendPlaybackStatus("idle");
  }

  function toggleMute() {
    if (!captureNodeRef.current) return;
    const next = !isMuted;
    setIsMuted(next);
    captureNodeRef.current.port.postMessage({ isMuted: next });
  }

  function handleInterrupt() {
    if (connected && voiceConnectionRef.current) {
      stopPlayback();
      setVoiceState("INTERRUPTED");
      voiceConnectionRef.current.sendPlaybackStatus("idle");
    }
  }


  async function finalizeCallEnding() {
    if (intentionalCloseRef.current) return;
    intentionalCloseRef.current = true;
    callEndingPendingRef.current = false;
    allTtsChunksReceivedRef.current = false;
    if (endingFinalizeTimerRef.current) {
      window.clearTimeout(endingFinalizeTimerRef.current);
      endingFinalizeTimerRef.current = null;
    }
    if (timerIntervalRef.current) {
      window.clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
    setFinalDuration(callDuration);
    stopMicrophone();
    voiceConnectionRef.current?.close();
    voiceConnectionRef.current = null;
    setVoiceState("ENDED");
    setConnected(false);
    setCallEnded(true);
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      await audioContextRef.current.close().catch(() => undefined);
    }
    audioContextRef.current = null;
  }

  async function closeCall(sendEnd: boolean) {
    intentionalCloseRef.current = true;
    callEndingPendingRef.current = false;
    allTtsChunksReceivedRef.current = false;
    if (endingFinalizeTimerRef.current) {
      window.clearTimeout(endingFinalizeTimerRef.current);
      endingFinalizeTimerRef.current = null;
    }
    if (timerIntervalRef.current) {
      window.clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
    setFinalDuration(callDuration);
    if (sendEnd) {
      voiceConnectionRef.current?.end();
    }
    stopMicrophone();
    stopPlayback();
    voiceConnectionRef.current?.close();
    voiceConnectionRef.current = null;
    setConnected(false);
    setCallEnded(true);
    setVoiceState("ENDED");
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      await audioContextRef.current.close().catch(() => undefined);
    }
    audioContextRef.current = null;
  }

  function playPcmChunk(chunk: Uint8Array) {
    const context = audioContextRef.current;
    if (!context) return;
    if (context.state === "suspended") {
      void context.resume();
    }
    if (context.state !== "running") return;

    const merged = new Uint8Array(pcmCarryRef.current.length + chunk.length);
    merged.set(pcmCarryRef.current);
    merged.set(chunk, pcmCarryRef.current.length);
    const evenLength = merged.length - (merged.length % 2);
    pcmCarryRef.current = merged.slice(evenLength);
    if (!evenLength) return;

    const view = new DataView(merged.buffer, merged.byteOffset, evenLength);
    const frames = evenLength / 2;
    const buffer = context.createBuffer(audioFormatRef.current.channels, frames, audioFormatRef.current.sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < frames; i += 1) {
      channel[i] = view.getInt16(i * 2, true) / 32768;
    }

    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);

    const playAt = Math.max(context.currentTime + 0.015, nextAudioTimeRef.current);
    source.start(playAt);
    nextAudioTimeRef.current = playAt + buffer.duration;
    if (playingSourcesRef.current.size === 0) {
      captureNodeRef.current?.port.postMessage({ isSpeaking: true });
      voiceConnectionRef.current?.sendPlaybackStatus("playing");
    }
    playingSourcesRef.current.add(source);

    source.onended = () => {
      source.disconnect();
      playingSourcesRef.current.delete(source);
      if (!playingSourcesRef.current.size) {
        captureNodeRef.current?.port.postMessage({ isSpeaking: false });
        voiceConnectionRef.current?.sendPlaybackStatus("idle");
        if (callEndingPendingRef.current && allTtsChunksReceivedRef.current) {
          if (endingFinalizeTimerRef.current) {
            window.clearTimeout(endingFinalizeTimerRef.current);
          }
          endingFinalizeTimerRef.current = window.setTimeout(() => {
            void finalizeCallEnding();
          }, 600);
        } else {
          setVoiceState(callEndingPendingRef.current ? "SPEAKING" : "LISTENING");
        }
      }
    };

    if (timingsRef.current.browser_playback_started === undefined) {
      const now = performance.now();
      recordTiming("browser_playback_started", now - callStartedAtRef.current);
      if (lastFinalAtRef.current !== null) {
        recordTiming("end_to_end", now - lastFinalAtRef.current);
      }
      sendClientTiming("browser_playback_started");
    }
    setVoiceState("SPEAKING");
  }

  function handleVoiceMessage(message: Record<string, unknown>) {
    switch (message.type) {
      case "connected":
        setConnected(true);
        setOnline(true);
        setError(null);
        break;

      case "assistant_message": {
        const now = Date.now();
        const text = String(message.text ?? "");
        setMessages((current) => [...current, { id: `${now}-ava`, speaker: "AVA", text, time: formatTime() }]);
        const stateStr = String(message.state ?? "");
        setKuralState(stateStr);
        setIntent(String(message.intent ?? ""));
        setPolicy((message.policy_decision as PolicyDecision | undefined) ?? null);
        setCaseId((message.case_id as string | null | undefined) ?? null);
        setCallbackRequested(Boolean(message.callback_id));
        if (message.secondary_question) {
          setSecondaryQuestion(String(message.secondary_question));
        } else {
          setSecondaryQuestion(null);
        }
        if (message.fallback_used !== undefined) {
          setFallbackUsed(Boolean(message.fallback_used));
        }
        setPartialText("");
        if (message.ended) {
          callEndingPendingRef.current = true;
          allTtsChunksReceivedRef.current = false;
        }
        break;
      }

      case "turn_telemetry": {
        const tel = message as unknown as TurnTelemetry;
        setTurnTelemetry(tel);
        setTelemetryHistory((prev) => [...prev, tel]);
        if (tel.secondary_question) {
          setSecondaryQuestion(tel.secondary_question);
        }
        if (tel.fallback_used !== undefined) {
          setFallbackUsed(tel.fallback_used);
        }
        break;
      }

      case "transcript_partial":
        if (!callEndingPendingRef.current) {
          setPartialText(String(message.text ?? ""));
          setVoiceState("LISTENING");
        }
        break;

      case "transcript_final": {
        const text = String(message.text ?? "");
        const now = Date.now();
        lastFinalAtRef.current = performance.now();
        const nextTimings = { ...timingsRef.current };
        delete nextTimings.browser_playback_started;
        delete nextTimings.end_to_end;
        timingsRef.current = nextTimings;
        setTimings(nextTimings);

        const sanitizedText = text.replace(/\b(?:\d[ -]?){4,16}\b/g, "[REDACTED_CREDENTIAL]");
        setMessages((current) => [...current, { id: `${now}-customer`, speaker: "CUSTOMER", text: sanitizedText, time: formatTime() }]);
        setPartialText("");
        setVoiceState("PROCESSING");
        break;
      }

      case "speech_started":
        if (!callEndingPendingRef.current) {
          setVoiceState("LISTENING");
        }
        break;

      case "barge_in":
        if (!callEndingPendingRef.current) {
          stopPlayback();
          setVoiceState("INTERRUPTED");
        }
        break;

      case "audio_format":
        audioFormatRef.current = {
          sampleRate: Number(message.sample_rate ?? 24000),
          channels: Number(message.channels ?? 1),
        };
        break;

      case "tts_started":
        setVoiceState("SPEAKING");
        break;

      case "assistant_done":
        if (message.ended || callEndingPendingRef.current) {
          callEndingPendingRef.current = true;
          allTtsChunksReceivedRef.current = true;
          stopMicrophone();
          if (!playingSourcesRef.current.size) {
            if (endingFinalizeTimerRef.current) {
              window.clearTimeout(endingFinalizeTimerRef.current);
            }
            endingFinalizeTimerRef.current = window.setTimeout(() => {
              void finalizeCallEnding();
            }, 2000);
          }
        } else {
          setVoiceState(playingSourcesRef.current.size ? "SPEAKING" : "LISTENING");
        }
        break;

      case "timing": {
        const name = String(message.name ?? "");
        const value = Number(message.elapsed_ms ?? 0);
        if (name) recordTiming(name, value);
        break;
      }

      case "audio_diagnostics": {
        setServerFramesCount(Number(message.mic_frames ?? 0));
        break;
      }

      case "tts_error":
      case "voice_error":
        captureNodeRef.current?.port.postMessage({ isSpeaking: false });
        voiceConnectionRef.current?.sendPlaybackStatus("idle");
        setError(String(message.detail ?? "Voice service encountered an issue. Typed responses remain active."));
        setVoiceErrorRecoverable(Boolean(message.recoverable));
        if (message.fatal) {
          void closeCall(false);
        }
        break;

      case "silence_state": {
        const stateStr = String(message.state ?? "");
        if (stateStr === "REMINDER") {
          setVoiceState("SILENCE_REMINDER");
        } else if (stateStr === "TERMINATING") {
          setVoiceState("TERMINATING");
        } else if (stateStr === "WAITING" && !callEndingPendingRef.current) {
          setVoiceState("LISTENING");
        }
        break;
      }

      case "call_ended": {
        const reason = String(message.reason ?? "");
        if (reason === "no_response") {
          setIntent("NO_RESPONSE");
        }
        callEndingPendingRef.current = true;
        allTtsChunksReceivedRef.current = true;
        stopMicrophone();
        if (!playingSourcesRef.current.size) {
          if (endingFinalizeTimerRef.current) {
            window.clearTimeout(endingFinalizeTimerRef.current);
          }
          endingFinalizeTimerRef.current = window.setTimeout(() => {
            void finalizeCallEnding();
          }, 600);
        }
        break;
      }

      default:
        break;
    }
  }

  async function startNewSession() {
    if (timerIntervalRef.current) {
      window.clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }
    if (endingFinalizeTimerRef.current) {
      window.clearTimeout(endingFinalizeTimerRef.current);
      endingFinalizeTimerRef.current = null;
    }
    if (voiceConnectionRef.current) {
      voiceConnectionRef.current.close();
      voiceConnectionRef.current = null;
    }
    stopMicrophone();
    stopPlayback();
    intentionalCloseRef.current = false;
    callEndingPendingRef.current = false;
    allTtsChunksReceivedRef.current = false;

    const session = await kuralApi.createSession(customerInfo.customerRef);
    setSessionId(session.session_id);
    setKuralState(session.state);
    setIntent("");
    setPolicy(null);
    setCaseId(null);
    setCallbackRequested(false);
    setMessages([]);
    setError(null);
    setVoiceErrorRecoverable(false);
    setMicFramesTransmitted(0);
    setServerFramesCount(0);
    micFramesCountRef.current = 0;
    setPartialText("");
    setTimings({});
    timingsRef.current = {};
    setCallEnded(false);
    setConnected(false);
    setCallDuration(0);
    setFinalDuration(0);
    setVoiceState("READY");
    return session.session_id;
  }

  async function answerCall() {
    if (connected) return;
    let targetSessionId = sessionId;
    if (!targetSessionId || callEnded) {
      targetSessionId = await startNewSession();
    }
    if (!targetSessionId) return;

    setError(null);
    setVoiceErrorRecoverable(false);
    setMicFramesTransmitted(0);
    setServerFramesCount(0);
    micFramesCountRef.current = 0;
    setVoiceState("PROCESSING");
    setCallEnded(false);
    setTimings({});
    timingsRef.current = {};
    setCallDuration(0);
    intentionalCloseRef.current = false;
    callEndingPendingRef.current = false;
    allTtsChunksReceivedRef.current = false;
    if (endingFinalizeTimerRef.current) {
      window.clearTimeout(endingFinalizeTimerRef.current);
      endingFinalizeTimerRef.current = null;
    }
    callStartedAtRef.current = performance.now();

    try {
      let context: AudioContext;
      try {
        context = new AudioContext({ latencyHint: "interactive" });
      } catch {
        context = new AudioContext();
      }
      audioContextRef.current = context;
      await context.resume();

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      micStreamRef.current = stream;

      const connection = await kuralApi.connectRealtimeVoice(
        targetSessionId,
        {
          onMessage: handleVoiceMessage,
          onAudioChunk: playPcmChunk,
          onError: () => setOnline(false),
          onClose: (_code, _reason) => {
            if (!intentionalCloseRef.current) {
              if (callEndingPendingRef.current && playingSourcesRef.current.size > 0) {
                return;
              }
              setConnected(false);
              setVoiceState("READY");
              setError("Call disconnected. You can reconnect or use typed input.");
              stopMicrophone();
              stopPlayback();
            }
          },
        },
        false,
      );
      voiceConnectionRef.current = connection;

      await context.audioWorklet.addModule("/pcm-capture-worklet.js");
      // The server may have ended the call (e.g. speech provider unavailable) while we awaited;
      // keep its truthful error instead of reporting a secondary audio-setup failure.
      if (context.state === "closed" || audioContextRef.current !== context) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      const source = context.createMediaStreamSource(stream);

      // Real-time Web Audio AnalyserNode for true dB / energy meter
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.3;
      source.connect(analyser);
      analyserRef.current = analyser;

      const pcmData = new Uint8Array(analyser.frequencyBinCount);
      const monitorEnergy = () => {
        if (!micStreamRef.current) return;
        analyser.getByteFrequencyData(pcmData);
        let sum = 0;
        for (let i = 0; i < pcmData.length; i++) {
          sum += pcmData[i];
        }
        const avg = sum / pcmData.length;
        const energy = Math.min(100, Math.round((avg / 128) * 100));
        const db = avg > 0 ? Math.max(-60, Math.round(20 * Math.log10(avg / 255))) : -60;
        setAudioEnergy(energy);
        setAudioDb(db);

        // Natural client-side barge-in: If user speaks (>20% energy) while Subbu is actively playing audio
        if (energy > 20 && playingSourcesRef.current.size > 0) {
          stopPlayback();
          voiceConnectionRef.current?.sendPlaybackStatus("idle");
          setVoiceState("LISTENING");
        }

        animFrameRef.current = requestAnimationFrame(monitorEnergy);
      };
      animFrameRef.current = requestAnimationFrame(monitorEnergy);

      const worklet = new AudioWorkletNode(context, "kural-pcm-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { targetRate: 16000 },
      });
      const mute = context.createGain();
      mute.gain.value = 0;

      worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        connection.sendAudio(event.data);
        micFramesCountRef.current += 1;
        if (micFramesCountRef.current % 25 === 0) {
          setMicFramesTransmitted(micFramesCountRef.current);
        }
      };

      source.connect(worklet);
      worklet.connect(mute).connect(context.destination);
      captureNodeRef.current = worklet;

      setConnected(true);
      setOnline(true);
      setVoiceState("SPEAKING");
      sendClientTiming("mic_capture_started");

      timerIntervalRef.current = window.setInterval(() => {
        setCallDuration((prev) => prev + 1);
      }, 1000);
    } catch (cause) {
      await closeCall(false);
      setVoiceState("READY");
      const denied = cause instanceof DOMException && cause.name === "NotAllowedError";
      setError(
        denied
          ? "Microphone access was denied. Please allow microphone permission to talk with Subbu."
          : cause instanceof Error
          ? cause.message
          : "Could not initialize voice call. Check connection.",
      );
    }
  }

  function handleTriggerScenario(scenario: DemoScenario) {
    if (!sessionId) return;
    setError(null);
    if (connected && voiceConnectionRef.current) {
      voiceConnectionRef.current.sendText(scenario.text);
    } else {
      void (async () => {
        try {
          const res = await kuralApi.sendMessage(sessionId, scenario.text);
          setMessages((current) => [
            ...current,
            { id: `${Date.now()}-customer`, speaker: "CUSTOMER", text: res.sanitized_user_text, time: formatTime() },
            { id: `${Date.now()}-ava`, speaker: "AVA", text: res.response, time: formatTime() },
          ]);
          setKuralState(res.state);
          setIntent(res.intent);
          setPolicy(res.policy_decision);
          setCaseId(res.case_id);
          setCallbackRequested(Boolean(res.callback_id));
          if (res.ended) setCallEnded(true);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Request failed");
        }
      })();
    }
  }

  function handleSendText() {
    if (!composerText.trim() || !sessionId) return;
    const textToSend = composerText.trim();
    setComposerText("");
    if (connected && voiceConnectionRef.current) {
      voiceConnectionRef.current.sendText(textToSend);
    } else {
      void (async () => {
        try {
          const res = await kuralApi.sendMessage(sessionId, textToSend);
          setMessages((current) => [
            ...current,
            { id: `${Date.now()}-customer`, speaker: "CUSTOMER", text: res.sanitized_user_text, time: formatTime() },
            { id: `${Date.now()}-ava`, speaker: "AVA", text: res.response, time: formatTime() },
          ]);
          setKuralState(res.state);
          setIntent(res.intent);
          setPolicy(res.policy_decision);
          setCaseId(res.case_id);
          setCallbackRequested(Boolean(res.callback_id));
          if (res.ended) setCallEnded(true);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Request failed");
        }
      })();
    }
  }

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        await kuralApi.health();
        await startNewSession();
        if (active) setOnline(true);
      } catch (cause) {
        if (active) {
          setOnline(false);
          setError(cause instanceof Error ? cause.message : "Could not connect to KURAL backend.");
        }
      }
    })();

    return () => {
      active = false;
      intentionalCloseRef.current = true;
      if (endingFinalizeTimerRef.current) {
        window.clearTimeout(endingFinalizeTimerRef.current);
      }
      if (timerIntervalRef.current) {
        window.clearInterval(timerIntervalRef.current);
      }
      voiceConnectionRef.current?.close();
      stopMicrophone();
      stopPlayback();
      void audioContextRef.current?.close();
    };
  }, []);

  const canUseMic =
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof AudioWorkletNode !== "undefined";

  const statusLabel = connected
    ? voiceState === "SPEAKING"
      ? "SUBBU SPEAKING"
      : voiceState === "SILENCE_REMINDER"
      ? "SILENCE REMINDER"
      : voiceState === "TERMINATING"
      ? "ENDING (NO RESPONSE)"
      : voiceState === "LISTENING"
      ? "LISTENING TO YOU"
      : voiceState === "PROCESSING"
      ? "EVALUATING"
      : voiceState === "INTERRUPTED"
      ? "INTERRUPTED"
      : "CONNECTED"
    : callEnded
    ? intent === "NO_RESPONSE" ? "ENDED (NO RESPONSE)" : "CALL ENDED"
    : "READY";

  const live = connected && !callEnded;
  const stateMeta: Record<VoiceState, { label: string; hint: string; tone: string }> = {
    READY: { label: callEnded ? "Call ended" : "Ready to call", hint: callEnded ? `Duration ${formatDuration(finalDuration)}` : "Subbu will open with the bank's approved disclosure", tone: "" },
    LISTENING: { label: isMuted ? "Microphone muted" : "Listening", hint: isMuted ? "Unmute to let the customer speak" : "Speak naturally — you can interrupt Subbu at any time", tone: isMuted ? "warn" : "live" },
    PROCESSING: { label: "Thinking", hint: "KURAL is checking policy and choosing an approved reply", tone: "live" },
    SPEAKING: { label: "Subbu is speaking", hint: "Start talking to interrupt", tone: "live" },
    INTERRUPTED: { label: "Interrupted", hint: "Listening to the customer", tone: "live" },
    SILENCE_REMINDER: { label: "Checking in", hint: "No response heard — Subbu is prompting the customer", tone: "warn" },
    TERMINATING: { label: "Ending call", hint: "Closing politely", tone: "warn" },
    ENDED: { label: "Call ended", hint: `Duration ${formatDuration(finalDuration)}`, tone: "" },
  };
  const meta = error && !live ? { label: "Call could not start", hint: "See the message below", tone: "bad" } : stateMeta[voiceState];
  const level = Math.min(1, audioEnergy * 4);
  const orbClass = voiceState === "SPEAKING" ? "speaking" : live ? "" : "idle";
  const lat = telemetryHistory.map((t) => t.stages.total_turn_response_ms).filter((n) => n > 0);
  const pct = calculatePercentiles(lat);
  void TIMING_LABELS; void statusLabel; void playingVoice; void playVoiceSample; void secondaryQuestion; void timings; void resetNotice; void handleResetDemo;

  return (
    <>
      <div className="page-head" style={{ marginBottom: 16 }}>
        <div><h1>Voice Studio</h1><p>Place a supervised browser call with Subbu. KURAL decides every reply; the AI only interprets speech.</p></div>
        <div className="actions"><span className={`badge ${online ? "ok" : "bad"}`}>{online ? "API reachable" : "API unreachable"}</span></div>
      </div>
      <div className="studio">
        <section className="stage" aria-label="Call">
          <div className="stage-top">
            <button className="cust-chip" onClick={() => !live && setShowCustomerPicker((v) => !v)} disabled={live} aria-expanded={showCustomerPicker}>
              <span className="avatar" style={{ background: "rgba(255,255,255,.1)", color: "#fff" }}>{(customerInfo.name || "?").slice(0, 1)}</span>
              <span style={{ minWidth: 0 }}><b>{customerInfo.name || "Select a customer"}</b><span>{customerInfo.customerRef ? `${customerInfo.customerRef} · ${customerInfo.phone} · ${customerInfo.language}` : customersError ?? "Choose who Subbu is calling"}</span></span>
            </button>
            <span className={`state-pill ${meta.tone}`}><i />{live ? formatDuration(callDuration) : meta.tone === "bad" ? "Not connected" : "Idle"}</span>
          </div>
          {showCustomerPicker && !live && (
            <div style={{ width: "100%", marginTop: 12, background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.08)", borderRadius: 12, maxHeight: 220, overflow: "auto" }}>
              {availableCustomers.length === 0 ? <p style={{ padding: 14, margin: 0, color: "#8ea0bd" }}>{customersError ?? "No customers registered. Add customers in Calls → Customers."}</p> :
                availableCustomers.map((cust) => { const c = cust as Record<string, string>; return (
                  <button key={c.customer_ref} className="cust-chip" style={{ width: "100%", border: 0, borderRadius: 0, background: c.customer_ref === customerInfo.customerRef ? "rgba(96,145,255,.18)" : "transparent" }}
                    onClick={() => { setCustomerInfo({ name: c.full_name || "", customerRef: c.customer_ref || "", phone: c.masked_phone || c.phone || "", accountType: `${c.account_type || ""} account`, language: c.preferred_language || "", campaign: "Voice Studio session" }); setShowCustomerPicker(false); }}>
                    <span style={{ minWidth: 0 }}><b>{c.full_name}</b><span>{c.customer_ref} · {c.masked_phone || c.phone} · {c.preferred_language}</span></span>
                  </button>); })}
            </div>
          )}
          <div className="orb-wrap">
            <div style={{ display: "grid", justifyItems: "center" }}>
              <div className={`orb ${orbClass}`} aria-hidden="true">
                <span className="ring" style={{ transform: `scale(${1 + (voiceState === "SPEAKING" ? 0.06 : level * 0.18)})`, opacity: live ? 0.4 + level * 0.6 : 0.15 }} />
                <span className="glyph">SUBBU</span>
              </div>
              <div className="caption" aria-live="polite"><b>{meta.label}</b><span>{meta.hint}</span></div>
              <div className="partial" aria-live="polite">{live && partialText ? `“${partialText}”` : ""}</div>
            </div>
          </div>
          {error && (
            <div className="stage-error" role="alert"><span>{error}</span>
              {voiceErrorRecoverable && live ? <button className="btn sm" onClick={() => { voiceConnectionRef.current?.retrySpeech(); setError(null); }}>Retry audio</button> : <button className="btn sm" onClick={() => setError(null)}>Dismiss</button>}
            </div>
          )}
          <div className="controls" style={{ marginTop: 18 }}>
            {live && <button className="ctl" onClick={toggleMute} aria-pressed={isMuted} aria-label={isMuted ? "Unmute microphone" : "Mute microphone"} title={isMuted ? "Unmute" : "Mute"} style={isMuted ? { background: "#f59e0b", color: "#111" } : undefined}>{isMuted ? <MicrophoneSlash size={22} /> : <Microphone size={22} />}</button>}
            {live ? (
              <button className="call-btn end" onClick={() => void closeCall(true)}><PhoneDisconnect size={20} weight="fill" /> End call</button>
            ) : (
              <button className="call-btn" disabled={!canUseMic || !customerInfo.customerRef || voiceState === "PROCESSING"} onClick={() => void answerCall()}
                title={!customerInfo.customerRef ? "Select a customer first" : !canUseMic ? "This browser cannot capture microphone audio" : ""}>
                <Phone size={20} weight="fill" /> {callEnded ? "Start new call" : "Start call"}
              </button>
            )}
            {live && <button className="ctl" onClick={handleInterrupt} disabled={voiceState !== "SPEAKING"} aria-label="Interrupt Subbu" title="Interrupt Subbu"><HandPalm size={22} /></button>}
          </div>
          <div className="stage-foot">
            <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className={`mic-meter ${live && !isMuted ? "live" : ""}`} aria-label={live ? `Microphone level ${Math.round(level * 100)}%` : "Microphone idle"}>
                {[0.2, 0.45, 0.7, 1, 0.7, 0.45, 0.2].map((w, i) => <i key={i} style={{ height: `${4 + (live && !isMuted ? level * w * 14 : 0)}px` }} />)}
              </span>
              {!canUseMic ? "Microphone capture unsupported" : live ? (isMuted ? "Microphone muted" : `Microphone live · ${micFramesTransmitted} frames sent`) : "Microphone off"}
            </span>
            <span>Never share OTPs, PINs or passwords on a call</span>
          </div>
        </section>

        <section className="panel transcript" aria-label="Transcript">
          <div className="panel-head"><div><h2>Transcript</h2><div className="sub">Sensitive numbers are redacted before storage</div></div>{messages.length > 0 && <span className="badge plain">{messages.length} turns</span>}</div>
          <div className="transcript-list" aria-live="polite">
            {messages.length === 0 ? <div className="empty"><h3>No conversation yet</h3><p>Start a call to see Subbu and the customer here in real time.</p></div> :
              messages.map((m) => <div key={m.id} className={`msg ${m.speaker === "CUSTOMER" ? "cust" : "ava"}`}><small>{m.speaker === "CUSTOMER" ? "Customer" : "Subbu"}{m.redacted ? " · redacted" : ""}</small>{m.text}</div>)}
          </div>
          {(caseId || callbackRequested || policy === "BLOCKED") && (
            <div className="outcome">
              {caseId && <span className="badge warn">Case {caseId} raised</span>}
              {callbackRequested && <span className="badge info">Callback recorded</span>}
              {policy === "BLOCKED" && <span className="badge bad">Sensitive input blocked</span>}
            </div>
          )}
          <div className="composer">
            <input className="input" placeholder={live ? "Type the customer's reply (text fallback)" : "Start a call to use the text fallback"} value={composerText} disabled={!live}
              onChange={(e) => setComposerText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && composerText.trim() && handleSendText()} aria-label="Customer reply" />
            <button className="btn" disabled={!live || !composerText.trim()} onClick={handleSendText}>Send</button>
          </div>
        </section>
      </div>

      <details className="diag" open={showDiagnostics} onToggle={(e) => setShowDiagnostics((e.target as HTMLDetailsElement).open)}>
        <summary>Diagnostics</summary>
        <div className="stack" style={{ marginTop: 8 }}>
          <div className="diag-grid">
            <div className="diag-cell"><label>KURAL state</label><b>{kuralState}</b></div>
            <div className="diag-cell"><label>Last intent</label><b>{intent || "—"}</b></div>
            <div className="diag-cell"><label>Policy</label><b>{policy ?? "—"}</b></div>
            <div className="diag-cell"><label>LLM fallback used</label><b>{fallbackUsed ? "Yes (rules)" : "No"}</b></div>
            <div className="diag-cell"><label>Session</label><b className="mono">{sessionId ? sessionId.slice(0, 8) : "—"}</b></div>
            <div className="diag-cell"><label>Mic frames / server frames</label><b>{micFramesTransmitted} / {serverFramesCount}</b></div>
            <div className="diag-cell"><label>Input level</label><b>{audioDb.toFixed(0)} dB</b></div>
            <div className="diag-cell"><label>Turn latency p50 / p95</label><b>{lat.length ? `${Math.round(pct.p50)} / ${Math.round(pct.p95)} ms` : "—"}</b></div>
          </div>
          {turnTelemetry && (
            <div className="diag-grid">
              {Object.entries(turnTelemetry.stages).map(([k, v]) => <div className="diag-cell" key={k}><label>{k.replace(/_/g, " ")}</label><b>{Math.round(v)} ms</b></div>)}
            </div>
          )}
          <div>
            <p className="small muted" style={{ margin: "0 0 6px" }}>Test utterances — sent as typed customer replies during a live call (QA only).</p>
            <div className="chips">{[...MASTER_DEMO_STEPS, ...GOLDEN_SCENARIOS].map((sc) => <button key={sc.id} className="chip" disabled={!live} onClick={() => handleTriggerScenario(sc)} title={sc.text}>{sc.label}</button>)}</div>
          </div>
        </div>
      </details>
    </>
  );
}
