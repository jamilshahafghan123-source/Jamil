import { TOOLS, type Drawing } from "./DrawingLayer";

/**
 * Object Tree / drawings manager (section 17).
 *
 * Lists what the customer has drawn on THIS symbol and timeframe, with
 * the four actions the toolbar offers on a selection: select, show/hide,
 * lock/unlock, delete.
 *
 * Section 17 asks that internal database identifiers stay out of the UI,
 * so a row is named by its tool and its position in the list. The id is
 * used as a React key and passed back to the callbacks, never displayed.
 */

const TOOL_NAME = new Map(TOOLS.map((tool) => [tool.kind, tool.hint]));

export function ObjectTree({
  drawings,
  symbol,
  timeframe,
  selectedId,
  onSelect,
  onToggle,
  onDelete,
}: {
  drawings: Drawing[];
  symbol: string;
  timeframe: string;
  selectedId: number | string | null;
  onSelect: (id: number | string | null) => void;
  onToggle: (id: number | string, field: "locked" | "hidden") => void;
  onDelete: (id: number | string) => void;
}) {
  if (drawings.length === 0) {
    return (
      <div className="jg-tree">
        <p className="jg-cc-note">
          Nothing drawn on {symbol} {timeframe} yet. Drawings are saved per
          symbol and timeframe, so each chart keeps its own.
        </p>
      </div>
    );
  }

  // Numbered per tool type, so two trend lines read as "Trend line 1" and
  // "Trend line 2" rather than by a database id that means nothing.
  const counters = new Map<string, number>();

  return (
    <div className="jg-tree">
      <p className="jg-tree-scope">
        {symbol} · {timeframe} · {drawings.length}{" "}
        {drawings.length === 1 ? "object" : "objects"}
      </p>
      <ul className="jg-tree-list">
        {drawings.map((drawing) => {
          const label = TOOL_NAME.get(drawing.kind) ?? drawing.kind;
          const seen = (counters.get(label) ?? 0) + 1;
          counters.set(label, seen);
          const selected = drawing.id === selectedId;

          return (
            <li
              key={drawing.id}
              className={selected ? "jg-tree-row selected" : "jg-tree-row"}
            >
              <button
                type="button"
                className="jg-tree-name"
                onClick={() => onSelect(selected ? null : drawing.id)}
                title={drawing.text || label}
              >
                <span className="jg-tree-label">
                  {label} {seen}
                </span>
                {drawing.text && (
                  <span className="jg-tree-text">{drawing.text}</span>
                )}
              </button>

              <button
                type="button"
                className="jg-tree-action"
                aria-pressed={drawing.hidden}
                title={drawing.hidden ? "Show" : "Hide"}
                aria-label={drawing.hidden
                  ? `Show ${label} ${seen}` : `Hide ${label} ${seen}`}
                onClick={() => onToggle(drawing.id, "hidden")}
              >
                {drawing.hidden ? "🚫" : "👁"}
              </button>

              <button
                type="button"
                className="jg-tree-action"
                aria-pressed={drawing.locked}
                title={drawing.locked ? "Unlock" : "Lock"}
                aria-label={drawing.locked
                  ? `Unlock ${label} ${seen}` : `Lock ${label} ${seen}`}
                onClick={() => onToggle(drawing.id, "locked")}
              >
                {drawing.locked ? "🔒" : "🔓"}
              </button>

              <button
                type="button"
                className="jg-tree-action danger"
                title="Delete"
                aria-label={`Delete ${label} ${seen}`}
                onClick={() => onDelete(drawing.id)}
              >
                🗑
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
