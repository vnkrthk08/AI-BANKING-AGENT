import { useEffect, useRef, useState } from "react";
import {
  ArrowCounterClockwise,
  CheckCircle,
  Clock,
  Hand,
  Lock,
  Microphone,
  MicrophoneSlash,
  PaperPlaneRight,
  Phone,
  PhoneDisconnect,
  ShieldCheck,
  SlidersHorizontal,
  Sparkle,
  UserCircle,
  Waveform,
  X,
} from "@phosphor-icons/react";
import { kuralApi } from "../services/kuralApi";
import type { RealtimeVoiceConnection } from "../services/kuralApi";
import type { PolicyDecision, TranscriptMessage, VoiceState } from "../types";
import "../voice-agent.css";

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
    name: "Rahul Sharma",
    customerRef: "CUST-00001",
    phone: "+91 98765 43210",
    accountType: "Savings Account · Active",
    language: "Hindi / English",
    campaign: "App v2.4 Upgrade Outreach",
  });
  const [availableCustomers, setAvailableCustomers] = useState<Array<Record<string, unknown>>>([]);
  const [showCustomerPicker, setShowCustomerPicker] = useState(false);

  useEffect(() => {
    fetch("/api/customers?limit=10")
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setAvailableCustomers(data);
          const first = data[0] as Record<string, string>;
          setCustomerInfo({
            name: first.full_name || "Rahul Sharma",
            customerRef: first.customer_ref || "CUST-00001",
            phone: first.phone || "+91 98765 43210",
            accountType: `${first.account_type || "Savings"} Account · Active`,
            language: first.preferred_language || "Hindi / English",
            campaign: "App v2.4 Upgrade Outreach",
          });
        }
      })
      .catch(() => undefined);
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
      await kuralApi.resetDemo();
      setResetNotice("Telephony cache and local demo data cleared.");
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

  return (
    <div className="voice-agent-root">
      <div className="voice-agent-container">
        {/* ==================================================================
            1. MINIMAL TOP BAR
            ================================================================== */}
        <header className="voice-topbar">
          <div className="voice-brand-pill">
            <div className="voice-brand-logo">TB</div>
            <div className="voice-brand-title">
              <strong>Town Bank · Outbound Voice Officer</strong>
              <span>KURAL Real-time Orchestration Engine · Subbu Voice</span>
            </div>
          </div>

          <div className="voice-topbar-controls">
            {/* Backend connectivity indicator */}
            <span style={{ fontSize: "11px", color: online ? "#34d399" : "#f87171", fontWeight: 600 }}>
              {online ? "● Backend Online" : "● Offline"}
            </span>

            {/* Live call status badge */}
            <div className={`voice-call-status-badge ${connected ? "is-live" : callEnded ? "is-ended" : ""}`}>
              {connected && <span className="live-pulse-dot" />}
              <span>{statusLabel}</span>
            </div>

            {/* Call duration timer */}
            {connected && <div className="voice-timer">{formatDuration(callDuration)}</div>}

            {/* Engineering Diagnostics Drawer toggle button */}
            <button
              className="developer-toggle"
              style={{ padding: "6px 12px", fontSize: "11px" }}
              onClick={() => setShowDiagnostics((prev) => !prev)}
              aria-label="Toggle engineering diagnostics drawer"
            >
              <SlidersHorizontal size={14} />
              <span>Diagnostics</span>
            </button>

            {/* Reset button */}
            <button
              className="reset-demo-btn"
              onClick={() => void handleResetDemo()}
              title="Reset session and telephony cache"
            >
              <ArrowCounterClockwise size={13} /> Reset
            </button>
          </div>
        </header>

        {/* Global notification banners */}
        {resetNotice && (
          <div style={{ background: "rgba(16, 185, 129, 0.2)", border: "1px solid #10b981", color: "#a7f3d0", padding: "10px 16px", borderRadius: 12, fontSize: "12px", display: "flex", alignItems: "center", gap: "8px" }}>
            <CheckCircle size={16} weight="fill" />
            <span>{resetNotice}</span>
          </div>
        )}

        {error && (
          <div className="error-banner" role="alert" style={{ margin: 0, borderRadius: 12, display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px" }}>
            <div>
              <strong>Voice Notification:</strong> {error}
            </div>
            {voiceErrorRecoverable && (
              <button
                type="button"
                className="retry-speech-btn"
                onClick={() => {
                  voiceConnectionRef.current?.retrySpeech();
                  setError(null);
                  setVoiceErrorRecoverable(false);
                }}
                style={{
                  background: "#38bdf8",
                  color: "#0f172a",
                  border: "none",
                  borderRadius: 6,
                  padding: "6px 12px",
                  fontSize: "11px",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                ↻ Retry Audio Playback
              </button>
            )}
          </div>
        )}

        {/* ==================================================================
            2. CUSTOMER CONTEXT BAR
            ================================================================== */}
        <section
          style={{
            background: "rgba(15, 23, 42, 0.75)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "14px",
            padding: "14px 20px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div
              style={{
                width: "36px",
                height: "36px",
                borderRadius: "50%",
                background: "rgba(13, 148, 136, 0.2)",
                color: "#2dd4bf",
                display: "grid",
                placeItems: "center",
              }}
            >
              <UserCircle size={22} weight="fill" />
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <strong style={{ fontSize: "13.5px", color: "#f8fafc" }}>{customerInfo.name}</strong>
                <small style={{ color: "#94a3b8", fontSize: "11px" }}>({customerInfo.customerRef})</small>
                <span style={{ fontSize: "11px", color: "#38bdf8", background: "rgba(56, 189, 248, 0.12)", padding: "2px 6px", borderRadius: "4px" }}>
                  {customerInfo.accountType}
                </span>
              </div>
              <span style={{ fontSize: "11.5px", color: "#94a3b8" }}>
                Line: {customerInfo.phone} · Lang: {customerInfo.language} · Campaign: {customerInfo.campaign}
              </span>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <span style={{ fontSize: "11px", color: "#34d399", display: "flex", alignItems: "center", gap: "4px" }}>
              <ShieldCheck size={14} /> Consent Verified
            </span>
            <button
              className="ops-button ops-button-secondary"
              style={{ padding: "4px 10px", fontSize: "11px" }}
              onClick={() => setShowCustomerPicker((prev) => !prev)}
            >
              Switch Customer
            </button>
          </div>
        </section>

        {/* Customer picker dropdown */}
        {showCustomerPicker && (
          <div
            style={{
              background: "#0f172a",
              border: "1px solid rgba(255, 255, 255, 0.15)",
              borderRadius: "12px",
              padding: "14px",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
            }}
          >
            <span style={{ fontSize: "11.5px", fontWeight: 700, color: "#94a3b8" }}>Select Customer Profile:</span>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "8px" }}>
              {availableCustomers.map((cust, idx) => {
                const c = cust as Record<string, string>;
                return (
                  <button
                    key={idx}
                    className="scenario-pill"
                    style={{ textAlign: "left", padding: "8px 12px" }}
                    onClick={() => {
                      setCustomerInfo({
                        name: c.full_name || "Customer",
                        customerRef: c.customer_ref || `CUST-00${idx + 1}`,
                        phone: c.phone || "+91 98765 00000",
                        accountType: `${c.account_type || "Savings"} Account · Active`,
                        language: c.preferred_language || "Hindi / English",
                        campaign: "App v2.4 Upgrade Outreach",
                      });
                      setShowCustomerPicker(false);
                      void startNewSession();
                    }}
                  >
                    <strong style={{ display: "block", color: "#f8fafc", fontSize: "12px" }}>{c.full_name}</strong>
                    <small style={{ color: "#94a3b8", fontSize: "11px" }}>{c.phone} · {c.preferred_language}</small>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* ==================================================================
            3. CORE CONVERSATION INTERFACE
            ================================================================== */}
        <main
          style={{
            background: "rgba(15, 23, 42, 0.65)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            borderRadius: "20px",
            padding: "24px",
            display: "flex",
            flexDirection: "column",
            gap: "20px",
            backdropFilter: "blur(20px)",
          }}
        >
          {/* Subbu Voice Presence Stage & Action Controls */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              padding: "20px 0 10px",
              gap: "14px",
            }}
          >
            {/* Visual presence orb with dynamic aura */}
            <div
              className={`active-orb-box ${
                connected
                  ? voiceState === "SPEAKING"
                    ? "speaking"
                    : voiceState === "SILENCE_REMINDER"
                    ? "speaking"
                    : "listening"
                  : ""
              }`}
              style={{ position: "relative" }}
            >
              <div
                className={`fluid-orb-aura ${voiceState === "LISTENING" ? "fluid-orb-listening" : ""}`}
                style={{
                  transform: `scale(${1 + (audioEnergy / 100) * 0.35})`,
                  opacity: connected ? 0.6 + (audioEnergy / 100) * 0.4 : 0,
                }}
              />
              <div className="active-orb-halo" />
              <div
                className="active-orb"
                style={{
                  transform: `scale(${1 + (audioEnergy / 100) * 0.12})`,
                  transition: "transform 0.08s ease",
                }}
              >
                {voiceState === "SPEAKING" ? "AVA" : "S"}
              </div>
            </div>

            {/* True Microphone Input Level (dB / Energy) Meter */}
            {connected && !isMuted && (
              <div className="db-meter-container">
                <div className="db-meter-readout">
                  <span>INPUT LEVEL</span>
                  <strong>
                    {audioDb > -58 ? `${audioDb} dB` : "-∞ dB"} ({audioEnergy}%)
                  </strong>
                </div>
                <div className="db-meter-tracks" title={`Microphone Input Level: ${audioDb} dB`}>
                  {Array.from({ length: 14 }).map((_, idx) => {
                    const threshold = (idx + 1) * (100 / 14);
                    const isActive = audioEnergy >= threshold;
                    const isRed = idx >= 11;
                    const isAmber = idx >= 8 && idx < 11;
                    const segmentClass = isActive
                      ? isRed
                        ? "active-red"
                        : isAmber
                        ? "active-amber"
                        : "active-green"
                      : "";
                    return <div key={idx} className={`db-meter-segment ${segmentClass}`} />;
                  })}
                </div>
              </div>
            )}

            {/* Dynamic state caption */}
            <div style={{ textAlign: "center" }}>
              <div
                style={{
                  fontSize: "14px",
                  fontWeight: 700,
                  letterSpacing: "0.04em",
                  color: connected
                    ? voiceState === "SPEAKING"
                      ? "#38bdf8"
                      : voiceState === "SILENCE_REMINDER"
                      ? "#fbbf24"
                      : voiceState === "TERMINATING"
                      ? "#f87171"
                      : voiceState === "LISTENING"
                      ? "#34d399"
                      : "#a78bfa"
                    : "#94a3b8",
                }}
              >
                {connected
                  ? voiceState === "SPEAKING"
                    ? "SUBBU IS SPEAKING"
                    : voiceState === "SILENCE_REMINDER"
                    ? "REMINDING CUSTOMER (NO RESPONSE)"
                    : voiceState === "TERMINATING"
                    ? "ENDING CALL (NO RESPONSE)"
                    : voiceState === "LISTENING"
                    ? "LISTENING TO YOU"
                    : voiceState === "PROCESSING"
                    ? "THINKING & EVALUATING"
                    : voiceState === "INTERRUPTED"
                    ? "INTERRUPTED"
                    : "CONNECTED"
                  : callEnded
                  ? intent === "NO_RESPONSE"
                    ? "CALL CONCLUDED · NO RESPONSE"
                    : "INTERACTION CONCLUDED"
                  : "SUBBU READY TO CALL"}
              </div>
              <span style={{ fontSize: "11.5px", color: "#64748b" }}>
                {connected
                  ? isMuted
                    ? "Microphone muted"
                    : "Speak naturally · Automatic speech interruption and barge-in active"
                  : "Town Bank automated voice assistant calling regarding mobile app update"}
              </span>
            </div>

            {/* Primary Call Controls */}
            <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "4px" }}>
              {!connected ? (
                <button
                  className="answer-call-btn"
                  disabled={!canUseMic || voiceState === "PROCESSING"}
                  onClick={() => void answerCall()}
                  style={{ minWidth: "200px" }}
                >
                  <Phone size={20} weight="fill" />
                  <span>{callEnded ? "START NEW CALL" : "START CALL"}</span>
                </button>
              ) : (
                <>
                  <button
                    className="developer-toggle"
                    style={{ background: isMuted ? "#ef4444" : "rgba(30, 41, 59, 0.8)", color: "#fff", padding: "10px 16px", borderRadius: "10px" }}
                    onClick={toggleMute}
                    title={isMuted ? "Unmute Mic" : "Mute Mic"}
                  >
                    {isMuted ? <MicrophoneSlash size={16} /> : <Microphone size={16} />}
                    <span>{isMuted ? "Unmute" : "Mute"}</span>
                  </button>

                  <button
                    className="developer-toggle"
                    style={{ background: "rgba(30, 41, 59, 0.8)", color: "#fbbf24", padding: "10px 16px", borderRadius: "10px" }}
                    onClick={handleInterrupt}
                    title="Interrupt Subbu speaking"
                  >
                    <Hand size={16} weight="fill" />
                    <span>Interrupt</span>
                  </button>

                  <button
                    className="end-call-btn"
                    onClick={() => void closeCall(true)}
                    style={{ padding: "10px 22px" }}
                  >
                    <PhoneDisconnect size={18} weight="fill" />
                    <span>END CALL</span>
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Live Transcript Panel */}
          <div className="transcript-card" style={{ margin: 0 }}>
            <div className="transcript-header">
              <h2>Customer Conversation</h2>
              <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                {messages.length} conversational turns
              </span>
            </div>

            <div className="transcript-scroll" style={{ minHeight: "260px", maxHeight: "400px" }}>
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={`message-bubble ${m.speaker === "AVA" || m.speaker === "Subbu" ? "is-ava" : "is-customer"}`}
                >
                  <div className="message-bubble-header">
                    <span>{m.speaker === "AVA" || m.speaker === "Subbu" ? "Subbu (Town Bank Assistant)" : "CUSTOMER (You)"}</span>
                    <span>{m.time}</span>
                  </div>
                  <div>{m.text}</div>
                </div>
              ))}

              {partialText && (
                <div className="partial-live-bubble">
                  <Waveform size={15} style={{ animation: "wave-bar 0.7s infinite alternate" }} />
                  <span>{partialText}</span>
                </div>
              )}

              {!messages.length && !partialText && (
                <div style={{ color: "#64748b", fontSize: "13px", textAlign: "center", padding: "40px 20px" }}>
                  {connected ? "Subbu is initiating opening disclosure…" : "Press 'Start Call' to initiate outbound conversation with Subbu."}
                </div>
              )}
            </div>

            {/* In-Call Text Fallback Composer */}
            <div className="in-call-composer">
              <input
                placeholder="Speak into microphone or type response here…"
                value={composerText}
                onChange={(e) => setComposerText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSendText();
                }}
              />
              <button
                className="in-call-send-btn"
                disabled={!composerText.trim()}
                onClick={handleSendText}
                aria-label="Send typed turn"
              >
                <PaperPlaneRight size={16} weight="fill" />
              </button>
            </div>
          </div>

          {/* Call Completed Outcome Card */}
          {callEnded && (
            <div
              style={{
                background: "rgba(16, 185, 129, 0.08)",
                border: "1px solid rgba(16, 185, 129, 0.25)",
                borderRadius: "14px",
                padding: "16px 20px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: "14px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <CheckCircle size={26} color="#10b981" weight="fill" />
                <div>
                  <strong style={{ fontSize: "13.5px", color: "#f8fafc", display: "block" }}>
                    Call Completed · Duration: {formatDuration(finalDuration || callDuration)}
                  </strong>
                  <span style={{ fontSize: "12px", color: "#94a3b8" }}>
                    Outcome: {intent === "NO_RESPONSE" ? "Terminated (No Customer Response)" : callbackRequested ? "Callback Scheduled" : caseId ? `Support Case Created (#${caseId})` : policy === "BLOCKED" ? "Blocked by Security Guard" : "Concluded Successfully"}
                  </span>
                </div>
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                <button className="ops-button ops-button-primary" onClick={() => void answerCall()}>
                  <Phone size={14} /> Start Next Call
                </button>
              </div>
            </div>
          )}
        </main>

        {/* Global Security Badges Strip */}
        <footer className="security-status-strip">
          <span>
            <ShieldCheck size={16} /> Customer PII Redacted
          </span>
          <span>
            <Lock size={16} /> Sensitive OTP/PIN Intercepted
          </span>
          <span>
            <ShieldCheck size={16} /> Closed-World Knowledge Grounding
          </span>
          <span>
            <Clock size={16} /> TRAI Contact Window Enforced (09:00-20:00 IST)
          </span>
        </footer>

        {/* ==================================================================
            4. COLLAPSIBLE ENGINEERING DIAGNOSTICS & TELEMETRY DRAWER
            ================================================================== */}
        {showDiagnostics && (
          <>
            <div className="diagnostics-backdrop" onClick={() => setShowDiagnostics(false)} />
            <aside className="diagnostics-drawer" role="dialog" aria-label="Engineering Diagnostics">
              <div className="diagnostics-header">
                <h2>
                  <SlidersHorizontal size={18} color="#38bdf8" />
                  <span>Engineering Diagnostics &amp; Telemetry</span>
                </h2>
                <button
                  className="diagnostics-close-btn"
                  onClick={() => setShowDiagnostics(false)}
                  aria-label="Close diagnostics"
                >
                  <X size={18} />
                </button>
              </div>

              <div className="diagnostics-body">
                {/* Section 1: Measured Pipeline Latencies */}
                <div className="diagnostics-section">
                  <div className="diagnostics-section-title">
                    <Waveform size={14} /> Real-Time Latency Telemetry (ms)
                  </div>
                  <div className="latency-grid">
                    {Object.entries(TIMING_LABELS).map(([key, label]) => (
                      <div key={key} className="latency-metric">
                        <span>{label}</span>
                        <strong>{timings[key] === undefined ? "—" : `${Math.round(timings[key])} ms`}</strong>
                      </div>
                    ))}
                  </div>

                  {telemetryHistory.length > 0 && (() => {
                    const latencies = telemetryHistory.map((t) => t.stages.total_turn_response_ms);
                    const stats = calculatePercentiles(latencies);
                    return (
                      <div style={{ marginTop: "12px", fontSize: "11px", color: "#64748b", display: "flex", justifyContent: "space-between", background: "#060a13", padding: "8px 12px", borderRadius: "6px", border: "1px solid #1e293b" }}>
                        <span>Turns: <strong style={{ color: "#cbd5e1" }}>{latencies.length}</strong></span>
                        <span>P50: <strong style={{ color: "#34d399" }}>{Math.round(stats.p50)}ms</strong></span>
                        <span>P95: <strong style={{ color: "#38bdf8" }}>{Math.round(stats.p95)}ms</strong></span>
                        <span>P99: <strong style={{ color: "#f59e0b" }}>{Math.round(stats.p99)}ms</strong></span>
                      </div>
                    );
                  })()}
                </div>

                {/* Section 2: Audio Transport & Stream Diagnostics */}
                <div className="diagnostics-section">
                  <div className="diagnostics-section-title">
                    <Microphone size={14} /> Audio Stream &amp; Buffer Status
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "11.5px" }}>
                    <div>
                      <span style={{ color: "#94a3b8" }}>Mic Chunks Sent:</span>
                      <strong style={{ color: "#38bdf8", marginLeft: "6px" }}>{micFramesTransmitted}</strong>
                    </div>
                    <div>
                      <span style={{ color: "#94a3b8" }}>Server Acks:</span>
                      <strong style={{ color: "#34d399", marginLeft: "6px" }}>{serverFramesCount}</strong>
                    </div>
                    <div>
                      <span style={{ color: "#94a3b8" }}>Sample Rates:</span>
                      <strong style={{ color: "#cbd5e1", marginLeft: "6px" }}>16kHz mic / 24kHz out</strong>
                    </div>
                    <div>
                      <span style={{ color: "#94a3b8" }}>Worklet State:</span>
                      <strong style={{ color: canUseMic ? "#34d399" : "#ef4444", marginLeft: "6px" }}>
                        {canUseMic ? "Active" : "Unavailable"}
                      </strong>
                    </div>
                  </div>
                </div>

                {/* Section 3: Deterministic KURAL Decision Layer */}
                <div className="diagnostics-section">
                  <div className="diagnostics-section-title">
                    <Lock size={14} /> KURAL Decision &amp; Policy Inspector
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div className="kural-metric-row">
                      <span className="kural-metric-label">FSM STATE</span>
                      <strong className="kural-metric-val">{kuralState || "DISCLOSURE"}</strong>
                    </div>
                    <div className="kural-metric-row">
                      <span className="kural-metric-label">CLASSIFIED INTENT</span>
                      <strong className="kural-metric-val" style={{ color: "#38bdf8" }}>
                        {intent || "Awaiting Utterance"}
                      </strong>
                    </div>
                    <div className="kural-metric-row">
                      <span className="kural-metric-label">POLICY CHECK</span>
                      <span className={`kural-pill-tag ${policy === "BLOCKED" ? "kural-pill-blocked" : "kural-pill-allowed"}`}>
                        {policy || "ALLOWED"}
                      </span>
                    </div>
                    <div className="kural-metric-row">
                      <span className="kural-metric-label">INFERENCE MODE</span>
                      <span className={`kural-pill-tag ${fallbackUsed ? "kural-pill-blocked" : "kural-pill-allowed"}`}>
                        {fallbackUsed ? "⚡ Local Fallback (<2ms)" : "🤖 Live LLM Layer"}
                      </span>
                    </div>
                    <div className="kural-metric-row">
                      <span className="kural-metric-label">NLU PROVIDER / MODEL</span>
                      <strong className="kural-metric-val" style={{ color: "#38bdf8", fontSize: "11px" }}>
                        {turnTelemetry ? `${turnTelemetry.provider} · ${turnTelemetry.model}` : "Configured LLM Layer"}
                      </strong>
                    </div>

                    {secondaryQuestion && (
                      <div className="kural-metric-row">
                        <span className="kural-metric-label">SIDE QUESTION</span>
                        <strong className="kural-metric-val" style={{ color: "#fbbf24", fontSize: "11px" }}>
                          {secondaryQuestion}
                        </strong>
                      </div>
                    )}
                    <div className="kural-metric-row">
                      <span className="kural-metric-label">AUTHORIZED ACTION</span>
                      <span className="kural-pill-tag kural-pill-action">
                        {callbackRequested ? "REQUEST_CALLBACK" : caseId ? "CREATE_APP_UPDATE_CASE" : "NO_OP"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Section 4: Speech Voice Samples */}
                <div className="diagnostics-section">
                  <div className="diagnostics-section-title">
                    <Waveform size={14} /> Voice Model Samples (Dual-Voice Comparison)
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                    <div className="sample-voice-card">
                      <div className="sample-voice-info">
                        <strong>Subbu (Male · Aditya)</strong>
                        <small>Outbound Voice Assistant</small>
                      </div>
                      <button
                        className={`sample-voice-play-btn ${playingVoice === "subbu" ? "is-playing" : ""}`}
                        onClick={() => playVoiceSample("/samples/voice_subbu_male.wav", "subbu")}
                      >
                        {playingVoice === "subbu" ? "⏹ Stop" : "▶ Subbu"}
                      </button>
                    </div>

                    <div className="sample-voice-card">
                      <div className="sample-voice-info">
                        <strong>Priya (Female · Priya)</strong>
                        <small>Support Specialist</small>
                      </div>
                      <button
                        className={`sample-voice-play-btn ${playingVoice === "priya" ? "is-playing" : ""}`}
                        onClick={() => playVoiceSample("/samples/voice_priya_female.wav", "priya")}
                      >
                        {playingVoice === "priya" ? "⏹ Stop" : "▶ Priya"}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Section 5: Automated Operational Scenarios */}
                <div className="diagnostics-section">
                  <div className="diagnostics-section-title">
                    <Sparkle size={14} /> Test Phrase Triggers (Spec §20)
                  </div>
                  <div className="demo-scenarios-pills" style={{ marginBottom: "14px" }}>
                    {MASTER_DEMO_STEPS.map((sc) => (
                      <button key={sc.id} className="scenario-pill" onClick={() => handleTriggerScenario(sc)}>
                        <span style={{ color: "#38bdf8", fontWeight: 700 }}>{sc.badge}:</span> {sc.text}
                      </button>
                    ))}
                  </div>

                  <div className="diagnostics-section-title">
                    <ShieldCheck size={14} /> Golden Edge Cases
                  </div>
                  <div className="demo-scenarios-pills">
                    {GOLDEN_SCENARIOS.map((sc) => (
                      <button key={sc.id} className="scenario-pill" onClick={() => handleTriggerScenario(sc)}>
                        <span style={{ color: "#2dd4bf", fontWeight: 700 }}>{sc.badge}:</span> {sc.text}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </aside>
          </>
        )}
      </div>
    </div>
  );
}
