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
  | "FIB"
  // Lines that continue past their second point.
  | "RAY" | "EXTENDED_LINE" | "HORIZONTAL_RAY" | "CHANNEL"
  // Fibonacci family beyond the plain retracement.
  | "FIB_EXTENSION" | "FIB_FAN" | "FIB_ARCS"
  // Freehand and shapes.
  | "BRUSH" | "CIRCLE" | "TRIANGLE"
  // Annotation.
  | "NOTE" | "PRICE_LABEL" | "CALLOUT"
  // Measurement.
  | "PRICE_RANGE" | "DATE_RANGE";

export interface Point {
  time: string;
  price: number;
}

/**
 * Presentation for one drawing. Colours are NAMES, resolved to hex here.
 *
 * The stored value would otherwise end up in an SVG stroke attribute, so
 * a closed set of names means the worst a tampered payload can do is
 * name a colour that does not exist — which falls back to the default.
 */
export interface DrawingStyle {
  colour?: string;
  width?: number;
  opacity?: number;
}

export interface Drawing {
  id: number | string;
  kind: DrawingKind;
  points: Point[];
  text?: string;
  locked: boolean;
  hidden: boolean;
  style?: DrawingStyle;
}

const COLOUR = "#8ab4f8";

export const STYLE_COLOURS: { name: string; hex: string; label: string }[] = [
  { name: "default", hex: "#8ab4f8", label: "Blue-grey" },
  { name: "gold", hex: "#d9a441", label: "Gold" },
  { name: "blue", hex: "#6aa9ff", label: "Blue" },
  { name: "green", hex: "#3fb950", label: "Green" },
  { name: "red", hex: "#f4564a", label: "Red" },
  { name: "purple", hex: "#b071e0", label: "Purple" },
  { name: "teal", hex: "#4ec9b0", label: "Teal" },
  { name: "grey", hex: "#9aa3b0", label: "Grey" },
];

const COLOUR_BY_NAME = new Map(STYLE_COLOURS.map((c) => [c.name, c.hex]));

export function resolveColour(style: DrawingStyle | undefined): string {
  return COLOUR_BY_NAME.get(style?.colour ?? "default") ?? COLOUR;
}

/**
 * Tool groups for the rail's flyout menus.
 *
 * The rail shows one button per GROUP and the group opens on click, which
 * is what keeps twenty-five tools inside a 46px strip. Showing every tool
 * at once would either wrap the rail into a block or shrink the icons past
 * usefulness — both cost the chart the space this layout exists to give it.
 */
export const TOOL_GROUPS: {
  id: string; label: string; glyph: string; kinds: (DrawingKind | "CURSOR")[];
}[] = [
  { id: "cursor", label: "Cursor", glyph: "\u2196", kinds: ["CURSOR"] },
  { id: "lines", label: "Lines and channels", glyph: "\uFF0F",
    kinds: ["TREND_LINE", "RAY", "EXTENDED_LINE", "HORIZONTAL",
            "HORIZONTAL_RAY", "VERTICAL", "CHANNEL", "ARROW"] },
  { id: "fib", label: "Fibonacci", glyph: "%",
    kinds: ["FIB", "FIB_EXTENSION", "FIB_FAN", "FIB_ARCS"] },
  { id: "shapes", label: "Shapes and brush", glyph: "\u25AD",
    kinds: ["RECTANGLE", "CIRCLE", "TRIANGLE", "BRUSH"] },
  { id: "text", label: "Text and notes", glyph: "T",
    kinds: ["TEXT", "NOTE", "CALLOUT", "PRICE_LABEL"] },
  { id: "measure", label: "Measurement", glyph: "\u2195",
    kinds: ["RULER", "PRICE_RANGE", "DATE_RANGE"] },
  { id: "position", label: "Position planners", glyph: "\u25B2",
    kinds: ["LONG_POSITION", "SHORT_POSITION"] },
];

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
  { kind: "RAY", label: "\u2197", hint: "Ray" },
  { kind: "EXTENDED_LINE", label: "\u2194", hint: "Extended line" },
  { kind: "HORIZONTAL_RAY", label: "\u2192", hint: "Horizontal ray" },
  { kind: "CHANNEL", label: "\u2225", hint: "Parallel channel" },
  { kind: "FIB_EXTENSION", label: "\u2192%", hint: "Fibonacci extension" },
  { kind: "FIB_FAN", label: "\u2A5B", hint: "Fibonacci fan" },
  { kind: "FIB_ARCS", label: "\u25DC", hint: "Fibonacci arcs" },
  { kind: "BRUSH", label: "\u270E", hint: "Brush" },
  { kind: "CIRCLE", label: "\u25CB", hint: "Circle" },
  { kind: "TRIANGLE", label: "\u25B3", hint: "Triangle" },
  { kind: "NOTE", label: "\u270D", hint: "Note" },
  { kind: "CALLOUT", label: "\u2691", hint: "Callout" },
  { kind: "PRICE_LABEL", label: "\u25C6", hint: "Price label" },
  { kind: "PRICE_RANGE", label: "\u2921", hint: "Price range" },
  { kind: "DATE_RANGE", label: "\u2194\uFE0E", hint: "Date range" },
];

/**
 * Retracement ratios, drawn between the two clicked swing points. 0 sits on
 * the first click and 1 on the second, so dragging low→high measures a
 * pullback in an uptrend and high→low one in a downtrend.
 */
const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

/** Extensions project past the move; the ratios above 1 are the targets. */
const EXTENSION_RATIOS = [0.618, 1, 1.272, 1.618, 2, 2.618];
const FAN_RATIOS = [0.382, 0.5, 0.618];
const ARC_RATIOS = [0.382, 0.5, 0.618];

/** Shapes needing two clicks; the rest are placed with one. */
const TWO_POINT: DrawingKind[] = [
  "TREND_LINE", "RECTANGLE", "ARROW", "RULER", "LONG_POSITION", "SHORT_POSITION",
  "FIB", "RAY", "EXTENDED_LINE", "CHANNEL", "FIB_EXTENSION", "FIB_FAN",
  "FIB_ARCS", "CIRCLE", "TRIANGLE", "PRICE_RANGE", "DATE_RANGE",
];

/** Kinds that ask for a text label when placed. */
const TEXT_KINDS: DrawingKind[] = ["TEXT", "NOTE", "CALLOUT", "PRICE_LABEL"];

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

    if (TEXT_KINDS.includes(tool)) {
      // A price label reads the price it was dropped on, so it needs no
      // typing — asking for text there would be busywork.
      if (tool === "PRICE_LABEL") {
        onCreate(tool, [point], point.price.toFixed(2));
        return;
      }
      const text = window.prompt(
        tool === "CALLOUT" ? "Callout text" : "Note text",
      );
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
          // Selection still wins over the drawing's own colour: knowing
          // what is selected matters more than its styling for as long
          // as it is selected.
          const stroke = drawing.id === selectedId
            ? SELECTED : resolveColour(drawing.style);
          const common = {
            stroke,
            strokeWidth: drawing.id === selectedId
              ? 2 : (drawing.style?.width ?? 1.4),
            strokeOpacity: drawing.style?.opacity ?? 1,
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
            case "HORIZONTAL_RAY":
              // A ray continues to the right edge only; the left side of
              // the level is deliberately not drawn, which is the whole
              // difference between a ray and a horizontal line.
              return <line key={drawing.id} x1={pts[0].x} y1={pts[0].y}
                           x2={width} y2={pts[0].y} {...common} />;
            case "RAY":
            case "EXTENDED_LINE": {
              // Extend along the segment's own direction rather than
              // clamping to the viewport corners, so the slope a customer
              // drew is the slope that continues.
              const dx = pts[1].x - pts[0].x;
              const dy = pts[1].y - pts[0].y;
              const length = Math.hypot(dx, dy) || 1;
              const reach = (width + height) * 2;
              const ux = (dx / length) * reach;
              const uy = (dy / length) * reach;
              const start = drawing.kind === "EXTENDED_LINE"
                ? { x: pts[0].x - ux, y: pts[0].y - uy }
                : pts[0];
              return (
                <line key={drawing.id} x1={start.x} y1={start.y}
                      x2={pts[0].x + ux} y2={pts[0].y + uy} {...common} />
              );
            }
            case "CHANNEL": {
              // Two parallel lines a fixed price distance apart, measured
              // from the two clicked points.
              const dy = pts[1].y - pts[0].y;
              const offset = Math.abs(dy) || 40;
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}>
                  <line x1={pts[0].x} y1={pts[0].y} x2={pts[1].x} y2={pts[0].y}
                        stroke={stroke} strokeWidth={common.strokeWidth} fill="none" />
                  <line x1={pts[0].x} y1={pts[0].y + offset}
                        x2={pts[1].x} y2={pts[0].y + offset}
                        stroke={stroke} strokeWidth={common.strokeWidth} fill="none" />
                  <polygon
                    points={`${pts[0].x},${pts[0].y} ${pts[1].x},${pts[0].y} `
                          + `${pts[1].x},${pts[0].y + offset} ${pts[0].x},${pts[0].y + offset}`}
                    fill="rgba(138, 180, 248, 0.07)" stroke="none" />
                </g>
              );
            }
            case "CIRCLE": {
              const rx = Math.abs(pts[1].x - pts[0].x);
              const ry = Math.abs(pts[1].y - pts[0].y);
              return <ellipse key={drawing.id} cx={pts[0].x} cy={pts[0].y}
                              rx={rx || 4} ry={ry || 4} {...common}
                              fill="rgba(138, 180, 248, 0.08)" />;
            }
            case "TRIANGLE":
              return (
                <polygon key={drawing.id}
                         points={`${pts[0].x},${pts[1].y} ${pts[1].x},${pts[1].y} `
                               + `${(pts[0].x + pts[1].x) / 2},${pts[0].y}`}
                         {...common} fill="rgba(138, 180, 248, 0.08)" />
              );
            case "PRICE_RANGE": {
              // Reports the move in price and as a percentage, which is
              // what the tool is for — the box is only a handle.
              const from = drawing.points[0].price;
              const to = drawing.points[1].price;
              const change = to - from;
              const pct = from !== 0 ? (change / from) * 100 : 0;
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}>
                  <rect x={Math.min(pts[0].x, pts[1].x)}
                        y={Math.min(pts[0].y, pts[1].y)}
                        width={Math.abs(pts[1].x - pts[0].x) || 50}
                        height={Math.abs(pts[1].y - pts[0].y)}
                        fill={change >= 0 ? "rgba(63,185,80,0.12)" : "rgba(244,86,74,0.12)"}
                        stroke={stroke} strokeWidth={1} />
                  <text x={Math.min(pts[0].x, pts[1].x) + 4}
                        y={Math.min(pts[0].y, pts[1].y) - 4}
                        fill={stroke} fontSize={10}>
                    {change >= 0 ? "+" : ""}{change.toFixed(2)} ({pct.toFixed(2)}%)
                  </text>
                </g>
              );
            }
            case "DATE_RANGE": {
              // Bar count is the honest measure here: the elapsed wall time
              // between two bars spans weekends and gaps the market was
              // shut for, so it would overstate how long the move took.
              const a = Date.parse(drawing.points[0].time);
              const b = Date.parse(drawing.points[1].time);
              const hours = Math.abs(b - a) / 3_600_000;
              const span = hours >= 48 ? `${(hours / 24).toFixed(1)}d`
                         : `${hours.toFixed(1)}h`;
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}>
                  <rect x={Math.min(pts[0].x, pts[1].x)} y={0}
                        width={Math.abs(pts[1].x - pts[0].x) || 40} height={height}
                        fill="rgba(138, 180, 248, 0.07)" stroke={stroke}
                        strokeWidth={1} strokeDasharray="4 3" />
                  <text x={(pts[0].x + pts[1].x) / 2} y={14} fill={stroke}
                        fontSize={10} textAnchor="middle">{span}</text>
                </g>
              );
            }
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
            case "NOTE":
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}
                   style={{ cursor: "move" }}>
                  <rect x={pts[0].x} y={pts[0].y - 12}
                        width={Math.max(28, (drawing.text?.length ?? 0) * 6 + 10)}
                        height={17} rx={4}
                        fill="rgba(15,17,21,0.86)" stroke={stroke} strokeWidth={1} />
                  <text x={pts[0].x + 5} y={pts[0].y} fill={stroke} fontSize={10}>
                    {drawing.text ?? ""}
                  </text>
                </g>
              );
            case "CALLOUT":
              // A leader line from the label to the exact point it marks,
              // so the annotation cannot drift away from its subject.
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}
                   style={{ cursor: "move" }}>
                  <line x1={pts[0].x} y1={pts[0].y} x2={pts[0].x + 26}
                        y2={pts[0].y - 22} stroke={stroke} strokeWidth={1} />
                  <circle cx={pts[0].x} cy={pts[0].y} r={2.5} fill={stroke} />
                  <rect x={pts[0].x + 26} y={pts[0].y - 34}
                        width={Math.max(30, (drawing.text?.length ?? 0) * 6 + 12)}
                        height={18} rx={4}
                        fill="rgba(15,17,21,0.9)" stroke={stroke} strokeWidth={1} />
                  <text x={pts[0].x + 32} y={pts[0].y - 21} fill={stroke} fontSize={10}>
                    {drawing.text ?? ""}
                  </text>
                </g>
              );
            case "PRICE_LABEL":
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}
                   style={{ cursor: "move" }}>
                  <line x1={pts[0].x} y1={pts[0].y} x2={width} y2={pts[0].y}
                        stroke={stroke} strokeWidth={1} strokeDasharray="2 3" />
                  <rect x={pts[0].x - 2} y={pts[0].y - 8} width={52} height={16}
                        rx={3} fill={stroke} />
                  <text x={pts[0].x + 24} y={pts[0].y + 4} fill="#0b0d11"
                        fontSize={10} textAnchor="middle">
                    {drawing.points[0].price.toFixed(2)}
                  </text>
                </g>
              );
            case "BRUSH":
              // Freehand is stored as the points it was drawn through, so
              // it reprojects correctly at any zoom like every other shape.
              return (
                <polyline key={drawing.id}
                          points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
                          {...common} strokeLinejoin="round"
                          strokeLinecap="round" />
              );
            case "FIB_EXTENSION":
            case "FIB_FAN":
            case "FIB_ARCS": {
              const [a, b] = drawing.points;
              const span = b.price - a.price;
              const left = Math.min(pts[0].x, pts[1].x);
              const right = Math.max(pts[0].x, pts[1].x);

              if (drawing.kind === "FIB_EXTENSION") {
                // Projects BEYOND the second point: 1.272 and 1.618 are
                // targets past the move, which is what separates an
                // extension from a retracement.
                return (
                  <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}>
                    {EXTENSION_RATIOS.map((ratio) => {
                      const price = a.price + span * ratio;
                      const y = coords?.priceToY(price);
                      if (y == null) return null;
                      return (
                        <g key={ratio}>
                          <line x1={left} y1={y} x2={right + 60} y2={y}
                                stroke={stroke} strokeWidth={1}
                                strokeDasharray={ratio > 1 ? undefined : "3 3"}
                                opacity={ratio > 1 ? 0.95 : 0.5} />
                          <text x={left + 3} y={y - 3} fill={stroke} fontSize={9}>
                            {ratio}  {price.toFixed(2)}
                          </text>
                        </g>
                      );
                    })}
                  </g>
                );
              }

              if (drawing.kind === "FIB_FAN") {
                // Rays from the first point through fractions of the move.
                return (
                  <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}>
                    {FAN_RATIOS.map((ratio) => {
                      const price = a.price + span * ratio;
                      const y = coords?.priceToY(price);
                      if (y == null) return null;
                      const dx = pts[1].x - pts[0].x || 1;
                      const dy = y - pts[0].y;
                      const scale = (width * 2) / Math.abs(dx);
                      return (
                        <line key={ratio} x1={pts[0].x} y1={pts[0].y}
                              x2={pts[0].x + dx * scale} y2={pts[0].y + dy * scale}
                              stroke={stroke} strokeWidth={1} opacity={0.75} />
                      );
                    })}
                  </g>
                );
              }

              // Arcs: semicircles centred on the second point, radius scaled
              // by the move's own pixel length.
              const radius = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y);
              return (
                <g key={drawing.id} onMouseDown={(e) => startDrag(e, drawing)}>
                  {ARC_RATIOS.map((ratio) => (
                    <path key={ratio}
                          d={`M ${pts[1].x - radius * ratio} ${pts[1].y} `
                           + `A ${radius * ratio} ${radius * ratio} 0 0 1 `
                           + `${pts[1].x + radius * ratio} ${pts[1].y}`}
                          stroke={stroke} strokeWidth={1} fill="none" opacity={0.7} />
                  ))}
                </g>
              );
            }
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
