import { ArrowUp, Keyboard } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";

interface TextComposerProps { disabled: boolean; onSend: (message: string) => void }

export function TextComposer({ disabled, onSend }: TextComposerProps) {
  const [value, setValue] = useState("");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = value.trim();
    if (!message || disabled) return;
    onSend(message);
    setValue("");
  }
  return (
    <form className="composer" onSubmit={submit}>
      <Keyboard size={17} className="composer-icon" />
      <label className="sr-only" htmlFor="text-message">Type a message instead</label>
      <input id="text-message" value={value} onChange={(event) => setValue(event.target.value)} placeholder="Type a message instead" disabled={disabled} maxLength={2000} />
      <button className="send-button" disabled={disabled || !value.trim()} aria-label="Send message" type="submit"><ArrowUp size={18} weight="bold" /></button>
    </form>
  );
}
