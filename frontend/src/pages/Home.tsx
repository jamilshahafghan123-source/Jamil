type HomeProps = {
  onLogin: () => void;
  onSignUp: () => void;
};

export function Home({ onLogin, onSignUp }: HomeProps) {
  return (
    <main style={{ minHeight: "100vh", padding: "48px", fontFamily: "Arial, sans-serif" }}>
      <section style={{ maxWidth: "1000px", margin: "0 auto" }}>
        <h1 style={{ fontSize: "48px", marginBottom: "12px" }}>
          Jamil Gold AI
        </h1>

        <h2 style={{ fontSize: "24px", fontWeight: 400, marginBottom: "24px" }}>
          Smart XAUUSD Trading
        </h2>

        <p style={{ fontSize: "18px", lineHeight: 1.6, maxWidth: "700px" }}>
          AI-powered gold market analysis for BUY, SELL and NO TRADE decisions,
          with confidence scoring, risk controls and automated demo trading.
        </p>

        <div style={{ marginTop: "32px", display: "flex", gap: "12px" }}>
          <button
            onClick={onLogin}
            style={{
              padding: "14px 24px",
              fontSize: "16px",
              cursor: "pointer",
            }}
          >
            Login
          </button>

          <button
            onClick={onSignUp}
            style={{
              padding: "14px 24px",
              fontSize: "16px",
              cursor: "pointer",
            }}
          >
            Sign Up
          </button>
        </div>

        <section style={{ marginTop: "64px" }}>
          <h3>Plans</h3>

          <p>Weekly - GBP 9.99</p>
          <p>Monthly - GBP 29.99</p>
          <p>Yearly - GBP 249.99</p>
        </section>
      </section>
    </main>
  );
}
