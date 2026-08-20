import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

/**
 * "Ask J Gold AI Support" — the customer-facing surface for the
 * permission-limited support worker.
 *
 * The worker runs server-side as WorkerRole.SUPPORT and can only READ and
 * RECOMMEND, so nothing typed here can become a trade, a payment or a
 * settings change. This component reflects that: it renders an answer and,
 * when support escalates, a ticket reference. It offers no action buttons,
 * because there is no action for it to offer.
 *
 * Answers to factual questions are computed server-side from real account
 * state, so `facts` carries the numbers the answer was built from and they
 * are shown alongside it — a customer can check the explanation rather than
 * take it on trust.
 */

type Turn = {
  id: number;
  who: "you" | "support";
  text: string;
  facts?: { label: string; value: string }[];
  ticketId?: number | null;
};

const SUGGESTIONS = [
  "Why isn't the bot trading?",
  "Is my broker connected?",
  "What does NO TRADE mean?",
  "What does RR mean?",
  "How does demo mode work?",
  "Where do deposits and withdrawals go?",
];

export function SupportChat() {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const nextId = useRef(1);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns, open]);

  async function send(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setError(null);
    setDraft("");
    setTurns((t) => [...t, { id: nextId.current++, who: "you", text }]);
    setBusy(true);
    try {
      const res = await api.supportAsk(text);
      setTurns((t) => [
        ...t,
        {
          id: nextId.current++,
          who: "support",
          text: res.answer,
          facts: res.facts,
          ticketId: res.escalated ? res.ticket_id : null,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Support is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="jg-support-launch"
        onClick={() => setOpen(true)}
      >
        Ask J Gold AI Support
      </button>
    );
  }

  return (
    <section className="jg-support" aria-label="J Gold AI Support">
      <header className="jg-support-head">
        <span className="jg-support-title">Ask J Gold AI Support</span>
        <button
          type="button"
          className="jg-support-close"
          onClick={() => setOpen(false)}
          aria-label="Close support"
        >
          ×
        </button>
      </header>

      <div className="jg-support-log">
        {turns.length === 0 && (
          <div className="jg-support-intro">
            <p>
              Support reads your live account status to answer. It can explain
              and recommend — it cannot place trades or change your settings.
            </p>
            <div className="jg-support-chips">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="jg-support-chip"
                  onClick={() => send(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn) => (
          <div key={turn.id} className={`jg-turn jg-turn-${turn.who}`}>
            <p>{turn.text}</p>
            {turn.facts && turn.facts.length > 0 && (
              <dl className="jg-support-facts">
                {turn.facts.map((f) => (
                  <div key={f.label}>
                    <dt>{f.label.replace(/_/g, " ")}</dt>
                    <dd>{f.value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {turn.ticketId != null && (
              <p className="jg-support-ticket">
                Ticket #{turn.ticketId} raised for an administrator.
              </p>
            )}
          </div>
        ))}

        {busy && <div className="jg-turn jg-turn-support jg-support-wait">…</div>}
        {error && <p className="jg-support-error">{error}</p>}
        <div ref={endRef} />
      </div>

      <form
        className="jg-support-compose"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask a question…"
          maxLength={2000}
          aria-label="Your question"
        />
        <button type="submit" className="jg-btn primary" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
