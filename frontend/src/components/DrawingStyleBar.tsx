import { STYLE_COLOURS, type Drawing } from "./DrawingLayer";

/**
 * Style controls for the selected drawing.
 *
 * Appears only while something is selected and unlocked, so it never sits
 * over the chart doing nothing. A locked drawing shows the bar in a
 * read-only state rather than hiding it — the customer needs to see WHY
 * the controls will not respond, and an unlock button beside them.
 */
export function DrawingStyleBar({
  drawing, onStyle, onToggle, onDelete, onClose,
}: {
  drawing: Drawing;
  onStyle: (style: { colour?: string; width?: number; opacity?: number }) => void;
  onToggle: (field: "locked" | "hidden") => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const style = drawing.style ?? {};
  const locked = drawing.locked;

  return (
    <div className="jg-stylebar" role="toolbar" aria-label="Drawing style">
      <span className="jg-stylebar-kind">
        {drawing.kind.replace(/_/g, " ").toLowerCase()}
      </span>

      <span className="jg-stylebar-sep" />

      <span className="jg-stylebar-swatches">
        {STYLE_COLOURS.map((colour) => (
          <button
            key={colour.name}
            type="button"
            className={(style.colour ?? "default") === colour.name
              ? "jg-swatch active" : "jg-swatch"}
            style={{ background: colour.hex }}
            title={colour.label}
            aria-label={colour.label}
            aria-pressed={(style.colour ?? "default") === colour.name}
            disabled={locked}
            onClick={() => onStyle({ colour: colour.name })}
          />
        ))}
      </span>

      <span className="jg-stylebar-sep" />

      <label className="jg-stylebar-field">
        Width
        <select
          value={style.width ?? 1}
          disabled={locked}
          aria-label="Line width"
          onChange={(e) => onStyle({ width: Number(e.target.value) })}
        >
          <option value={1}>Thin</option>
          <option value={2}>Medium</option>
          <option value={3}>Thick</option>
        </select>
      </label>

      <label className="jg-stylebar-field">
        Opacity
        <input
          type="range"
          min={10}
          max={100}
          step={10}
          disabled={locked}
          aria-label="Opacity"
          value={Math.round((style.opacity ?? 1) * 100)}
          onChange={(e) => onStyle({ opacity: Number(e.target.value) / 100 })}
        />
      </label>

      <span className="jg-stylebar-sep" />

      <button type="button" className="jg-stylebar-btn"
              aria-pressed={locked}
              title={locked ? "Unlock" : "Lock"}
              aria-label={locked ? "Unlock drawing" : "Lock drawing"}
              onClick={() => onToggle("locked")}>
        {locked ? "🔒" : "🔓"}
      </button>
      <button type="button" className="jg-stylebar-btn"
              aria-pressed={drawing.hidden}
              title={drawing.hidden ? "Show" : "Hide"}
              aria-label={drawing.hidden ? "Show drawing" : "Hide drawing"}
              onClick={() => onToggle("hidden")}>
        {drawing.hidden ? "🚫" : "👁"}
      </button>
      <button type="button" className="jg-stylebar-btn danger"
              title="Delete" aria-label="Delete drawing"
              onClick={onDelete}>
        🗑
      </button>
      <button type="button" className="jg-stylebar-btn"
              title="Deselect" aria-label="Deselect" onClick={onClose}>
        ×
      </button>

      {locked && (
        <span className="jg-stylebar-locked">
          Locked — unlock to edit
        </span>
      )}
    </div>
  );
}
