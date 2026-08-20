import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { Banner } from "../components/Primitives";
import { Brand } from "../components/Brand";

/**
 * Registration page.
 *
 * Props and the api.register() call are unchanged — only the presentation is
 * rebranded. New accounts are still created as CUSTOMER server-side, so this
 * page cannot grant dashboard access on its own.
 */

type SignUpProps = {
  onBack: () => void;
  onRegistered: () => void;
};

export function SignUp({ onBack, onRegistered }: SignUpProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setBusy(true);

    try {
      await api.register(email, password);
      onRegistered();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Could not create account");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <Brand size={40} className="jg-auth-brand" />
        <h1>Create account</h1>
        <p className="tagline">
          Sign up to access XAUUSD analysis, risk controls and demo trading.
        </p>

        {error && (
          <div style={{ marginBottom: 14 }}>
            <Banner tone="err">{error}</Banner>
          </div>
        )}

        <div className="field">
          <label htmlFor="signup-email">Email</label>
          <input
            id="signup-email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>

        <div className="field">
          <label htmlFor="signup-password">Password</label>
          <input
            id="signup-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
          <span className="hint">At least 8 characters.</span>
        </div>

        <div className="field">
          <label htmlFor="signup-confirm">Confirm password</label>
          <input
            id="signup-confirm"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            minLength={8}
            required
          />
        </div>

        <button
          type="submit"
          className="btn primary"
          style={{ width: "100%", marginTop: 4 }}
          disabled={busy}
        >
          {busy ? "Creating account…" : "Create account"}
        </button>

        <button
          type="button"
          className="btn"
          style={{ width: "100%", marginTop: 10 }}
          onClick={onBack}
        >
          Back
        </button>

        <p className="tagline" style={{ marginTop: 18, marginBottom: 0 }}>
          Broker credentials are never entered here. They live only on the MT5
          bridge host.
        </p>
      </form>
    </div>
  );
}
