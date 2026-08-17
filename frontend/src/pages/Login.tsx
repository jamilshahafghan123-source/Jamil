import { useState, type FormEvent } from "react";
import { api, auth } from "../lib/api";
import { Banner } from "../components/Primitives";

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.login(email.trim().toLowerCase(), password);
      auth.set(res.access_token);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand" style={{ marginBottom: 14 }}>
          <span className="mark">◆</span>
          <span>MT5 AI Analyst</span>
        </div>
        <h1>Sign in</h1>
        <p className="tagline">XAUUSD market analysis and risk-managed execution.</p>

        {error && (
          <div style={{ marginBottom: 14 }}>
            <Banner tone="err">{error}</Banner>
          </div>
        )}

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        <button
          className="btn primary"
          style={{ width: "100%", marginTop: 4 }}
          disabled={busy}
          type="submit"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="tagline" style={{ marginTop: 18, marginBottom: 0 }}>
          Broker credentials are never entered here. They live only on the MT5
          bridge host.
        </p>
      </form>
    </div>
  );
}
