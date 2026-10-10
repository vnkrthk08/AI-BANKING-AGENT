import { useState, type FormEvent } from "react";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(null);
    try { await login(username.trim(), password); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Sign-in failed"); }
    finally { setBusy(false); }
  }

  return (
    <main className="login-shell">
      <form className="login-card" onSubmit={submit} aria-labelledby="login-title">
        <div className="login-brand">
          <img src="/logo-horizontal.png" alt="AVA Banking Demo" className="login-logo-banner" />
        </div>
        <h1 id="login-title">Sign in to Operations</h1>
        <p className="login-sub">Use the account issued by your bank administrator.</p>
        <label>Username<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
        <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {error && <p className="login-error" role="alert">{error}</p>}
        <button type="submit" disabled={busy || !username || !password}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="login-foot">Access is logged. Never share OTPs, PINs or passwords.</p>
      </form>
    </main>
  );
}
