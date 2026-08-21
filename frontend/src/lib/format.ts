/**
 * Shared display formatting.
 *
 * Money was formatted in two places with two different rules — one put the
 * minus sign before the currency, the other after it — so the same loss
 * read differently depending on which panel you were looking at. One
 * function means one answer.
 */

/**
 * A money amount, or an em dash when there is no number to show.
 *
 * A missing figure is never rendered as 0.00. Zero is a real balance and a
 * real P/L; "we do not have this value" is not, and showing one as the
 * other is how a trading screen starts lying about money.
 */
export function money(
  value: number | null | undefined,
  currency = "USD",
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value < 0 ? "-" : "";
  return `${sign}${currency} ${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
