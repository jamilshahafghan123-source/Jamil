import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type {
  Drawing, DrawingKind, DrawingStyle, Point,
} from "./DrawingLayer";

/**
 * Drawing state, persistence and history.
 *
 * UNDO/REDO IS LOCAL AND EXPLICIT. Each action pushes an inverse onto an
 * undo stack; performing a new action clears the redo stack, as it must —
 * a redo stack that survives divergent history replays edits the user
 * never made.
 *
 * Persistence is per user, symbol and timeframe. Switching either reloads
 * from the backend rather than filtering a cached list, so a drawing can
 * never leak onto the wrong chart.
 */

type UndoStep =
  | { type: "created"; id: number }
  | { type: "deleted"; drawing: Drawing }
  | { type: "moved"; id: number | string; points: Point[] };

function fromApi(row: {
  id: number;
  kind: string;
  payload: { points?: Point[]; text?: string; style?: DrawingStyle };
  locked: boolean;
  hidden: boolean;
}): Drawing {
  return {
    id: row.id,
    kind: row.kind as DrawingKind,
    points: row.payload?.points ?? [],
    text: row.payload?.text,
    locked: row.locked,
    hidden: row.hidden,
    style: row.payload?.style,
  };
}

export function useDrawings(symbol: string, timeframe: string) {
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [selectedId, setSelectedId] = useState<number | string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const undoStack = useRef<UndoStep[]>([]);
  const redoStack = useRef<UndoStep[]>([]);
  const [, bump] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const rows = await api.drawings(symbol, timeframe);
      setDrawings(rows.map(fromApi));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load drawings");
    }
  }, [symbol, timeframe]);

  // Reload on every scope change. Filtering a cached list would risk a
  // drawing appearing on a chart it does not belong to.
  useEffect(() => {
    undoStack.current = [];
    redoStack.current = [];
    setSelectedId(null);
    void refresh();
  }, [refresh]);

  const create = useCallback(
    async (kind: DrawingKind, points: Point[], text?: string) => {
      try {
        const row = await api.createDrawing({
          symbol, timeframe, kind, payload: { points, ...(text ? { text } : {}) },
        });
        setDrawings((current) => [...current, fromApi(row)]);
        undoStack.current.push({ type: "created", id: row.id });
        redoStack.current = [];
        bump((n) => n + 1);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not save drawing");
      }
    },
    [symbol, timeframe],
  );

  const move = useCallback(
    async (id: number | string, points: Point[]) => {
      const before = drawings.find((d) => d.id === id);
      if (!before || before.locked) return;
      setDrawings((current) =>
        current.map((d) => (d.id === id ? { ...d, points } : d)),
      );
      undoStack.current.push({ type: "moved", id, points: before.points });
      redoStack.current = [];
      bump((n) => n + 1);
      try {
        await api.updateDrawing(Number(id), {
          payload: { points, ...(before.text ? { text: before.text } : {}) },
        });
      } catch {
        // The server refused; put the drawing back where it was rather
        // than showing a position that was not saved.
        setDrawings((current) =>
          current.map((d) => (d.id === id ? { ...d, points: before.points } : d)),
        );
      }
    },
    [drawings],
  );

  /**
   * Change how a drawing looks.
   *
   * Style rides in the same payload as the points, because the API takes
   * the payload whole — sending style alone would drop the geometry.
   * A refused change is rolled back rather than left on screen unsaved.
   */
  const setStyle = useCallback(
    async (id: number | string, patch: DrawingStyle) => {
      const before = drawings.find((d) => d.id === id);
      if (!before || before.locked) return;
      const style = { ...(before.style ?? {}), ...patch };
      setDrawings((current) =>
        current.map((d) => (d.id === id ? { ...d, style } : d)),
      );
      try {
        await api.updateDrawing(Number(id), {
          payload: {
            points: before.points,
            ...(before.text ? { text: before.text } : {}),
            style,
          },
        });
      } catch {
        setDrawings((current) =>
          current.map((d) =>
            (d.id === id ? { ...d, style: before.style } : d)),
        );
      }
    },
    [drawings],
  );

  const remove = useCallback(
    async (id: number | string) => {
      const drawing = drawings.find((d) => d.id === id);
      if (!drawing) return;
      setDrawings((current) => current.filter((d) => d.id !== id));
      if (selectedId === id) setSelectedId(null);
      undoStack.current.push({ type: "deleted", drawing });
      redoStack.current = [];
      bump((n) => n + 1);
      try {
        await api.deleteDrawing(Number(id));
      } catch {
        void refresh();
      }
    },
    [drawings, selectedId, refresh],
  );

  const toggle = useCallback(
    async (id: number | string, field: "locked" | "hidden") => {
      const drawing = drawings.find((d) => d.id === id);
      if (!drawing) return;
      const next = !drawing[field];
      setDrawings((current) =>
        current.map((d) => (d.id === id ? { ...d, [field]: next } : d)),
      );
      try {
        await api.updateDrawing(Number(id), { [field]: next });
      } catch {
        void refresh();
      }
    },
    [drawings, refresh],
  );

  const clear = useCallback(async () => {
    try {
      await api.clearDrawings(symbol, timeframe);
      setDrawings([]);
      setSelectedId(null);
      // History refers to rows that no longer exist.
      undoStack.current = [];
      redoStack.current = [];
      bump((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not clear drawings");
    }
  }, [symbol, timeframe]);

  const undo = useCallback(async () => {
    const step = undoStack.current.pop();
    if (!step) return;
    if (step.type === "created") {
      const drawing = drawings.find((d) => d.id === step.id);
      if (drawing) redoStack.current.push({ type: "deleted", drawing });
      setDrawings((current) => current.filter((d) => d.id !== step.id));
      try {
        await api.deleteDrawing(step.id);
      } catch {
        void refresh();
      }
    } else if (step.type === "deleted") {
      try {
        const row = await api.createDrawing({
          symbol, timeframe, kind: step.drawing.kind,
          payload: {
            points: step.drawing.points,
            ...(step.drawing.text ? { text: step.drawing.text } : {}),
          },
        });
        setDrawings((current) => [...current, fromApi(row)]);
        redoStack.current.push({ type: "created", id: row.id });
      } catch {
        void refresh();
      }
    } else {
      const current = drawings.find((d) => d.id === step.id);
      if (current) redoStack.current.push({ type: "moved", id: step.id,
                                           points: current.points });
      setDrawings((all) =>
        all.map((d) => (d.id === step.id ? { ...d, points: step.points } : d)),
      );
      try {
        await api.updateDrawing(Number(step.id), { payload: { points: step.points } });
      } catch {
        void refresh();
      }
    }
    bump((n) => n + 1);
  }, [drawings, symbol, timeframe, refresh]);

  const redo = useCallback(async () => {
    const step = redoStack.current.pop();
    if (!step) return;
    // A redo is the same operation as its undo, replayed forward.
    if (step.type === "deleted") {
      try {
        const row = await api.createDrawing({
          symbol, timeframe, kind: step.drawing.kind,
          payload: {
            points: step.drawing.points,
            ...(step.drawing.text ? { text: step.drawing.text } : {}),
          },
        });
        setDrawings((current) => [...current, fromApi(row)]);
        undoStack.current.push({ type: "created", id: row.id });
      } catch {
        void refresh();
      }
    } else if (step.type === "created") {
      setDrawings((current) => current.filter((d) => d.id !== step.id));
      undoStack.current.push({ type: "deleted",
        drawing: drawings.find((d) => d.id === step.id)! });
      try {
        await api.deleteDrawing(step.id);
      } catch {
        void refresh();
      }
    } else {
      setDrawings((all) =>
        all.map((d) => (d.id === step.id ? { ...d, points: step.points } : d)),
      );
      try {
        await api.updateDrawing(Number(step.id), { payload: { points: step.points } });
      } catch {
        void refresh();
      }
    }
    bump((n) => n + 1);
  }, [drawings, symbol, timeframe, refresh]);

  return {
    drawings, selectedId, setSelectedId, error,
    create, move, remove, toggle, clear, undo, redo, setStyle,
    canUndo: undoStack.current.length > 0,
    canRedo: redoStack.current.length > 0,
  };
}
