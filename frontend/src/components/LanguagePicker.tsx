import { useState } from "react";
import { LOCALES, PLANNED_LOCALES, coverage } from "../i18n";
import { useLanguage } from "../i18n/useLanguage";

/**
 * Language selector (section 46).
 *
 * Each language shows how complete it actually is, measured from the
 * locale files rather than from a hand-kept label. A partly translated
 * language says so; a planned one is listed but cannot be chosen, because
 * an English interface wearing an Urdu label helps nobody.
 */
export function LanguagePicker() {
  const { code, setCode, t } = useLanguage();
  const [open, setOpen] = useState(false);
  const active = LOCALES.find((l) => l.code === code);

  return (
    <div className="jg-lang">
      <button
        type="button"
        className="btn sm"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        title={t("language.title")}
      >
        {active?.nativeName ?? "English (UK)"}
      </button>

      {open && (
        <div className="jg-lang-panel" role="listbox"
             aria-label={t("language.title")}>
          {LOCALES.map((locale) => {
            const stats = coverage(locale.code);
            return (
              <button
                key={locale.code}
                type="button"
                role="option"
                aria-selected={locale.code === code}
                className={locale.code === code
                  ? "jg-lang-option current" : "jg-lang-option"}
                onClick={() => {
                  setCode(locale.code);
                  setOpen(false);
                }}
              >
                <span className="jg-lang-native" dir={locale.direction}>
                  {locale.nativeName}
                </span>
                <span className="jg-lang-english">{locale.englishName}</span>
                <span className={`jg-symbol-status ${stats.status.toLowerCase()}`}>
                  {stats.status === "COMPLETE"
                    ? t("language.complete")
                    : `${t("language.beta")} ${stats.percent}%`}
                </span>
              </button>
            );
          })}

          <div className="jg-lang-planned">
            <span className="jg-ind-heading">{t("language.comingSoon")}</span>
            <p className="jg-lang-note">{t("language.plannedNote")}</p>
            <div className="jg-lang-planned-list">
              {PLANNED_LOCALES.map((locale) => (
                <span key={locale.code} className="jg-lang-chip"
                      dir={locale.direction}>
                  {locale.nativeName}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
