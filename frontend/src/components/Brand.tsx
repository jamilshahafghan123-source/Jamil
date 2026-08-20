import { useState } from "react";

/**
 * J Gold AI brand lockup — the single place the product identity is defined.
 *
 * THE ARTWORK
 * -----------
 * `frontend/public/j-gold-ai-logo.png` is the master: a square 1254x1254
 * lockup on an opaque near-black ground (RGB, no alpha channel) — a circular
 * gold "J" emblem on top, then the "GOLD AI" wordmark and two straplines.
 * It stays in the repo but no page loads it; at 1.7 MB it is far too heavy
 * to ship for something drawn at 22-240px.
 *
 * Pages load two derivatives cut from it instead, each already cropped to
 * the region its variant needs (the crop windows were measured off the
 * master's pixels — emblem gold bbox x 0.2153-0.8078, y 0.1260-0.6683):
 *
 *   "mark" — j-gold-ai-mark.png, 256x256, just the emblem. Used at every
 *     small placement (top bars, auth cards, dashboard header). At 22-40px
 *     the wordmark and straplines are illegible, so shrinking the whole
 *     lockup would only produce a gold smudge; the mark stays sharp and the
 *     name is set in text beside it.
 *
 *   "full" — j-gold-ai-lockup.png, 437x512, the whole lockup with its black
 *     outer margin trimmed, for the home hero. Framed as a deliberate plate:
 *     screen blending was tried first to drop the black ground out, but the
 *     ground is textured charcoal rather than true black, so it lightened
 *     into a visible square instead of disappearing.
 *
 * If either PNG fails to load, a vector emblem is drawn instead and the name
 * is always shown, so no page is left unbranded.
 */

export const BRAND = {
  name: "J Gold AI",
  title: "J Gold AI — Smart XAUUSD Trading",
} as const;

/** Full-resolution master. Kept as the source asset; not loaded by any page. */
export const LOGO_MASTER_SRC = "/j-gold-ai-logo.png";

/** What pages actually load, keyed by variant. */
export const LOGO_SRC = {
  mark: "/j-gold-ai-mark.png",
  full: "/j-gold-ai-lockup.png",
} as const;

/** Intrinsic aspect (width / height) of each derivative. */
const ASPECT = { mark: 1, full: 437 / 512 } as const;

function VectorEmblem({ size }: { size: number }) {
  const id = "jg-grad";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label={`${BRAND.name} emblem`}
      className="brand-emblem"
    >
      <defs>
        <linearGradient id={id} x1="8" y1="56" x2="56" y2="8">
          <stop offset="0%" stopColor="var(--gold-dim)" />
          <stop offset="50%" stopColor="var(--gold)" />
          <stop offset="100%" stopColor="#f6e0ad" />
        </linearGradient>
      </defs>
      {/* ring */}
      <circle cx="32" cy="32" r="28" fill="none" stroke={`url(#${id})`} strokeWidth="2.4" />
      {/* stylised J */}
      <path
        d="M38 16 v22 a9 9 0 0 1 -18 0"
        fill="none"
        stroke={`url(#${id})`}
        strokeWidth="5"
        strokeLinecap="round"
      />
      <path d="M30 16 h16" stroke={`url(#${id})`} strokeWidth="5" strokeLinecap="round" />
      {/* rising market line */}
      <path
        d="M20 46 L28 38 L34 42 L46 26"
        fill="none"
        stroke={`url(#${id})`}
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />
      <circle cx="46" cy="26" r="2.8" fill={`url(#${id})`} />
    </svg>
  );
}

interface BrandProps {
  /** Rendered size of the emblem in px. */
  size?: number;
  /**
   * Show the wordmark next to the emblem. Forced on when the PNG fails to
   * load, so a page is never left unbranded.
   */
  showName?: boolean;
  /** "mark" crops to the emblem; "full" shows the entire lockup. */
  variant?: "mark" | "full";
  className?: string;
}

export function Brand({
  size = 32,
  showName = true,
  variant = "mark",
  className,
}: BrandProps) {
  const [pngFailed, setPngFailed] = useState(false);
  const withName = pngFailed || showName;

  // `size` is the height; width follows the derivative's own aspect so
  // neither variant is ever squashed.
  return (
    <span className={className ? `brand-lockup ${className}` : "brand-lockup"}>
      {pngFailed ? (
        <VectorEmblem size={size} />
      ) : (
        <img
          src={LOGO_SRC[variant]}
          alt={`${BRAND.name} logo`}
          className={`brand-emblem brand-emblem-${variant}`}
          style={{ width: ASPECT[variant] * size, height: size }}
          onError={() => setPngFailed(true)}
          decoding="async"
        />
      )}
      {withName && <span className="brand-name">{BRAND.name}</span>}
    </span>
  );
}
