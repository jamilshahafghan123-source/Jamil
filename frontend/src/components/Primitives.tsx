import type { ReactNode } from "react";

export function Card({
  title,
  actions,
  children,
  flush,
}: {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          {title && <h2 className="card-title">{title}</h2>}
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      <div className={flush ? "card-body flush" : "card-body"}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "up" | "down";
}) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value num ${tone ?? ""}`}>{value}</div>
      {sub != null && <div className="stat-sub num">{sub}</div>}
    </div>
  );
}

export function Badge({
  tone = "neutral",
  live,
  children,
}: {
  tone?: "neutral" | "gold" | "up" | "down" | "warn";
  live?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`badge ${tone}`}>
      {live && <span className="dot live" />}
      {children}
    </span>
  );
}

export function Confidence({ value }: { value: number }) {
  return (
    <span className="conf" title={`${value}% confidence`}>
      <span className="conf-track">
        <span className="conf-fill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </span>
      <span className="num dim" style={{ fontSize: 12 }}>
        {value}%
      </span>
    </span>
  );
}

export function Banner({
  tone = "info",
  children,
}: {
  tone?: "err" | "warn" | "ok" | "info";
  children: ReactNode;
}) {
  return <div className={`banner ${tone}`}>{children}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Spinner() {
  return <span className="spin" aria-hidden />;
}
