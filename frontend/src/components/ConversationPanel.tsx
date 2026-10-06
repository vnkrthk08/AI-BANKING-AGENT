import { ChatCircleText } from "@phosphor-icons/react";
import type { TranscriptMessage } from "../types";

interface ConversationPanelProps { messages: TranscriptMessage[]; busy: boolean }

export function ConversationPanel({ messages, busy }: ConversationPanelProps) {
  return (
    <section className="conversation-card" aria-labelledby="conversation-title">
      <div className="section-heading">
        <div><span className="section-icon"><ChatCircleText size={17} /></span><h2 id="conversation-title">Live conversation</h2></div>
        <span className="live-caption"><i /> LIVE TRANSCRIPT</span>
      </div>
      <div className="transcript" aria-live="polite" aria-relevant="additions text">
        {messages.length === 0 && <p className="empty-transcript">Your conversation will appear here.</p>}
        {messages.map((message) => (
          <article className={`message message-${message.speaker.toLowerCase()}`} key={message.id}>
            <div className="message-meta"><span>{message.speaker}</span><time>{message.time}</time></div>
            <p>{message.text}</p>
          </article>
        ))}
        {busy && <div className="typing-row"><span /><span /><span /><small>AVA is preparing a response</small></div>}
      </div>
    </section>
  );
}
