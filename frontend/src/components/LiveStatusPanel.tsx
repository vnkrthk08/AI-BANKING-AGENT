import { Pulse, ArrowSquareOut, Broadcast, Fingerprint, ShieldCheck } from "@phosphor-icons/react";
import type { PolicyDecision, VoiceState } from "../types";

interface LiveStatusPanelProps {
  online: boolean;
  sessionId: string | null;
  kuralState: string;
  intent: string;
  policy: PolicyDecision | null;
  caseId: string | null;
  callback: boolean;
  voiceState: VoiceState;
}

function Value({ children, tone }: { children: string; tone?: string }) {
  return <span className={`status-value ${tone ?? ""}`}>{children}</span>;
}

export function LiveStatusPanel({ online, sessionId, kuralState, intent, policy, caseId, callback, voiceState }: LiveStatusPanelProps) {
  return (
    <aside className="status-card" aria-label="KURAL live status">
      <div className="status-card-heading"><div><span className="panel-icon"><Pulse size={17} /></span><h2>KURAL live status</h2></div><span className="pulse-mark" /></div>
      <div className="status-section-label">CONVERSATION</div>
      <dl className="status-list">
        <div><dt><span className="row-icon"><Broadcast size={15} /></span>Connection</dt><dd><Value tone={online ? "value-online" : "value-offline"}>{online ? "ONLINE" : "OFFLINE"}</Value></dd></div>
        <div className="session-row"><dt><span className="row-icon"><Fingerprint size={15} /></span>Session</dt><dd title={sessionId ?? "Waiting for session"}>{sessionId ?? "—"}</dd></div>
        <div><dt>KURAL state</dt><dd><Value tone="value-state">{kuralState || "—"}</Value></dd></div>
        <div><dt>Intent</dt><dd><Value>{intent || "—"}</Value></dd></div>
      </dl>
      <div className="status-section-label policy-label"><ShieldCheck size={14} /> DECISION &amp; ACTION</div>
      <dl className="status-list status-list-lower">
        <div><dt>Policy</dt><dd><Value tone={policy === "BLOCKED" ? "value-blocked" : policy ? "value-allowed" : ""}>{policy ?? "—"}</Value></dd></div>
        <div><dt>Case</dt><dd title={caseId ?? "No case"}><Value>{caseId ? `${caseId.slice(0, 8)}…` : "NONE"}</Value></dd></div>
        <div><dt>Callback</dt><dd><Value tone={callback ? "value-allowed" : ""}>{callback ? "REQUESTED" : "NONE"}</Value></dd></div>
      </dl>
      <div className="voice-state-box"><span className="voice-state-label">VOICE</span><span className={`voice-mini voice-mini-${voiceState.toLowerCase()}`}><i />{voiceState}</span></div>
      <a className="api-docs-link" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">KURAL API <ArrowSquareOut size={14} /></a>
    </aside>
  );
}
