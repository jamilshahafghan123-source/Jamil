import type { ReactNode } from "react";

/**
 * Right icon rail and panel host.
 *
 * The rule the whole layout depends on: a panel occupies space only while
 * it is open, and closing it gives the space straight back to the chart.
 * Nothing here reserves a column "just in case" — the grid column simply
 * does not exist when no panel is open.
 *
 * One major panel at a time, deliberately. Two open panels halve the
 * chart, and the chart is the product.
 */

export type PanelId =
  | "watchlist" | "news" | "alerts" | "calendar" | "data" | "chat"
  | "screener" | "sentiment" | "products" | "help" | "objects"
  | "ai" | "technicals" | "strategies" | "brokers" | "account" | "bot"
  | "trade";

export interface RailItem {
  id: PanelId;
  label: string;
  /** Simple geometric glyph — original, not a licensed icon set. */
  glyph: ReactNode;
  /** Small count badge, e.g. unacknowledged alerts. */
  badge?: number;
}

export function RightRail({
  items, active, onToggle,
}: {
  items: RailItem[];
  active: PanelId | null;
  onToggle: (id: PanelId) => void;
}) {
  return (
    <nav className="jg-rail" aria-label="Workspace panels">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className={active === item.id ? "jg-rail-btn active" : "jg-rail-btn"}
          onClick={() => onToggle(item.id)}
          title={item.label}
          aria-label={item.label}
          aria-pressed={active === item.id}
        >
          <span className="jg-rail-glyph" aria-hidden="true">{item.glyph}</span>
          {item.badge != null && item.badge > 0 && (
            <span className="jg-rail-badge">{item.badge > 99 ? "99+" : item.badge}</span>
          )}
        </button>
      ))}
    </nav>
  );
}

export function RailPanel({
  title, onClose, children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <aside className="jg-panel" aria-label={title}>
      <header className="jg-panel-head">
        <h3>{title}</h3>
        <div className="jg-spacer" />
        <button type="button" className="jg-panel-close" onClick={onClose}
                title="Close panel — the chart takes the space back"
                aria-label={`Close ${title}`}>
          ×
        </button>
      </header>
      <div className="jg-panel-body">{children}</div>
    </aside>
  );
}

/**
 * What a panel shows when its data source is not connected.
 *
 * Section 64: never fake news, sentiment or a calendar. A panel that has
 * no provider says exactly that, rather than showing plausible-looking
 * sample content a customer might act on.
 */
export function NotConfigured({ what, detail }: { what: string; detail: string }) {
  return (
    <div className="jg-not-configured">
      <p className="jg-not-configured-title">{what} — NOT CONFIGURED</p>
      <p className="jg-not-configured-detail">{detail}</p>
    </div>
  );
}
