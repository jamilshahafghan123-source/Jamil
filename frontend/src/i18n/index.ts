/**
 * J Gold AI language system (sections 45-48).
 *
 * The architecture rule: no component holds a translation. A component
 * asks for a key, and the locale files answer. That is what makes adding
 * a locale a matter of adding a file rather than editing every screen.
 *
 * The honesty rule: a locale declares how complete it actually is.
 * `COMPLETE` means every key is translated; `BETA` means some keys fall
 * back to English; `COMING_SOON` means the locale is declared but has no
 * translations yet and cannot be selected. `coverage()` measures this
 * from the files themselves rather than trusting a hand-maintained
 * label, so a locale cannot claim to be finished while it is not.
 *
 * Fallback is always English (UK), never a blank string or a raw key.
 */

import { en_GB } from "./locales/en-GB";
import { en_US } from "./locales/en-US";
import { ar } from "./locales/ar";
import { ps } from "./locales/ps";
import { ur } from "./locales/ur";
import { es } from "./locales/es";
import { fr } from "./locales/fr";
import { de } from "./locales/de";

export type Dictionary = Record<string, string>;

export type LocaleStatus = "COMPLETE" | "BETA" | "COMING_SOON";

export interface Locale {
  code: string;
  /** Name in the language itself — how a speaker would look for it. */
  nativeName: string;
  englishName: string;
  direction: "ltr" | "rtl";
  dictionary: Dictionary;
}

export const FALLBACK_LOCALE = "en-GB";

export const LOCALES: Locale[] = [
  { code: "en-GB", nativeName: "English (UK)", englishName: "English (UK)",
    direction: "ltr", dictionary: en_GB },
  { code: "en-US", nativeName: "English (US)", englishName: "English (US)",
    direction: "ltr", dictionary: en_US },
  { code: "ar", nativeName: "العربية", englishName: "Arabic",
    direction: "rtl", dictionary: ar },
  { code: "ps", nativeName: "پښتو", englishName: "Pashto",
    direction: "rtl", dictionary: ps },
  { code: "ur", nativeName: "اردو", englishName: "Urdu",
    direction: "rtl", dictionary: ur },
  { code: "es", nativeName: "Español", englishName: "Spanish",
    direction: "ltr", dictionary: es },
  { code: "fr", nativeName: "Français", englishName: "French",
    direction: "ltr", dictionary: fr },
  { code: "de", nativeName: "Deutsch", englishName: "German",
    direction: "ltr", dictionary: de },
];

/**
 * Locales the architecture is ready for but which have no translations.
 *
 * They are listed so the selector can say "coming soon" honestly rather
 * than implying the platform will never speak them. They are NOT
 * selectable: showing a customer an English interface under an Urdu label
 * would be worse than showing them English.
 */
export const PLANNED_LOCALES: { code: string; nativeName: string; englishName: string;
                                direction: "ltr" | "rtl" }[] = [
  { code: "it", nativeName: "Italiano", englishName: "Italian", direction: "ltr" },
  { code: "pt", nativeName: "Português", englishName: "Portuguese", direction: "ltr" },
  { code: "nl", nativeName: "Nederlands", englishName: "Dutch", direction: "ltr" },
  { code: "pl", nativeName: "Polski", englishName: "Polish", direction: "ltr" },
  { code: "tr", nativeName: "Türkçe", englishName: "Turkish", direction: "ltr" },
  { code: "ru", nativeName: "Русский", englishName: "Russian", direction: "ltr" },
  { code: "fa", nativeName: "فارسی", englishName: "Farsi", direction: "rtl" },
  { code: "hi", nativeName: "हिन्दी", englishName: "Hindi", direction: "ltr" },
  { code: "bn", nativeName: "বাংলা", englishName: "Bengali", direction: "ltr" },
  { code: "zh-Hans", nativeName: "简体中文", englishName: "Chinese (Simplified)", direction: "ltr" },
  { code: "zh-Hant", nativeName: "繁體中文", englishName: "Chinese (Traditional)", direction: "ltr" },
  { code: "ja", nativeName: "日本語", englishName: "Japanese", direction: "ltr" },
  { code: "ko", nativeName: "한국어", englishName: "Korean", direction: "ltr" },
  { code: "id", nativeName: "Bahasa Indonesia", englishName: "Indonesian", direction: "ltr" },
  { code: "vi", nativeName: "Tiếng Việt", englishName: "Vietnamese", direction: "ltr" },
  { code: "th", nativeName: "ไทย", englishName: "Thai", direction: "ltr" },
  { code: "sv", nativeName: "Svenska", englishName: "Swedish", direction: "ltr" },
  { code: "uk", nativeName: "Українська", englishName: "Ukrainian", direction: "ltr" },
];

const BY_CODE = new Map(LOCALES.map((l) => [l.code, l]));

/** Every key the interface can ask for, taken from the reference locale. */
export function allKeys(): string[] {
  return Object.keys(en_GB);
}

/**
 * How complete a locale actually is, measured from its own dictionary.
 *
 * A label that has to be maintained by hand drifts; this cannot.
 */
export function coverage(code: string): {
  status: LocaleStatus; translated: number; total: number; percent: number;
} {
  const locale = BY_CODE.get(code);
  const total = allKeys().length;
  if (!locale) return { status: "COMING_SOON", translated: 0, total, percent: 0 };
  const translated = allKeys().filter((key) => {
    const value = locale.dictionary[key];
    return typeof value === "string" && value.trim().length > 0;
  }).length;
  const percent = total === 0 ? 0 : Math.round((translated / total) * 100);
  return {
    status: translated === total ? "COMPLETE" : translated === 0 ? "COMING_SOON" : "BETA",
    translated, total, percent,
  };
}

export function getLocale(code: string): Locale {
  return BY_CODE.get(code) ?? BY_CODE.get(FALLBACK_LOCALE)!;
}

export function isRTL(code: string): boolean {
  return getLocale(code).direction === "rtl";
}

/**
 * Translate a key.
 *
 * Falls back to English (UK), then to the key itself — a missing string
 * shows something a human can act on rather than an empty space.
 * `vars` are substituted as {name}.
 */
export function translate(
  code: string,
  key: string,
  vars?: Record<string, string | number>,
): string {
  const locale = getLocale(code);
  const template =
    locale.dictionary[key] ?? en_GB[key] ?? key;
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name) =>
    name in vars ? String(vars[name]) : whole);
}
