import { FormEvent, useState } from "react";
import { api, ApiError } from "../lib/api";

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
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "24px",
      }}
    >
      <form
        onSubmit={submit}
        style={{
          width: "100%",
          maxWidth: "420px",
          padding: "32px",
          border: "1px solid #333",
          borderRadius: "14px",
        }}
      >
        <h1>Jamil Gold AI</h1>
        <h2>Create Account</h2>

        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={{ width: "100%", padding: "12px", margin: "8px 0 18px" }}
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
            style={{ width: "100%", padding: "12px", margin: "8px 0 18px" }}
          />
        </label>

        <label>
          Confirm Password
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            minLength={8}
            required
            style={{ width: "100%", padding: "12px", margin: "8px 0 18px" }}
          />
        </label>

        {error && (
          <p style={{ color: "#ff6b6b" }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          style={{
            width: "100%",
            padding: "13px",
            cursor: "pointer",
          }}
        >
          {busy ? "Creating account..." : "Create Account"}
        </button>

        <button
          type="button"
          onClick={onBack}
          style={{
            width: "100%",
            padding: "13px",
            marginTop: "10px",
            cursor: "pointer",
          }}
        >
          Back
        </button>
      </form>
    </main>
  );
}
