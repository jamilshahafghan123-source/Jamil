/** Display formatting shared by the client components. */

export function money(value: number | null | undefined, currency = "USD"): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function number(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

export function price(value: number | null | undefined, digits = 5): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "—";
  return value.toFixed(digits);
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function timeAgo(timestamp: number | null): string {
  if (!timestamp) return "never";
  const seconds = Math.round((Date.now() - timestamp) / 1000);
  if (seconds < 2) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toISOString().slice(0, 16).replace("T", " ");
}
