import { PLANS } from "../lib/pricing";
import { Brand } from "../components/Brand";
import { SupportChat } from "../components/SupportChat";

/**
 * Subscription gate for CUSTOMER accounts.
 *
 * App.tsx renders this instead of the dashboard whenever the signed-in user
 * is a CUSTOMER, so this page is what enforces the paywall in the UI. The
 * props and the gate itself are unchanged.
 *
 * There is no payment provider wired up yet: the plan buttons are inert and
 * say so, rather than pretending to start a checkout that does not exist.
 */

type SubscriptionRequiredProps = {
  email: string;
  onLogout: () => void;
};

export function SubscriptionRequired({
  email,
  onLogout,
}: SubscriptionRequiredProps) {
  return (
    <main className="jg-gate">
      <header className="jg-topbar">
        <Brand size={36} />
        <div className="jg-spacer" />
        <button type="button" className="jg-btn" onClick={onLogout}>
          Sign out
        </button>
      </header>

      <section className="jg-section jg-gate-head">
        <h1>Choose your plan</h1>
        <p className="jg-lead">
          An active subscription is required to open the trading dashboard.
        </p>
        <p className="jg-signed-in">Signed in as {email}</p>
      </section>

      <section className="jg-section">
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
              <button type="button" className="jg-btn price" disabled>
                Choose Plan
              </button>
            </article>
          ))}
        </div>
        <p className="jg-disclaimer">
          Payments are not connected yet, so these buttons do not charge
          anything. Prices are shown in GBP.
        </p>
      </section>

      <SupportChat />
    </main>
  );
}
