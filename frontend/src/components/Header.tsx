import { Headphones, ShieldCheck } from "@phosphor-icons/react";

interface HeaderProps { online: boolean }

export function Header({ online }: HeaderProps) {
  return (
    <header className="topbar">
      <a className="brand" href="#top" aria-label="KURAL AVA home">
        <span className="brand-mark" aria-hidden="true">K</span>
        <span className="brand-copy"><strong>KURAL</strong><small>Knowledge-driven Response &amp; Assistance Layer</small></span>
      </a>
      <div className="header-center"><span className="header-divider" /><span className="ava-wordmark">AVA</span><span className="header-role">AI Banking Voice Assistant</span></div>
      <div className="header-right">
        <span className="demo-tag"><Headphones size={14} weight="duotone" /> DEMO VOICE MODE</span>
        <span className={`connection ${online ? "is-online" : "is-offline"}`}><i />{online ? "Online" : "Offline"}</span>
        <span className="secure-note"><ShieldCheck size={15} /> Synthetic demo</span>
      </div>
    </header>
  );
}
