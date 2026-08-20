"""Approved J Gold AI product facts for the support worker.

Section 88. This is the *only* place the support worker may take product
statements from. Two reasons it is a hand-written table rather than a
generated or model-recalled one:

* A support answer that invents a feature is worse than no answer. Every
  entry here describes something that exists in this repository today.
* It makes "the product changed" a diff on this file, so support cannot
  quietly drift out of date without someone seeing it.

Where a topic is not yet built, the entry says so plainly rather than
being omitted — a customer asking about drawing tools deserves "not yet
available" rather than silence or an invented walkthrough.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Article:
    key: str
    title: str
    body: str
    #: Lowercase substrings that route a question here.
    triggers: tuple[str, ...]


#: Ordered: the first match wins, so put specific topics before general ones.
ARTICLES: tuple[Article, ...] = (
    Article(
        key="no_trade",
        title="What NO TRADE means",
        body=(
            "NO TRADE is a real result, not an error. The analysis engine "
            "resolves every read to BUY, SELL or NO TRADE, and NO TRADE is "
            "returned whenever the current structure does not offer a setup "
            "that meets your configured requirements. No setup is "
            "manufactured to look busy."
        ),
        triggers=("no trade", "no_trade", "why no signal", "not taking trades"),
    ),
    Article(
        key="confidence",
        title="Confidence scoring",
        body=(
            "Confidence is a 0-100 score built from named components of the "
            "analysis. A signal is only eligible for execution when its "
            "confidence is at or above the minimum confidence in your risk "
            "settings. Raising the minimum makes the system more selective; "
            "lowering it admits weaker setups."
        ),
        triggers=("confidence", "confident"),
    ),
    Article(
        key="rr",
        title="Risk/reward (RR)",
        body=(
            "RR is reward divided by risk: the distance from entry to take "
            "profit, over the distance from entry to stop loss. An RR of 1.5 "
            "means the target is one and a half times the size of the stop. "
            "Signals below your configured minimum RR are not executed."
        ),
        triggers=("rr", "risk/reward", "risk reward", "risk-to-reward"),
    ),
    Article(
        key="demo",
        title="Demo mode",
        body=(
            "Demo mode trades a simulated balance against real market prices. "
            "It is how entries, stops, targets and risk limits are exercised "
            "without money at stake. Demo is the default, and real trading "
            "stays disabled unless it is explicitly enabled on the server."
        ),
        triggers=("demo mode", "how does demo", "what is demo", "practice account"),
    ),
    Article(
        key="demo_withdraw",
        title="Why demo money cannot be withdrawn",
        body=(
            "Demo balance is virtual. It is a number in the simulator, not "
            "money held anywhere, so there is nothing to withdraw. Only funds "
            "held in a real account at your own broker can be withdrawn, and "
            "that is done through the broker, not through J Gold AI."
        ),
        triggers=("withdraw demo", "demo money", "cash out demo", "withdraw virtual"),
    ),
    Article(
        key="deposit_withdraw",
        title="Deposits and withdrawals",
        body=(
            "J Gold AI never holds your trading funds. Money for trading sits "
            "in your account with your own broker, and deposits and "
            "withdrawals are handled entirely through that broker's own "
            "portal. A J Gold AI subscription is a separate payment for "
            "access to the software and is not a trading balance."
        ),
        triggers=("deposit", "withdraw", "withdrawal", "take my money out"),
    ),
    Article(
        key="subscription",
        title="Subscriptions",
        body=(
            "Plans are Weekly GBP 9.99, Monthly GBP 29.99 and Yearly GBP "
            "249.99. A subscription pays for access to the platform and is "
            "separate from any broker balance and from trading profit or "
            "loss. No payment provider is connected yet, so no plan can "
            "currently be purchased."
        ),
        triggers=("subscription", "subscribe", "plan cost", "how much", "billing",
                  "price"),
    ),
    Article(
        key="broker_connect",
        title="Connecting a broker",
        body=(
            "Trading connects to MetaTrader 5 through a bridge that runs on "
            "the machine hosting your MT5 terminal. Broker credentials are "
            "entered in MT5 itself and never in J Gold AI — the platform "
            "never asks for, stores or transmits your broker password."
        ),
        triggers=("connect broker", "connect my broker", "how do i connect",
                  "link broker", "mt5 setup"),
    ),
    Article(
        key="modes",
        title="Manual, AI Assist and AI Auto",
        body=(
            "Manual means you place trades yourself. AI Assist means the "
            "system analyses and proposes, and you approve each trade. AI "
            "Auto means approved setups are executed automatically, still "
            "subject to every risk limit. Risk checks apply identically in "
            "all three modes."
        ),
        # Deliberately not bare "ai auto": a question about AI Auto being
        # *paused* is a status question and belongs to ai_auto_paused below.
        triggers=("ai assist", "what is ai auto", "how does ai auto",
                  "manual mode", "trading mode", "what are the modes"),
    ),
    Article(
        key="risk_settings",
        title="Risk settings",
        body=(
            "Your risk envelope covers risk per trade, daily loss limit, max "
            "trades per day, max open positions, max lot size, minimum "
            "confidence, minimum RR and maximum spread. The risk engine "
            "checks every one before any order is sent, and nothing — "
            "including the AI — can bypass it."
        ),
        triggers=("risk setting", "risk limit", "daily loss", "lot size",
                  "max spread"),
    ),
    Article(
        key="emergency_stop",
        title="Emergency stop",
        body=(
            "Emergency stop halts trading on your account. While it is "
            "engaged the bot will not open anything, and it must be cleared "
            "explicitly before automated trading resumes."
        ),
        triggers=("emergency stop", "kill switch", "stop everything"),
    ),
    Article(
        key="chart",
        title="The chart",
        body=(
            "The dashboard shows live XAUUSD candles across M1 to D1, drawn "
            "from real broker data. Analysis overlays mark the levels a "
            "signal was built from."
        ),
        triggers=("chart", "candles", "timeframe"),
    ),
    Article(
        key="drawing_tools",
        title="Drawing tools",
        body=(
            "Manual drawing tools are not available yet. The chart currently "
            "renders analysis overlays produced by the engine rather than "
            "shapes you place yourself."
        ),
        triggers=("drawing tool", "draw on chart", "trendline", "draw a line"),
    ),
    Article(
        key="indicators",
        title="Indicators",
        body=(
            "The engine computes moving averages, momentum and volatility "
            "measures internally and shows EMA overlays on the chart. A "
            "configurable indicator panel is not available yet."
        ),
        triggers=("indicator", "ema", "moving average", "rsi"),
    ),
    Article(
        key="login",
        title="Signing in",
        body=(
            "Sign in with the email and password used at registration. "
            "Self-service password reset is not available yet; if you cannot "
            "get in, raise a ticket and it will be escalated."
        ),
        triggers=("log in", "login", "sign in", "password reset", "forgot password",
                  "cannot get in"),
    ),
    Article(
        key="market_data",
        title="Market data",
        body=(
            "Prices come from the connected MT5 terminal. If that connection "
            "drops or prices stop updating, automated trading pauses rather "
            "than acting on stale numbers, and it resumes once data is live "
            "again."
        ),
        triggers=("market data", "prices", "no data", "data unavailable", "stale"),
    ),
    Article(
        key="ai_auto_paused",
        title="Why automated trading pauses",
        body=(
            "Automated trading pauses whenever the platform cannot vouch for "
            "the state a decision would rest on — stale or missing prices, an "
            "unreachable broker connection, or risk checks it cannot verify. "
            "Positions already open are left untouched, and trading resumes "
            "on its own once conditions are trustworthy."
        ),
        triggers=("paused", "why is ai auto", "safe mode", "trading stopped"),
    ),
)

_BY_KEY = {a.key: a for a in ARTICLES}


def find(question: str) -> Article | None:
    """First matching article, or None. Never guesses."""
    text = (question or "").lower()
    for article in ARTICLES:
        if any(trigger in text for trigger in article.triggers):
            return article
    return None


def get(key: str) -> Article | None:
    return _BY_KEY.get(key)
