import { useEffect, useRef, useState } from "react";
import type { ChartCoordinates } from "./TradingChart";
import type { SessionRange } from "../lib/types";

/**
 * J Gold AI Session Map (section 8).
 *
 * lightweight-charts has no time-range rectangle, so the session boxes are
 * drawn on their own SVG layer through the same coordinate bridge the
 * drawing tools use. It sits BENEATH the drawing layer and ignores pointer
 * events entirely: a session box is context, never something the user has
 * to click past to reach their own work.
 *
 * The boxes are deliberately quieter than customer drawings — a low-opacity
 * fill and a thin top/bottom rule — so the two never read as the same kind
 * of object.
 */
export function SessionLayer({
  coords,
  ranges,
  showFill,
  showHighLow,
}: {
  coords: ChartCoordinates | null;
  ranges: SessionRange[];
  showFill: boolean;
  showHighLow: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [, repaint] = useState(0);

  // Every pan, zoom and resize moves the boxes, so the layer repaints on
  // the chart's own signal rather than polling.
  useEffect(() => {
    if (!coords) return;
    return coords.subscribe(() => repaint((n) => n + 1));
  }, [coords]);

  if (!coords || ranges.length === 0) return null;

  const height = host.current?.clientHeight ?? 0;

  return (
    <div ref={host} className="jg-session-layer" aria-hidden="true">
      <svg width="100%" height="100%">
        {ranges.map((range) => {
          const x1 = coords.timeToX(range.start);
          const x2 = coords.timeToX(range.end);
          const yHigh = coords.priceToY(range.high);
          const yLow = coords.priceToY(range.low);
          // A session scrolled out of view returns null coordinates; there
          // is nothing sensible to clamp it to, so it is simply not drawn.
          if (x1 == null || x2 == null || yHigh == null || yLow == null) {
            return null;
          }
          const left = Math.min(x1, x2);
          const width = Math.max(Math.abs(x2 - x1), 1);
          const top = Math.min(yHigh, yLow);
          const boxHeight = Math.max(Math.abs(yLow - yHigh), 1);
          const key = `${range.session}-${range.date}`;

          return (
            <g key={key}>
              {showFill && (
                <rect
                  x={left}
                  y={top}
                  width={width}
                  height={boxHeight}
                  fill={range.colour}
                  fillOpacity={range.complete ? 0.07 : 0.12}
                  stroke={range.colour}
                  strokeOpacity={0.35}
                  strokeWidth={1}
                />
              )}
              {showHighLow && (
                <>
                  <line
                    x1={left} y1={top} x2={left + width} y2={top}
                    stroke={range.colour} strokeOpacity={0.75} strokeWidth={1}
                  />
                  <line
                    x1={left} y1={top + boxHeight}
                    x2={left + width} y2={top + boxHeight}
                    stroke={range.colour} strokeOpacity={0.75} strokeWidth={1}
                  />
                </>
              )}
              {width > 46 && (
                <text
                  x={left + 4}
                  y={Math.max(top - 4, 10)}
                  fill={range.colour}
                  fontSize={10}
                  opacity={0.9}
                >
                  {range.display_name}
                  {!range.complete && " (live)"}
                </text>
              )}
            </g>
          );
        })}
        {height > 0 && null}
      </svg>
    </div>
  );
}
