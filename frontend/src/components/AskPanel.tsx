import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

interface Turn {
  id: number;
  role: "user" | "assistant";
  text: string;
}

type VoiceState = "idle" | "listening" | "thinking" | "speaking";

const SUGGESTIONS = [
  "What do you think of the market right now?",
  "After this break of structure, continuation or pullback?",
  "Where is the system watching for an entry?",
  "Where should I avoid entering?",
  "Why is there no SELL setup?",
];

export function AskPanel({
  symbol,
  timeframe,
}: {
  symbol: string;
  timeframe: string;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [speechSupported, setSpeechSupported] = useState(true);

  const nextId = useRef(1);
  const recognitionRef = useRef<any>(null);
  const askRef = useRef<(question: string) => void>(() => {});

  useEffect(() => {
    const w = window as any;
    const Recognition =
      w.SpeechRecognition || w.webkitSpeechRecognition;

    if (!Recognition) {
      setSpeechSupported(false);
      return;
    }

    const recognition = new Recognition();
    recognition.lang = "en-GB";
    recognition.interimResults = false;
    recognition.continuous = false;

    recognition.onstart = () => {
      setError(null);
      setVoiceState("listening");
    };

    recognition.onresult = (event: any) => {
      const transcript =
        event?.results?.[0]?.[0]?.transcript?.trim() ?? "";

      if (transcript) {
        askRef.current(transcript);
      }
    };

    recognition.onerror = (event: any) => {
      setVoiceState("idle");

      const code = event?.error ?? "unknown";

      if (code === "not-allowed" || code === "service-not-allowed") {
        setError(
          "Microphone permission is blocked. Allow microphone access for J Gold.",
        );
      } else if (code !== "no-speech" && code !== "aborted") {
        setError(`Voice recognition error: ${code}`);
      }
    };

    recognition.onend = () => {
      setVoiceState((current) =>
        current === "listening" ? "idle" : current,
      );
    };

    recognitionRef.current = recognition;

    return () => {
      try {
        recognition.abort();
      } catch {
        // Browser may already have stopped recognition.
      }

      window.speechSynthesis?.cancel();
    };
  }, []);

  function stopSpeaking() {
    window.speechSynthesis?.cancel();
    setVoiceState("idle");
  }

  function speak(text: string) {
    if (!voiceEnabled || !("speechSynthesis" in window)) {
      setVoiceState("idle");
      return;
    }

    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-GB";
    utterance.rate = 1;
    utterance.pitch = 1;

    utterance.onstart = () => {
      setVoiceState("speaking");
    };

    utterance.onend = () => {
      setVoiceState("idle");
    };

    utterance.onerror = () => {
      setVoiceState("idle");
    };

    window.speechSynthesis.speak(utterance);
  }

  function startListening() {
    if (!speechSupported || busy) return;

    stopSpeaking();

    try {
      recognitionRef.current?.start();
    } catch {
      // start() can throw if recognition is already running.
    }
  }

  function stopListening() {
    try {
      recognitionRef.current?.stop();
    } catch {
      // Already stopped.
    }

    setVoiceState("idle");
  }

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;

    stopListening();

    const history = turns.map((turn) => ({
      role: turn.role,
      text: turn.text,
    }));

    const mine: Turn = {
      id: nextId.current++,
      role: "user",
      text,
    };

    setTurns((current) => [...current, mine]);
    setDraft("");
    setBusy(true);
    setError(null);
    setVoiceState("thinking");

    try {
      const result = await api.ownerTraderAsk(
        text,
        symbol,
        timeframe,
        history,
      );

      setTurns((current) => [
        ...current,
        {
          id: nextId.current++,
          role: "assistant",
          text: result.answer,
        },
      ]);

      if (voiceEnabled) {
        speak(result.answer);
      } else {
        setVoiceState("idle");
      }
    } catch (err) {
      setVoiceState("idle");
      setError(
        err instanceof Error
          ? err.message
          : "Could not reach J Gold.",
      );
    } finally {
      setBusy(false);
    }
  }

  askRef.current = (question: string) => {
    void ask(question);
  };

  const stateLabel =
    voiceState === "listening"
      ? "Listening"
      : voiceState === "thinking"
        ? "Thinking"
        : voiceState === "speaking"
          ? "Speaking"
          : "Ready";

  return (
    <div className="jg-ask">
      <p className="jg-ask-scope">
        Private J Gold ? {symbol} ? {timeframe}
      </p>

      <div
        style={{
          display: "flex",
          gap: "8px",
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: "10px",
        }}
      >
        <span className="jg-chip active">
          {stateLabel}
        </span>

        <button
          type="button"
          className="btn sm"
          onClick={
            voiceState === "listening"
              ? stopListening
              : startListening
          }
          disabled={!speechSupported || busy}
          title="Talk to J Gold"
        >
          {voiceState === "listening" ? "Stop mic" : "Talk"}
        </button>

        <button
          type="button"
          className="btn sm"
          onClick={() => {
            if (voiceEnabled) {
              stopSpeaking();
            }
            setVoiceEnabled((value) => !value);
          }}
        >
          {voiceEnabled ? "Mute voice" : "Voice on"}
        </button>

        <button
          type="button"
          className="btn sm"
          onClick={stopSpeaking}
          disabled={voiceState !== "speaking"}
        >
          Stop speaking
        </button>
      </div>

      {!speechSupported && (
        <p className="jg-ws-error">
          Voice recognition is not supported by this browser.
          Text chat still works.
        </p>
      )}

      <div className="jg-ask-log">
        {turns.length === 0 && (
          <>
            <p className="jg-cc-note">
              Talk naturally to J Gold about the live XAUUSD market.
              It can discuss BOS, CHoCH, pullbacks, continuation,
              EMA, FVG, support, resistance, liquidity, signals,
              positions and risk.
            </p>

            <div className="jg-ask-suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="jg-chip"
                  disabled={busy}
                  onClick={() => void ask(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </>
        )}

        {turns.map((turn) => (
          <div
            key={turn.id}
            className={
              turn.role === "user"
                ? "jg-ask-turn you"
                : "jg-ask-turn ai"
            }
          >
            <span className="jg-ask-who">
              {turn.role === "user" ? "You" : "J Gold"}
            </span>
            <p>{turn.text}</p>
          </div>
        ))}

        {voiceState === "listening" && (
          <p className="jg-cc-note">
            J Gold is listening...
          </p>
        )}

        {voiceState === "thinking" && (
          <p className="jg-cc-note">
            J Gold is reading the market and thinking...
          </p>
        )}

        {voiceState === "speaking" && (
          <p className="jg-cc-note">
            J Gold is speaking...
          </p>
        )}
      </div>

      {error && <p className="jg-ws-error">{error}</p>}

      <form
        className="jg-ask-form"
        onSubmit={(event) => {
          event.preventDefault();
          void ask(draft);
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Talk or type to J Gold..."
          aria-label="Talk to J Gold"
          disabled={busy}
        />

        <button
          type="submit"
          className="btn sm"
          disabled={busy || !draft.trim()}
        >
          Send
        </button>
      </form>

      <p className="jg-ask-note">
        Normal conversation never places a trade. Trading execution
        remains behind the bot and risk controls.
      </p>
    </div>
  );
}
