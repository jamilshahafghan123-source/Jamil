import { Brand } from "../components/Brand";
import { PLANS } from "../lib/pricing";

/**
 * Public home page.
 *
 * Props and callbacks are unchanged — App.tsx still drives navigation through
 * local page state, so the ADMIN / CUSTOMER gate is untouched.
 */

type HomeProps = {
  onLogin: () => void;
  onSignUp: () => void;
};

const FEATURES = [
  {
    title: "BUY / SELL / NO TRADE",
    body:
      "Every read resolves to one of three answers. NO TRADE is a valid and " +
      "frequent result — no setup is manufactured to look busy.",
  },
  {
    title: "Confidence scoring",
    body:
      "A 0–100 score built from named components so you can audit each point " +
      "rather than take a number on trust.",
  },
  {
    title: "Risk controls",
    body:
      "Risk per trade, daily loss limit, max open positions, lot cap and " +
      "spread ceiling. An emergency stop halts everything downstream.",
  },
  {
    title: "Demo trading",
    body:
      "Test entries, stops and targets against a demo account. Real trading " +
      "stays off until it is explicitly enabled server-side.",
  },
  {
    title: "Reversal logic",
    body:
      "When structure turns against an open position the engine recognises " +
      "the change rather than holding a thesis that has already failed.",
  },
];

export function Home({ onLogin, onSignUp }: HomeProps) {
  return (
    <main className="jg-home">
      <header className="jg-topbar">
        <Brand size={36} />
        <div className="jg-spacer" />
        <button type="button" className="jg-btn" onClick={onLogin}>
          Login
        </button>
        <button type="button" className="jg-btn primary" onClick={onSignUp}>
          Sign Up
        </button>
      </header>

      <section className="jg-hero">
        <Brand size={240} variant="full" showName={false} className="jg-hero-logo" />
        <h1>
          J Gold AI <span className="jg-gold">— Smart XAUUSD Trading</span>
        </h1>
        <p className="jg-lead">
          AI-powered gold market analysis for BUY, SELL and NO TRADE decisions,
          with confidence scoring, risk controls and automated demo trading.
          Every level is calculated from real price structure — the AI explains
          the result, it does not invent it.
        </p>
        <div className="jg-cta">
          <button type="button" className="jg-btn primary lg" onClick={onSignUp}>
            Sign Up
          </button>
          <button type="button" className="jg-btn lg" onClick={onLogin}>
            Login
          </button>
        </div>
        <p className="jg-disclaimer">
          Decision support only. Nothing here is financial advice, and no
          analysis is a guarantee of any outcome. Trading carries risk of loss.
        </p>
      </section>

      <section className="jg-section">
        <h2>What the platform does</h2>
        <div className="jg-grid">
          {FEATURES.map((f) => (
            <article key={f.title} className="jg-card">
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="jg-section">
        <h2>Plans</h2>
        <div className="jg-price-grid">
          {PLANS.map((plan) => (
            <article
              key={plan.id}
              className={plan.highlight ? "jg-price featured" : "jg-price"}
            >
              {plan.highlight && <span className="jg-flag">{plan.note}</span>}
              <h3>{plan.name}</h3>
              <div className="jg-amount">{plan.price}</div>
              <p className="jg-cadence">{plan.cadence}</p>
              {!plan.highlight && <p className="jg-note">{plan.note}</p>}
              <button
                type="button"
                className={plan.highlight ? "jg-btn price primary" : "jg-btn price"}
                onClick={onSignUp}
              >
                Choose Plan
              </button>
            </article>
          ))}
        </div>
      </section>

      <footer className="jg-foot">
        <Brand size={24} />
        <p>
          J Gold AI is an analysis and risk-management tool. It is not a broker,
          is not regulated as a financial adviser, and does not provide
          investment advice.
        </p>
      </footer>
    </main>
  );
}
