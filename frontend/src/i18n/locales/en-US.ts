/**
 * English (US).
 *
 * Only the strings that genuinely differ from English (UK) are listed;
 * everything else falls through to the reference locale by design rather
 * than being duplicated, so a change to shared wording cannot leave the
 * two English variants disagreeing.
 */

import { en_GB } from "./en-GB";

export const en_US: Record<string, string> = {
  ...en_GB,
  "account.realisedPnl": "Realized P/L",
  "notice.notAdvice":
    "This describes what the indicators say now — it is not a forecast and not advice.",
  "language.betaNote":
    "Partly translated. Anything not yet translated is shown in English (UK).",
};
