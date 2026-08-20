import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import {
  FALLBACK_LOCALE, LOCALES, getLocale, isRTL, translate,
} from "./index";

/**
 * Language preference and document direction (sections 46, 47).
 *
 * The preference is kept in browser storage so a signed-out visitor keeps
 * their choice, and read back defensively: a private window or blocked
 * storage falls back to English (UK) rather than throwing.
 *
 * RTL is applied to the document element only. It flips reading order for
 * text and controls — and deliberately stops there. Charts, candles, the
 * price scale and the time axis are NOT mirrored: time runs left to right
 * in every market on earth, and reversing it would make an Arabic chart
 * unreadable to the same trader who reads Arabic. Numbers stay in Western
 * digits for the same reason.
 */

const STORAGE_KEY = "jgold.language";

function readStored(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && LOCALES.some((l) => l.code === stored)) return stored;
  } catch {
    /* storage unavailable; fall through to the browser's own preference */
  }
  try {
    const browser = navigator.language;
    const exact = LOCALES.find((l) => l.code === browser);
    if (exact) return exact.code;
    const base = LOCALES.find((l) => l.code === browser.split("-")[0]);
    if (base) return base.code;
  } catch {
    /* no navigator; fall back below */
  }
  return FALLBACK_LOCALE;
}

interface LanguageValue {
  code: string;
  setCode: (code: string) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
  rtl: boolean;
}

const LanguageContext = createContext<LanguageValue | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [code, setCodeState] = useState<string>(readStored);

  const setCode = useCallback((next: string) => {
    setCodeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* the choice still applies for this session */
    }
  }, []);

  // Direction and lang live on <html> so the browser's own text handling,
  // form controls and scrollbars follow the language too.
  useEffect(() => {
    const locale = getLocale(code);
    document.documentElement.lang = locale.code;
    document.documentElement.dir = locale.direction;
    return () => {
      document.documentElement.dir = "ltr";
    };
  }, [code]);

  const value = useMemo<LanguageValue>(
    () => ({
      code,
      setCode,
      t: (key, vars) => translate(code, key, vars),
      rtl: isRTL(code),
    }),
    [code, setCode],
  );

  return (
    <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
  );
}

export function useLanguage(): LanguageValue {
  const ctx = useContext(LanguageContext);
  if (ctx) return ctx;
  // A component rendered outside the provider still needs to render text
  // rather than crash, so it gets the fallback locale.
  return {
    code: FALLBACK_LOCALE,
    setCode: () => {},
    t: (key, vars) => translate(FALLBACK_LOCALE, key, vars),
    rtl: false,
  };
}
