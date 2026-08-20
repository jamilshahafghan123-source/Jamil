import { useEffect, useState } from "react";
import type { ChartCoordinates } from "./TradingChart";

/**
 * AI structural overlay layer.
 *
 * SEPARATE FROM CUSTOMER DRAWINGS BY CONSTRUCTION. This layer renders only
 * what the deterministic engine measured and the analysis returned; it holds
 * no user state, has no pointer handlers, and cannot be selected, moved or
 * deleted. "Clear AI overlays" empties the props that feed it and touches
 * nothing the customer owns — the two systems share a coordinate bridge and
 * nothing else.
 *
 * VISUALLY DISTINCT ON PURPOSE: hatched translucent fills, dashed borders
 * and an "AI" tag on every label, against the customer layer's solid blue
 * strokes. A glance should be enough to tell whose line it is.
 *
 * NOTHING HERE IS INVENTED. A zone appears because the backend found a real
 * unmitigated imbalance or order block in the bars. When the engine finds
 * nothing, this layer draws nothing rather than filling the chart.
 */

export interface AIZone {
  kind: "fvg" | "order_block" | "liquidity";
  /** Absent on liquidity zones, which are price bands with no start bar. */
  side?: "bullish" | "bearish" | "demand" | "supply";
  low: number;
  high: number;
  from_time?: string;
  label: string;
}

export interface AISwing {
  side: "high" | "low";
  price: number;
  time: string;
}

/** Structure events: a break of structure or change of character. */
export interface AIStructureMark {
  kind: "BOS" | "CHOCH";
  price: number;
  label: string;
}

const ZONE_STYLE: Record<string, { stroke: string; fill: string }> = {
  bullish: { stroke: "#3fb950", fill: "rgba(63, 185, 80, 0.13)" },
  demand: { stroke: "#3fb950", fill: "rgba(63, 185, 80, 0.13)" },
  bearish: { stroke: "#f4564a", fill: "rgba(244, 86, 74, 0.13)" },
  supply: { stroke: "#f4564a", fill: "rgba(244, 86, 74, 0.13)" },
  liquidity: { stroke: "#b071e0", fill: "rgba(176, 113, 224, 0.13)" },
};

function styleFor(zone: AIZone) {
  if (zone.kind === "liquidity") return ZONE_STYLE.liquidity;
  return ZONE_STYLE[zone.side ?? "liquidity"] ?? ZONE_STYLE.liquidity;
}

/**
 * Liquidity zones arrive labelled with the engine's own key
 * ("equal_highs"), which is right for the payload and wrong on a chart.
 * Everything else already carries a human label and passes through.
 */
const LABELS: Record<string, string> = {
  equal_highs: "Equal highs",
  equal_lows: "Equal lows",
};

function labelFor(zone: AIZone): string {
  return LABELS[zone.label] ?? zone.label;
}

/** Minimum vertical gap, in pixels, between two zone captions. */
const LABEL_SPACING = 12;

export function AIOverlayLayer({
  coords,
  zones,
  swings,
  structure,
}: {
  coords: ChartCoordinates | null;
  zones: AIZone[];
  swings: AISwing[];
  structure: AIStructureMark[];
}) {
  const [, forceRepaint] = useState(0);

  // The projection changes on every pan, zoom and resize even though the
  // analysis has not, so repaint on the chart's own signal.
  useEffect(() => {
    if (!coords) return;
    return coords.subscribe(() => forceRepaint((n) => n + 1));
  }, [coords]);

  if (!coords) return null;
  if (zones.length === 0 && swings.length === 0 && structure.length === 0) {
    return null;
  }

  // Zones can sit within a point or two of each other, which stacks their
  // labels into an unreadable clump. Labels are claimed top-down: a zone
  // only gets one if nothing already labelled sits within a line's height.
  // The band itself is always drawn — only the caption is rationed.
  const claimed: number[] = [];
  const canLabel = (y: number) => {
    if (claimed.some((taken) => Math.abs(taken - y) < LABEL_SPACING)) return false;
    claimed.push(y);
    return true;
  };

  return (
    <div className="jg-ai-layer" aria-hidden="true">
      <svg width="100%" height="100%">
        <defs>
          {/* Hatching is what separates an AI zone from a customer rectangle
              at a glance, independent of colour. */}
          <pattern id="jg-ai-hatch" width="6" height="6"
                   patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <line x1="0" y1="0" x2="0" y2="6" stroke="currentColor"
                  strokeWidth="1" opacity="0.35" />
          </pattern>
        </defs>

        {zones.map((zone, i) => {
          const top = coords.priceToY(Math.max(zone.low, zone.high));
          const bottom = coords.priceToY(Math.min(zone.low, zone.high));
          if (top == null || bottom == null) return null;
          // A zone with no start bar (liquidity) spans the full width; one
          // with a start bar begins there and runs to the right edge, which
          // is what "still unmitigated" means visually.
          const startX = zone.from_time ? coords.timeToX(zone.from_time) : 0;
          const x = startX ?? 0;
          const style = styleFor(zone);
          const height = Math.max(Math.abs(bottom - top), 1);

          return (
            <g key={`zone-${i}`} color={style.stroke}>
              <rect x={x} y={Math.min(top, bottom)} width="100%" height={height}
                    fill={style.fill} stroke={style.stroke} strokeWidth={1}
                    strokeDasharray="5 3" />
              <rect x={x} y={Math.min(top, bottom)} width="100%" height={height}
                    fill="url(#jg-ai-hatch)" stroke="none" />
              {canLabel(Math.min(top, bottom)) && (
                <text x={x + 6} y={Math.min(top, bottom) - 3} fontSize={9.5}
                      fill={style.stroke}>
                  AI {labelFor(zone)}
                </text>
              )}
            </g>
          );
        })}

        {swings.map((swing, i) => {
          const x = coords.timeToX(swing.time);
          const y = coords.priceToY(swing.price);
          if (x == null || y == null) return null;
          const up = swing.side === "high";
          const dy = up ? -5 : 5;
          return (
            <g key={`swing-${i}`}>
              {/* A small triangle above a swing high, below a swing low. */}
              <polygon
                points={`${x - 4},${y + dy} ${x + 4},${y + dy} ${x},${y + dy * 2}`}
                fill={up ? "#f4564a" : "#3fb950"}
                opacity={0.85}
              />
            </g>
          );
        })}

        {structure.map((mark, i) => {
          const y = coords.priceToY(mark.price);
          if (y == null) return null;
          return (
            <g key={`struct-${i}`}>
              <line x1={0} y1={y} x2="100%" y2={y} stroke="#b071e0"
                    strokeWidth={1.2} strokeDasharray="2 4" />
              {canLabel(y) && (
                <text x={8} y={y - 4} fontSize={9.5} fill="#b071e0">
                  AI {mark.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
