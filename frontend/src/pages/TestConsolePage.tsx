import { useEffect, useRef, useState } from "react";
import {
  ArrowCounterClockwise,
  CheckCircle,
  Lock,
  Microphone,
  MicrophoneSlash,
  PaperPlaneRight,
  Phone,
  PhoneDisconnect,
  ShieldCheck,
  Sparkle,
  Waveform,
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

const DEMO_SCENARIOS: DemoScenario[] = [
  { id: "normal", label: "Normal customer", text: "Yes, speaking.", badge: "Affirm" },
  { id: "busy", label: "Busy / Callback", text: "I'm busy right now, call me later.", badge: "Callback" },
  { id: "issue", label: "App update issue", text: "My banking application is not updating.", badge: "Issue" },
  { id: "sensitive", label: "Sensitive data guard", text: "My OTP is 123456.", badge: "Security" },
  { id: "human", label: "Human escalation", text: "I want to speak with a human agent.", badge: "Escalate" },
  { id: "wrong", label: "Wrong person", text: "No, this is not the customer.", badge: "Exit" },
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

  const [online, setOnline] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [voiceState, setVoiceState] = useState<VoiceState>("READY");
  const [kuralState, setKuralState] = useState("DISCLOSURE");
  const [intent, setIntent] = useState("");
  const [policy, setPolicy] = useState<PolicyDecision | null>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  const [callbackRequested, setCallbackRequested] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [partialText, setPartialText] = useState("");
  const [connected, setConnected] = useState(false);
  const [callEnded, setCallEnded] = useState(false);
  const [callDuration, setCallDuration] = useState(0);
  const [finalDuration, setFinalDuration] = useState(0);
  const [showTimings, setShowTimings] = useState(false);
  const [showDebug, setShowDebug] = useState(true);
  const [showTranscriptModal, setShowTranscriptModal] = useState(false);
  const [timings, setTimings] = useState<Record<string, number>>({});
  const [isMuted, setIsMuted] = useState(false);
  const [composerText, setComposerText] = useState("");
  const [reachedStates, setReachedStates] = useState<string[]>(["Connected", "Disclosure"]);

  const timingsRef = useRef<Record<string, number>>({});

  function recordTiming(name: string, value = performance.now() - callStartedAtRef.current) {
    timingsRef.current = { ...timingsRef.current, [name]: value };
    setTimings((current) => ({ ...current, [name]: value }));
  }

  function sendClientTiming(name: string) {
    const elapsed = performance.now() - callStartedAtRef.current;
    recordTiming(name, elapsed);
    voiceConnectionRef.current?.sendTiming(name, elapsed);
  }

  function stopPlayback() {
    for (const source of playingSourcesRef.current) {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
      source.disconnect();
    }
    playingSourcesRef.current.clear();
    nextAudioTimeRef.current = audioContextRef.current?.currentTime ?? 0;
  }

  function stopMicrophone() {
    captureNodeRef.current?.port.close();
    captureNodeRef.current?.disconnect();
    captureNodeRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
  }

  function toggleMute() {
    if (micStreamRef.current) {
      const audioTracks = micStreamRef.current.getAudioTracks();
      audioTracks.forEach((track) => {
        track.enabled = isMuted;
      });
      setIsMuted(!isMuted);
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
    if (!context || context.state !== "running") return;

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
    playingSourcesRef.current.add(source);

    source.onended = () => {
      source.disconnect();
      playingSourcesRef.current.delete(source);
      if (!playingSourcesRef.current.size) {
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
        setReachedStates((prev) => Array.from(new Set([...prev, "Connected", "Identity Check"])));
        break;

      case "assistant_message": {
        const now = Date.now();
        const text = String(message.text ?? "");
        setMessages((current) => [...current, { id: `${now}-ava`, speaker: "AVA", text, time: formatTime() }]);
        const stateStr = String(message.state ?? "");
        setKuralState(stateStr);
        if (stateStr) {
          setReachedStates((prev) => Array.from(new Set([...prev, stateStr])));
        }
        setIntent(String(message.intent ?? ""));
        setPolicy((message.policy_decision as PolicyDecision | undefined) ?? null);
        setCaseId((message.case_id as string | null | undefined) ?? null);
        setCallbackRequested(Boolean(message.callback_id));
        setPartialText("");
        if (message.ended) {
          callEndingPendingRef.current = true;
          allTtsChunksReceivedRef.current = false;
          setReachedStates((prev) => Array.from(new Set([...prev, "Ended"])));
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

        setMessages((current) => [...current, { id: `${now}-customer`, speaker: "CUSTOMER", text, time: formatTime() }]);
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

      case "tts_error":
      case "voice_error":
        setError(String(message.detail ?? "Voice service encountered an issue. Typed responses remain active."));
        if (message.fatal) {
          void closeCall(false);
        }
        break;

      case "call_ended":
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
    intentionalCloseRef.current = false;
    callEndingPendingRef.current = false;
    allTtsChunksReceivedRef.current = false;
    const session = await kuralApi.createSession();
    setSessionId(session.session_id);
    setKuralState(session.state);
    setIntent("");
    setPolicy(null);
    setCaseId(null);
    setCallbackRequested(false);
    setMessages([]);
    setError(null);
    setPartialText("");
    setTimings({});
    timingsRef.current = {};
    setCallEnded(false);
    setCallDuration(0);
    setFinalDuration(0);
    setVoiceState("READY");
    setReachedStates(["Connected", "Disclosure"]);
  }

  async function answerCall() {
    if (!sessionId || connected) return;
    setError(null);
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
      await context.resume(); // Unlocks playback in the user click gesture

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
        sessionId,
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
          ? "Microphone access was denied. Please allow microphone permission to talk with AVA."
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

  return (
    <div className="voice-agent-root">
      <div className="voice-agent-container">
        {/* Top bar */}
        <header className="voice-topbar">
          <div className="voice-brand-pill">
            <div className="voice-brand-logo">K</div>
            <div className="voice-brand-title">
              <strong>KURAL AVA</strong>
              <span>Banking Voice Operations · Demo Outbound Service</span>
            </div>
          </div>

          <div className="voice-topbar-controls">
            <span style={{ fontSize: "11px", color: online ? "#34d399" : "#f87171", fontWeight: 600 }}>
              {online ? "● Backend Connected" : "● Offline"}
            </span>

            <div className={`voice-call-status-badge ${connected ? "is-live" : callEnded ? "is-ended" : ""}`}>
              {connected && <span className="live-pulse-dot" />}
              <span>{connected ? "LIVE CALL" : callEnded ? "CALL ENDED" : "READY TO CONNECT"}</span>
            </div>

            {connected && <div className="voice-timer">{formatDuration(callDuration)}</div>}

            <button
              className="developer-toggle"
              style={{ padding: "6px 12px", fontSize: "11px" }}
              onClick={() => setShowTimings((v) => !v)}
              aria-expanded={showTimings}
            >
              <Waveform size={14} /> {showTimings ? "Hide Latency" : "Latency Timings"}
            </button>
          </div>
        </header>

        {/* Global Error Banner */}
        {error && (
          <div className="error-banner" role="alert" style={{ margin: 0, borderRadius: 12 }}>
            <strong>Voice Notification:</strong> {error}
          </div>
        )}

        {/* Latency Timings Drawer */}
        {showTimings && (
          <div className="latency-panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: "12px", fontWeight: 700, color: "#38bdf8" }}>
                Voice Pipeline Telemetry (Measured Latencies)
              </span>
              <span style={{ fontSize: "10px", color: "#94a3b8" }}>Realtime STT (Saaras) · Gemini · Bulbul v3 TTS</span>
            </div>
            <div className="latency-grid">
              {Object.entries(TIMING_LABELS).map(([key, label]) => (
                <div key={key} className="latency-metric">
                  <span>{label}</span>
                  <strong>{timings[key] === undefined ? "—" : `${Math.round(timings[key])} ms`}</strong>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ------------------------------------------------------------------
            STATE 1: INCOMING CALL SCREEN (Before Answering)
            ------------------------------------------------------------------ */}
        {!connected && !callEnded && (
          <section className="incoming-call-hero">
            <div className="incoming-eyebrow">Incoming Outbound Assistance Call</div>

            <div className="hero-orb-wrapper">
              <div className="hero-orb-ring-outer" />
              <div className="hero-orb-ring-inner" />
              <div className="hero-orb-core">A</div>
            </div>

            <h1>AVA</h1>
            <p>
              AI Voice Assistant calling on behalf of your bank regarding mobile app updates.
            </p>

            <button
              className="answer-call-btn"
              disabled={!sessionId || !canUseMic || voiceState === "PROCESSING"}
              onClick={() => void answerCall()}
            >
              <Phone size={22} weight="fill" />
              {voiceState === "PROCESSING" ? "CONNECTING SERVICE…" : "ANSWER CALL"}
            </button>

            {!canUseMic && (
              <p style={{ color: "#ef4444", fontSize: "12px", marginTop: "16px" }}>
                This browser environment does not support audio worklet microphone capture.
              </p>
            )}

            <div style={{ marginTop: "40px", width: "100%", maxWidth: "680px" }}>
              <div className="demo-scenarios-section">
                <div className="demo-scenarios-title">
                  <Sparkle size={14} /> Quick Demo Scenarios (Click to test natural flow)
                </div>
                <div className="demo-scenarios-pills">
                  {DEMO_SCENARIOS.map((sc) => (
                    <button
                      key={sc.id}
                      className="scenario-pill"
                      onClick={() => handleTriggerScenario(sc)}
                    >
                      <span style={{ color: "#2dd4bf", fontWeight: 700 }}>{sc.badge}:</span> {sc.text}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        {/* ------------------------------------------------------------------
            STATE 2: ACTIVE LIVE CALL SCREEN (When Connected)
            ------------------------------------------------------------------ */}
        {connected && (
          <section className="active-call-grid">
            <div className="active-call-main">
              {/* Central Dynamic Interactive Orb */}
              <div className={`voice-orb-stage voice-state-${voiceState.toLowerCase()}`}>
                <div className="active-orb-box">
                  <div className="active-orb-halo" />
                  <div className="active-orb">A</div>
                </div>

                {/* Animated Equalizer Waveform */}
                <div className="waveform-container">
                  <div className="waveform-bar" />
                  <div className="waveform-bar" />
                  <div className="waveform-bar" />
                  <div className="waveform-bar" />
                  <div className="waveform-bar" />
                  <div className="waveform-bar" />
                  <div className="waveform-bar" />
                </div>

                {/* Dynamic Status Caption */}
                <div className="active-state-caption">
                  {voiceState === "SPEAKING" ? (
                    <>
                      <span style={{ color: "#38bdf8" }}>AVA IS SPEAKING</span>
                      <small style={{ color: "#64748b" }}>· (Start speaking to interrupt)</small>
                    </>
                  ) : voiceState === "LISTENING" ? (
                    <>
                      <span style={{ color: "#34d399" }}>LISTENING TO YOU</span>
                      <small style={{ color: "#64748b" }}>· (Microphone active)</small>
                    </>
                  ) : voiceState === "PROCESSING" ? (
                    <>
                      <span style={{ color: "#a78bfa" }}>THINKING & PROCESSING</span>
                      <small style={{ color: "#64748b" }}>· KURAL evaluating</small>
                    </>
                  ) : voiceState === "INTERRUPTED" ? (
                    <>
                      <span style={{ color: "#fbbf24" }}>INTERRUPTED</span>
                      <small style={{ color: "#64748b" }}>· Switched to listening</small>
                    </>
                  ) : (
                    "CONNECTED"
                  )}
                </div>

                <div className="barge-in-hint">
                  Continuous live audio — speaks naturally without pressing stop.
                </div>

                {/* Call Control Buttons */}
                <div className="call-action-row">
                  <button
                    className="developer-toggle"
                    style={{ background: isMuted ? "#f87171" : "#1e293b", color: "#fff" }}
                    onClick={toggleMute}
                    title={isMuted ? "Unmute Mic" : "Mute Mic"}
                  >
                    {isMuted ? <MicrophoneSlash size={18} /> : <Microphone size={18} />}
                    {isMuted ? "Unmute" : "Mute"}
                  </button>

                  <button className="end-call-btn" onClick={() => void closeCall(true)}>
                    <PhoneDisconnect size={20} weight="fill" />
                    END CALL
                  </button>
                </div>
              </div>

              {/* Live Transcript Stream */}
              <div className="transcript-card">
                <div className="transcript-header">
                  <h2>Live Conversation</h2>
                  <span style={{ fontSize: "11px", color: "#94a3b8" }}>
                    Turn #{messages.length}
                  </span>
                </div>

                <div className="transcript-scroll">
                  {messages.map((m) => (
                    <div
                      key={m.id}
                      className={`message-bubble ${m.speaker === "AVA" ? "is-ava" : "is-customer"}`}
                    >
                      <div className="message-bubble-header">
                        <span>{m.speaker === "AVA" ? "AVA (Bank Assistant)" : "CUSTOMER (You)"}</span>
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
                    <div style={{ color: "#64748b", fontSize: "12px", textAlign: "center", padding: "20px" }}>
                      AVA is initiating the opening disclosure…
                    </div>
                  )}
                </div>

                {/* In-Call Quick Scenarios */}
                <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", paddingTop: "12px" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8", marginBottom: "8px", fontWeight: 600 }}>
                    Quick Talking Scenarios:
                  </div>
                  <div className="demo-scenarios-pills">
                    {DEMO_SCENARIOS.map((sc) => (
                      <button
                        key={sc.id}
                        className="scenario-pill"
                        style={{ padding: "5px 10px", fontSize: "11px" }}
                        onClick={() => handleTriggerScenario(sc)}
                      >
                        {sc.text}
                      </button>
                    ))}
                  </div>
                </div>

                {/* In-Call Typed Fallback Composer */}
                <div className="in-call-composer">
                  <input
                    placeholder="Speak or type a message into the call…"
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
                  >
                    <PaperPlaneRight size={16} weight="fill" />
                  </button>
                </div>
              </div>
            </div>

            {/* Right Sidebar: KURAL Decision & Policy Engine */}
            <aside className="kural-sidebar">
              <div className="kural-panel-card">
                <h3>
                  <span>KURAL Decision Layer</span>
                  <button
                    className="developer-toggle"
                    style={{ padding: "4px 8px", fontSize: "10px" }}
                    onClick={() => setShowDebug(!showDebug)}
                  >
                    {showDebug ? "Hide" : "Show"}
                  </button>
                </h3>

                {showDebug && (
                  <div>
                    <div className="kural-metric-row">
                      <span className="kural-metric-label">CURRENT STATE</span>
                      <strong className="kural-metric-val">{kuralState || "—"}</strong>
                    </div>

                    <div className="kural-metric-row">
                      <span className="kural-metric-label">DETECTED INTENT</span>
                      <strong className="kural-metric-val" style={{ color: "#38bdf8" }}>
                        {intent || "—"}
                      </strong>
                    </div>

                    <div className="kural-metric-row">
                      <span className="kural-metric-label">POLICY DECISION</span>
                      <span
                        className={`kural-pill-tag ${
                          policy === "BLOCKED" ? "kural-pill-blocked" : "kural-pill-allowed"
                        }`}
                      >
                        {policy || "ALLOWED"}
                      </span>
                    </div>

                    <div className="kural-metric-row">
                      <span className="kural-metric-label">AUTHORIZED ACTION</span>
                      <span className="kural-pill-tag kural-pill-action">
                        {callbackRequested
                          ? "REQUEST_CALLBACK"
                          : caseId
                          ? "CREATE_APP_UPDATE_CASE"
                          : "NO_OP"}
                      </span>
                    </div>

                    <div className="kural-metric-row">
                      <span className="kural-metric-label">CONFIDENCE THRESHOLD</span>
                      <strong className="kural-metric-val">&gt; 0.45 MIN</strong>
                    </div>

                    <div style={{ fontSize: "10.5px", color: "#64748b", marginTop: "12px", lineHeight: 1.5 }}>
                      Deterministic rules enforce policy boundaries. Gemini classifies intent; it cannot authorize actions.
                    </div>
                  </div>
                )}
              </div>

              {/* Call Timeline */}
              <div className="kural-panel-card">
                <h3>Call Progression Timeline</h3>
                <div className="call-timeline-stepper">
                  {reachedStates.map((st, idx) => (
                    <div
                      key={st}
                      className={`timeline-step ${
                        idx === reachedStates.length - 1 ? "is-active" : "is-past"
                      }`}
                    >
                      <div className="timeline-step-icon">✓</div>
                      <span>{st}</span>
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          </section>
        )}

        {/* ------------------------------------------------------------------
            STATE 3: CALL COMPLETED SUMMARY SCREEN (After Ending Call)
            ------------------------------------------------------------------ */}
        {callEnded && (
          <section className="call-summary-card">
            <div className="summary-check-icon">
              <CheckCircle size={32} weight="fill" />
            </div>

            <h2>CALL COMPLETED</h2>
            <p>Outbound customer service interaction has been concluded and persisted.</p>

            <div className="summary-metrics-grid">
              <div className="summary-metric-box">
                <span>Call Duration</span>
                <strong>{formatDuration(finalDuration || callDuration)}</strong>
              </div>

              <div className="summary-metric-box">
                <span>Final Intent</span>
                <strong>{intent || "Call Concluded"}</strong>
              </div>

              <div className="summary-metric-box">
                <span>Business Outcome</span>
                <strong>
                  {callbackRequested
                    ? "Callback Request Created"
                    : caseId
                    ? "App Update Case Created"
                    : policy === "BLOCKED"
                    ? "Blocked (Sensitive Data Protected)"
                    : "Conversation Completed"}
                </strong>
              </div>

              <div className="summary-metric-box">
                <span>Security Status</span>
                <strong style={{ color: "#34d399" }}>Sensitive Data Guard Active</strong>
              </div>

              {callbackRequested && (
                <div className="summary-metric-box" style={{ gridColumn: "1 / -1" }}>
                  <span>Callback Ticket</span>
                  <strong style={{ color: "#38bdf8" }}>Requested · Scheduled for support team</strong>
                </div>
              )}

              {caseId && (
                <div className="summary-metric-box" style={{ gridColumn: "1 / -1" }}>
                  <span>Support Case ID</span>
                  <strong style={{ color: "#38bdf8" }}>{caseId}</strong>
                </div>
              )}
            </div>

            <div className="summary-actions-row">
              <button
                className="new-call-btn"
                onClick={() => void startNewSession().catch((c) => setError(String(c)))}
              >
                <ArrowCounterClockwise size={18} />
                NEW CALL
              </button>

              <button
                className="view-transcript-btn"
                onClick={() => setShowTranscriptModal(!showTranscriptModal)}
              >
                {showTranscriptModal ? "HIDE TRANSCRIPT" : "VIEW FULL TRANSCRIPT"}
              </button>
            </div>

            {/* Expandable Complete Transcript View */}
            {showTranscriptModal && (
              <div style={{ marginTop: "28px", width: "100%", textAlign: "left" }}>
                <h3 style={{ fontSize: "14px", color: "#f8fafc", marginBottom: "12px" }}>
                  Complete Interaction Transcript ({messages.length} turns)
                </h3>
                <div
                  className="transcript-scroll"
                  style={{
                    maxHeight: "350px",
                    background: "rgba(15, 23, 42, 0.6)",
                    padding: "16px",
                    borderRadius: "14px",
                    border: "1px solid rgba(255, 255, 255, 0.08)",
                  }}
                >
                  {messages.map((m) => (
                    <div
                      key={m.id}
                      className={`message-bubble ${m.speaker === "AVA" ? "is-ava" : "is-customer"}`}
                    >
                      <div className="message-bubble-header">
                        <span>{m.speaker}</span>
                        <span>{m.time}</span>
                      </div>
                      <div>{m.text}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        {/* Global Security Badges Strip */}
        <footer className="security-status-strip">
          <span>
            <ShieldCheck size={16} /> Customer Data Protected
          </span>
          <span>
            <Lock size={16} /> Sensitive-Data Guard (OTP/PIN Blocked)
          </span>
          <span>
            <ShieldCheck size={16} /> Approved Knowledge
          </span>
          <span>
            <ShieldCheck size={16} /> Audit Trail Persisted
          </span>
        </footer>
      </div>
    </div>
  );
}
