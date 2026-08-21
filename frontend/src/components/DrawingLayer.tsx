import { useCallback, useEffect, useRef, useState } from "react";
import type { ChartCoordinates } from "./TradingChart";

/**
 * Customer drawing layer.
 *
 * COORDINATES ARE PRICE AND TIME, NEVER PIXELS. A drawing stored in pixels
 * would be wrong the moment the window resized or the user zoomed, so every
 * shape persists as {time, price} pairs and is projected through the
 * chart's own scales at paint time.
 *
 * SEPARATE FROM AI OVERLAYS by construction: those are chart series drawn
 * by the library, these are SVG the customer owns. "Clear AI" and "Clear
 * drawings" cannot reach each other's data because they are different
 * systems, not two flags on one list.
 *
 * WHAT THIS SUPPORTS, honestly: place, select, move, delete, lock, hide,
 * undo, redo and clear. A SELECTED, unlocked shape shows a handle on
 * each of its points: dragging one reshapes the shape, leaving the other
 * end anchored, while dragging the body still moves the whole thing.
 * (Previously only whole-shape moves were supported.) Resizing a single
 * handle is *not* implemented — the toolbar does not offer it, rather than
 * offering a handle that does nothing.
 */

export type DrawingKind =
  | "TREND_LINE" | "HORIZONTAL" | "VERTICAL" | "RECTANGLE"
  | "ARROW" | "TEXT" | "RULER" | "LONG_POSITION" | "SHORT_POSITION"
  | "FIB";

export interface Point {
  time: string;
  price: number;
}

export interface Drawing {
  id: number | string;
  kind: DrawingKind;
  points: Point[];
  text?: string;
  locked: boolean;
  hidden: boolean;
}

export const TOOLS: { kind: DrawingKind | "CURSOR"; label: string; hint: string }[] = [
  { kind: "CURSOR", label: "↖", hint: "Select and move" },
  { kind: "TREND_LINE", label: "／", hint: "Trend line" },
  { kind: "HORIZONTAL", label: "—", hint: "Horizontal line" },
  { kind: "VERTICAL", label: "│", hint: "Vertical line" },
  { kind: "RECTANGLE", label: "▭", hint: "Rectangle / zone" },
  { kind: "ARROW", label: "↗", hint: "Arrow" },
  { kind: "TEXT", label: "T", hint: "Text note" },
  { kind: "RULER", label: "↕", hint: "Measure" },
  { kind: "LONG_POSITION", label: "▲", hint: "Long position" },
  { kind: "SHORT_POSITION", label: "▼", hint: "Short position" },
  { kind: "FIB", label: "%", hint: "Fibonacci retracement" },
];

/**
 * Retracement ratios, drawn between the two clicked swing points. 0 sits on
 * the first click and 1 on the second, so dragging low→high measures a
 * pullback in an uptrend and high→low one in a downtrend.
 */
const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

/** Shapes needing two clicks; the rest are placed with one. */
const TWO_POINT: DrawingKind[] = [
  "TREND_LINE", "RECTANGLE", "ARROW", "RULER", "LONG_POSITION", "SHORT_POSITION",
  "FIB",
];

const COLOUR = "#8ab4f8";
const SELECTED = "#d9a441";

export function DrawingLayer({
  coords,
  tool,
  drawings,
  selectedId,
  onSelect,
  onCreate,
  onMove,
}: {
  coords: ChartCoordinates | null;
  tool: DrawingKind | "CURSOR";
  drawings: Drawing[];
  selectedId: number | string | null;
  onSelect: (id: number | string | null) => void;
  onCreate: (kind: DrawingKind, points: Point[], text?: string) => void;
  onMove: (id: number | string, points: Point[]) => void;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  const [pending, setPending] = useState<Point[]>([]);
  const [, forceRepaint] = useState(0);
  // `pointIndex` distinguishes reshaping from moving: with it set the
  // drag moves ONE endpoint, without it the whole shape travels.
  // Set on mousedown over a shape or handle, and consumed by the click
  // that follows, so a shape-click never reaches the deselect path.
  const justInteracted = useRef(false);
  const drag = useRef<
    { id: number | string; from: Point; pointIndex?: number } | null
  >(null);

  // Repaint on every pan, zoom and resize — the projection changes even
  // though the data has not.
  useEffect(() => {
    if (!coords) return;
    return coords.subscribe(() => forceRepaint((n) => n + 1));
  }, [coords]);

  const pointAt = useCallback(
    (clientX: number, clientY: number): Point | null => {
      if (!coords || !host.current) return null;
      const box = host.current.getBoundingClientRect();
      const time = coords.xToTime(clientX - box.left);
      const price = coords.yToPrice(clientY - box.top);
      if (time == null || price == null) return null;
      return { time, price };
    },
    [coords],
  );

  const toPoint = useCallback(
    (event: React.MouseEvent): Point | null =>
      pointAt(event.clientX, event.clientY),
    [pointAt],
  );

  function handleClick(event: React.MouseEvent) {
    if (tool === "CURSOR") {
      // A click that started ON a shape has already selected it via
      // startDrag's mousedown. The click event still bubbles up to this
      // container afterwards, and clearing the selection here would undo
      // the selection the user just made — which is why selecting a shape
      // appeared not to work at all. Only a click on empty chart clears.
      if (justInteracted.current) {
        justInteracted.current = false;
        return;
      }
      onSelect(null);
      return;
    }
    const point = toPoint(event);
    if (!point) return;

    if (TWO_POINT.includes(tool)) {
      if (pending.length === 0) {
        setPending([point]);
      } else {
        onCreate(tool, [pending[0], point]);
        setPending([]);
      }
      return;
    }

    if (tool === "TEXT") {
      const text = window.prompt("Note text");
      if (text && text.trim()) onCreate(tool, [point], text.trim().slice(0, 200));
      return;
    }
    onCreate(tool, [point]);
  }

  function project(p: Point): { x: number; y: number } | null {
    if (!coords) return null;
    const x = coords.timeToX(p.time);
    const y = coords.priceToY(p.price);
    if (x == null || y == null) return null;
    return { x, y };
  }

  function startDrag(event: React.MouseEvent, drawing: Drawing) {
    if (tool !== "CURSOR" || drawing.locked) return;
    event.stopPropagation();
    justInteracted.current = true;
    onSelect(drawing.id);
    const point = toPoint(event);
    if (point) drag.current = { id: drawing.id, from: point };
  }

  /** Grab one endpoint. Reshapes rather than moves. */
  function startHandleDrag(
    event: React.MouseEvent, drawing: Drawing, pointIndex: number,
  ) {
    if (tool !== "CURSOR" || drawing.locked) return;
    event.stopPropagation();
    justInteracted.current = true;
    onSelect(drawing.id);
    const point = toPoint(event);
    if (point) drag.current = { id: drawing.id, from: point, pointIndex };
  }

  const finishDrag = useCallback((clientX: number, clientY: number) => {
    const active = drag.current;
    drag.current = null;
    if (!active) return;
    const to = pointAt(clientX, clientY);
    if (!to) return;
    const drawing = drawings.find((d) => d.id === active.id);
    if (!drawing || drawing.locked) return;

    // Reshaping: only the grabbed endpoint takes the new position, so the
    // opposite end stays anchored exactly where the user left it.
    if (active.pointIndex != null) {
      const index = active.pointIndex;
      if (index < 0 || index >= drawing.points.length) return;
      onMove(
        drawing.id,
        drawing.points.map((p, i) => (i === index ? to : p)),
      );
      return;
    }

    // Moving: shift by the delta in *data* space, so a drag means the same
    // thing at any zoom level.
    const dPrice = to.price - active.from.price;
    const dMs = Date.parse(to.time) - Date.parse(active.from.time);
    if (dPrice === 0 && dMs === 0) return;
    onMove(
      drawing.id,
      drawing.points.map((p) => ({
        price: p.price + dPrice,
        time: new Date(Date.parse(p.time) + dMs).toISOString(),
      })),
    );
  }, [pointAt, drawings, onMove]);

  /**
   * Finish drags on the window.
   *
   * With the cursor tool this layer sets pointer-events:none so the chart
   * underneath stays interactive, which means its own mouseup never
   * fires. Listening on the window is what makes a drag that ends
   * anywhere — including outside the chart — still land.
   */
  useEffect(() => {
    const onUp = (event: MouseEvent) => {
      if (drag.current) finishDrag(event.clientX, event.clientY);
    };
    window.addEventListener("mouseup", onUp);
    return () => window.removeEventListener("mouseup", onUp);
  }, [finishDrag]);

  const width = host.current?.clientWidth ?? 0;
  const height = host.current?.clientHeight ?? 0;

  return (
    <div
      ref={host}
      className={`jg-draw-layer ${tool === "CURSOR" ? "cursor" : "drawing"}`}
      onClick={handleClick}
    >
      <svg width="100%" height="100%">
        {drawings.map((drawing) => {
          if (drawing.hidden) return null;
          const points = drawing.points.map(project);
          if (points.some((p) => p == null)) return null;
          const pts = points as { x: number; y: number }[];
          const stroke = drawing.id === selectedId ? SELECTED : COLOUR;
          const common = {
            stroke,
            strokeWidth: drawing.id === selectedId ? 2 : 1.4,
            fill: "none",
            onMouseDown: (e: React.MouseEvent) => startDrag(e, drawing),
            style: { cursor: tool === "CURSOR" && !drawing.locked
              ? "move" : "default" } as React.CSSProperties,
          };

          switch (drawing.kind) {
            case "HORIZONTAL":
              return <line key={drawing.id} x1={0} y1={pts[0].y} x2={width}
                           y2={pts[0].y} {...common} />;
            case "VERTICAL":
              return <line key={drawing.id} x1={pts[0].x} y1={0} x2={pts[0].x}
                           y2={height} {...common} />;
            case "TREND_LINE":
            case "ARROW":
            case "RULER":
              return (
                <g key={drawing.id}>
                  <line x1={pts[0].x} y1={pts[0].y} x2={pts[1].x} y2={pts[1].y}
                        {...common}
                        strokeDasharray={drawing.kind === "RULER" ? "4 3" : undefined} />
                  {drawing.kind === "ARROW" && (
                    <circle cx={pts[1].x} cy={pts[1].y} r={3.5} fill={stroke} />
                  )}
                  {drawing.kind === "RULER" && (
                    <text x={(pts[0].x + pts[1].x) / 2} y={(pts[0].y + pts[1].y) / 2 - 6}
                          fill={stroke} fontSize={10} textAnchor="middle">
                      {(drawing.points[1].price - drawing.points[0].price).toFixed(2)}
                    </text>
                  )}
                </g>
              );
            case "RECTANGLE":
              return (
                <rect key={drawing.id}
                      x={Math.min(pts[0].x, pts[1].x)} y={Math.min(pts[0].y, pts[1].y)}
                      width={Math.abs(pts[1].x - pts[0].x)}
                      height={Math.abs(pts[1].y - pts[0].y)}
                      {...common} fill="rgba(138, 180, 248, 0.10)" />
              );
            case "LONG_POSITION":
            case "SHORT_POSITION": {
              const isLong = drawing.kind === "LONG_POSITION";
              const top = Math.min(pts[0].y, pts[1].y);
              const bottom = Math.max(pts[0].y, pts[1].y);
              const x = Math.min(pts[0].x, pts[1].x);
              const w = Math.abs(pts[1].x - pts[0].x) || 60;
              // Target half green, risk half red, oriented by direction.
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}>
                  <rect x={x} y={top} width={w} height={(bottom - top) / 2}
                        fill={isLong ? "rgba(63,185,80,0.16)" : "rgba(244,86,74,0.16)"}
                        stroke={stroke} strokeWidth={1} />
                  <rect x={x} y={top + (bottom - top) / 2} width={w}
                        height={(bottom - top) / 2}
                        fill={isLong ? "rgba(244,86,74,0.16)" : "rgba(63,185,80,0.16)"}
                        stroke={stroke} strokeWidth={1} />
                </g>
              );
            }
            case "FIB": {
              const [a, b] = drawing.points;
              const left = Math.min(pts[0].x, pts[1].x);
              const right = Math.max(pts[0].x, pts[1].x);
              const span = b.price - a.price;
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}
                   style={{ cursor: tool === "CURSOR" && !drawing.locked
                     ? "move" : "default" }}>
                  {FIB_RATIOS.map((ratio) => {
                    const price = a.price + span * ratio;
                    const y = coords?.priceToY(price);
                    if (y == null) return null;
                    // 0.5 is not a Fibonacci ratio but is the level traders
                    // actually watch, so it is drawn and labelled like one.
                    return (
                      <g key={ratio}>
                        <line x1={left} y1={y} x2={right} y2={y} stroke={stroke}
                              strokeWidth={ratio === 0 || ratio === 1 ? 1.4 : 1}
                              strokeDasharray={ratio === 0 || ratio === 1
                                ? undefined : "4 3"} />
                        <text x={right + 4} y={y + 3} fill={stroke} fontSize={9.5}>
                          {ratio.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")}
                          {"  "}
                          {price.toFixed(2)}
                        </text>
                      </g>
                    );
                  })}
                </g>
              );
            }
            case "TEXT":
              return (
                <text key={drawing.id} x={pts[0].x} y={pts[0].y} fill={stroke}
                      fontSize={11} onMouseDown={(e) => startDrag(e, drawing)}
                      style={{ cursor: "move" }}>
                  {drawing.text ?? ""}
                </text>
              );
            default:
              return null;
          }
        })}

        {/* Endpoint handles on the selected shape. Only a selected,
            unlocked shape gets them, so they never clutter the chart and
            never suggest an edit that would be refused. */}
        {(() => {
          if (tool !== "CURSOR" || selectedId == null) return null;
          const drawing = drawings.find((d) => d.id === selectedId);
          if (!drawing || drawing.locked || drawing.hidden) return null;
          return drawing.points.map((point, index) => {
            const projected = project(point);
            if (!projected) return null;
            return (
              <circle
                key={`handle-${index}`}
                cx={projected.x}
                cy={projected.y}
                r={5}
                fill="#0f1115"
                stroke={SELECTED}
                strokeWidth={2}
                className="jg-draw-handle"
                onMouseDown={(e) => startHandleDrag(e, drawing, index)}
              />
            );
          });
        })()}

        {/* First click of a two-point shape, so the user can see it landed. */}
        {pending.map((p, i) => {
          const projected = project(p);
          return projected ? (
            <circle key={i} cx={projected.x} cy={projected.y} r={3}
                    fill={SELECTED} />
          ) : null;
        })}
      </svg>
    </div>
  );
}
