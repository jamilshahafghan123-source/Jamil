import { useRef, useState } from "react";
import { api } from "../lib/api";

/**
 * Ask J Gold AI (section 50).
 *
 * Answers questions about the chart, the analysis, strategies and the
 * platform. It reaches the permission-limited support worker — the same
 * one behind the support widget — which can read and explain but holds no
 * execution capability at all.
 *
 * That boundary is enforced on the backend, not here: the worker's role
 * grants no WRITE or FINANCIAL capability, so no phrasing of a question
 * can produce a trade. This panel simply states the limit plainly so a
 * customer does not waste time asking it to buy something.
 */

interface Turn {
  id: number;
  role: "you" | "ai";
  text: string;
  facts?: { label: string; value: string }[];
  escalated?: boolean;
}

const SUGGESTIONS = [
  "What is the current read on XAUUSD?",
  "Why did the bot not take a trade today?",
  "What does my opportunity score mean?",
  "How do I build a strategy?",
];

export function AskPanel({ symbol, timeframe }: {
  symbol: string;
  timeframe: string;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setTurns((current) => [
      ...current, { id: nextId.current++, role: "you", text },
    ]);
    setDraft("");
    try {
      const answer = await api.supportAsk(text);
      setTurns((current) => [
        ...current,
        {
          id: nextId.current++,
          role: "ai",
          text: answer.answer,
          facts: answer.facts,
          escalated: answer.escalated,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach J Gold AI");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="jg-ask">
      <p className="jg-ask-scope">
        Context: {symbol} · {timeframe}
      </p>

      <div className="jg-ask-log">
        {turns.length === 0 && (
          <>
            <p className="jg-cc-note">
              Ask about the chart, an analysis, a strategy or the platform.
            </p>
            <div className="jg-ask-suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button key={suggestion} type="button" className="jg-chip"
                        disabled={busy} onClick={() => void ask(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </>
        )}

        {turns.map((turn) => (
          <div key={turn.id}
               className={turn.role === "you" ? "jg-ask-turn you" : "jg-ask-turn ai"}>
            <span className="jg-ask-who">
              {turn.role === "you" ? "You" : "J Gold AI"}
            </span>
            <p>{turn.text}</p>
            {turn.facts && turn.facts.length > 0 && (
              <dl className="jg-ask-facts">
                {turn.facts.map((fact) => (
                  <div key={fact.label}>
                    <dt>{fact.label}</dt><dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {turn.escalated && (
              <p className="jg-ask-escalated">
                Raised with a human — you will get a reply on your ticket.
              </p>
            )}
          </div>
        ))}
        {busy && <p className="jg-cc-note">Thinking…</p>}
      </div>

      {error && <p className="jg-ws-error">{error}</p>}

      <form className="jg-ask-form"
            onSubmit={(e) => { e.preventDefault(); void ask(draft); }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask about this chart…"
          aria-label="Ask J Gold AI"
          disabled={busy}
        />
        <button type="submit" className="btn sm" disabled={busy || !draft.trim()}>
          Ask
        </button>
      </form>

      <p className="jg-ask-note">
        This assistant explains — it cannot place, change or close a trade.
        That is a limit of what it is allowed to do, not a rule it is asked
        to follow, so no way of phrasing a question will get around it.
      </p>
    </div>
  );
}
