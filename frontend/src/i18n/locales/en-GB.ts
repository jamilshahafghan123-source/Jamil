/**
 * English (UK) — the reference locale.
 *
 * Every other locale is measured against this file, so a key added here
 * immediately shows up as untranslated elsewhere rather than silently
 * disappearing. Keys are namespaced by area, not by screen, so moving a
 * control between screens does not orphan its string.
 *
 * Market terminology (XAUUSD, RSI, MACD, ATR, ADX, BOS, CHoCH, FVG) is
 * deliberately NOT translated anywhere: traders read these as symbols,
 * and localising them makes a chart harder to read, not easier.
 */

export const en_GB: Record<string, string> = {
  // -- brand and chrome
  "brand.name": "J Gold AI",
  "nav.signIn": "Sign in",
  "nav.signOut": "Sign out",
  "nav.createAccount": "Create account",
  "nav.back": "Back",
  "nav.close": "Close",
  "nav.cancel": "Cancel",
  "nav.confirm": "Confirm",
  "nav.language": "Language",

  // -- workspace chrome
  "workspace.searchMarkets": "Search markets",
  "workspace.indicators": "Indicators",
  "workspace.sessions": "Sessions",
  "workspace.previousLevels": "Prev levels",
  "workspace.brokers": "Brokers",
  "workspace.resetDemo": "Reset demo",
  "workspace.aiOverlaysOn": "AI overlays on",
  "workspace.aiOverlaysOff": "AI overlays off",
  "workspace.clearAI": "Clear AI",

  // -- account metrics
  "account.balance": "Balance",
  "account.equity": "Equity",
  "account.freeMargin": "Free margin",
  "account.floatingPnl": "Floating P/L",
  "account.realisedPnl": "Realised P/L",
  "account.market": "Market",
  "account.spread": "spread",
  "account.sessionsOpen": "Sessions open",
  "account.virtualMoney": "VIRTUAL MONEY",
  "account.demoName": "J Gold AI demo",

  // -- order ticket
  "ticket.title": "Order ticket",
  "ticket.buy": "BUY",
  "ticket.sell": "SELL",
  "ticket.volume": "Volume",
  "ticket.stopLoss": "Stop loss",
  "ticket.takeProfit": "Take profit",
  "ticket.entry": "Entry",
  "ticket.risk": "Risk",
  "ticket.riskReward": "R:R",
  "ticket.optional": "optional",
  "ticket.place": "Place {side} order",
  "ticket.confirmTitle": "Confirm order",
  "ticket.unavailable": "Trading unavailable",

  // -- AI
  "ai.title": "J Gold AI analysis",
  "ai.run": "Run analysis",
  "ai.useSetup": "Use AI setup",
  "ai.confidence": "Confidence",
  "ai.requiredConfidence": "Required confidence",
  "ai.riskReward": "Risk / reward",
  "ai.requiredRR": "Required R:R",
  "ai.decision": "Decision",
  "ai.noTrade": "NO TRADE",
  "ai.intro":
    "Run an analysis to see the current read, the gates it must clear, and why it would or would not trade.",

  // -- bottom panel
  "tabs.positions": "Open positions",
  "tabs.history": "Trade history",
  "tabs.aiHistory": "AI history",
  "table.symbol": "Symbol",
  "table.side": "Side",
  "table.source": "Source",
  "table.volume": "Volume",
  "table.entry": "Entry",
  "table.stopLoss": "SL",
  "table.takeProfit": "TP",
  "table.floating": "Floating",
  "table.close": "Close",
  "table.openTime": "Open time",
  "table.exit": "Exit",
  "table.profit": "P/L",
  "table.reason": "Reason",

  // -- technicals
  "tech.title": "Technicals",
  "tech.oscillators": "Oscillators",
  "tech.movingAverages": "Moving averages",
  "tech.summary": "Summary",
  "tech.strongBuy": "Strong buy",
  "tech.buy": "Buy",
  "tech.neutral": "Neutral",
  "tech.sell": "Sell",
  "tech.strongSell": "Strong sell",

  // -- market status
  "status.live": "Live",
  "status.chartOnly": "Chart only",
  "status.comingSoon": "Coming soon",
  "status.unsupported": "Unsupported",
  "status.unavailable": "Unavailable",
  "status.connected": "Connected",
  "status.available": "Available",

  // -- errors
  "error.marketData": "Market data is unavailable right now.",
  "error.unreachable":
    "Cannot reach the J Gold AI server. Check your connection and try again.",
  "error.orderRejected": "Order rejected",
  "error.demoUnavailable": "Demo account unavailable",
  "error.safeMode": "Safe Mode is active — new positions are blocked.",
  "error.maintenance":
    "Maintenance Mode is active — new positions are blocked. Closing remains available.",
  "error.sessionExpired": "Session expired — please sign in again",

  // -- honesty notices
  "notice.noPrice":
    "Only markets with a live J Gold AI feed show a price. Everything else shows its status — no figure is estimated or invented.",
  "notice.notAdvice":
    "This describes what the indicators say now — it is not a forecast and not advice.",
  "notice.brokerDisclaimer":
    "Listing a broker is not endorsement, partnership or a claim of support. J Gold AI never custodies your trading money and never asks for a broker password.",

  // -- language selector
  "language.title": "Language",
  "language.complete": "Complete",
  "language.beta": "Beta",
  "language.comingSoon": "Coming soon",
  "language.betaNote":
    "Partly translated. Anything not yet translated is shown in English (UK).",
  "language.plannedNote":
    "Planned. Not yet translated, so it cannot be selected — an English interface under another language's name would help nobody.",
};
