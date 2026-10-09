import { Microphone, Stop } from "@phosphor-icons/react";
import type { VoiceState } from "../types";

interface AvatarStageProps {
  state: VoiceState;
  sttAvailable: boolean;
  onTalk: () => void;
  onStop: () => void;
}

const labels: Record<VoiceState, string> = {
  READY: "Ready when you are", LISTENING: "Listening to you", PROCESSING: "KURAL is thinking",
  SPEAKING: "AVA is speaking", INTERRUPTED: "Listening to you",
  SILENCE_REMINDER: "Reminding customer...", TERMINATING: "Ending call (no response)...",
  ENDED: "Conversation ended",
};

export function AvatarStage({ state, sttAvailable, onTalk, onStop }: AvatarStageProps) {
  const busy = state === "PROCESSING" || state === "SPEAKING" || state === "ENDED";
  return (
    <section className={`voice-stage voice-${state.toLowerCase()}`} aria-label="AVA voice controls">
      <div className="stage-kicker"><span className="eyebrow-line" />YOUR BANKING ASSISTANT</div>
      <div className="orb-wrap" aria-hidden="true">
        <div className="orb-halo" />
        <div className="orb-ring orb-ring-outer" />
        <div className="orb-ring orb-ring-inner" />
        <div className="ava-orb"><span className="orb-light" /><span className="orb-core">A</span></div>
        <span className="orb-spark spark-one" /><span className="orb-spark spark-two" />
      </div>
      <div className="state-lockup" aria-live="polite">
        <span className={`state-dot state-dot-${state.toLowerCase()}`} />
        <strong>{state}</strong>
      </div>
      <p className="state-caption">{labels[state]}</p>
      {state === "LISTENING" ? (
        <button className="talk-button stop-button" onClick={onStop} aria-label="Stop listening"><Stop size={20} weight="fill" /> STOP LISTENING</button>
      ) : (
        <button className="talk-button" onClick={onTalk} disabled={busy || !sttAvailable} aria-label="Talk to AVA">
          <Microphone size={20} weight="fill" /> TALK TO AVA
        </button>
      )}
      {!sttAvailable && <p className="voice-unavailable">Browser voice input unavailable — use text mode.</p>}
      <p className="voice-footnote">Voice turns are sent securely to the KURAL backend for processing.</p>
    </section>
  );
}
