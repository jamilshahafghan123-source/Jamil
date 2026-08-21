import { useEffect, useRef } from "react";

/**
 * Chart replay (section 42).
 *
 * Replay only ever REVEALS bars that already exist — it slices the loaded
 * history and shows a prefix of it. It never generates a candle, and it
 * has no execution path of any kind: there is no order call in this file
 * and no way to reach one from it, which is what makes "replay can never
 * send a live order" a structural fact rather than a promise.
 *
 * LIVE versus REPLAY is deliberately loud. A customer who mistakes
 * recorded history for the live market could act on a price that is
 * hours old, so the banner is unmissable and the chart carries a badge
 * for as long as replay is on.
 */

export const REPLAY_SPEEDS = [0.5, 1, 2, 4, 8] as const;

export function ReplayBar({
  active, index, total, playing, speed,
  onToggleActive, onPlayPause, onStep, onJump, onSpeed, onReset, onExit,
}: {
  active: boolean;
  index: number;
  total: number;
  playing: boolean;
  speed: number;
  onToggleActive: () => void;
  onPlayPause: () => void;
  onStep: () => void;
  onJump: (bars: number) => void;
  onSpeed: (speed: number) => void;
  onReset: () => void;
  onExit: () => void;
}) {
  const timer = useRef<number | null>(null);

  // One interval, rebuilt when speed changes and cleared on unmount, so
  // switching speed cannot leave a second timer running behind the first.
  useEffect(() => {
    if (!active || !playing) return;
    const period = Math.max(80, 1000 / speed);
    timer.current = window.setInterval(onStep, period);
    return () => {
      if (timer.current != null) window.clearInterval(timer.current);
      timer.current = null;
    };
  }, [active, playing, speed, onStep]);

  if (!active) {
    return (
      <button type="button" className="btn sm" onClick={onToggleActive}
              title="Step through recorded history">
        Replay
      </button>
    );
  }

  const atEnd = index >= total - 1;

  return (
    <div className="jg-replay" role="group" aria-label="Chart replay">
      <span className="jg-replay-badge">REPLAY</span>

      <button type="button" className="jg-replay-btn" onClick={onPlayPause}
              title={playing ? "Pause" : "Play"}
              aria-label={playing ? "Pause" : "Play"}>
        {playing ? "❙❙" : "▶"}
      </button>
      <button type="button" className="jg-replay-btn" onClick={onStep}
              disabled={atEnd} title="Next candle" aria-label="Next candle">
        ▶❙
      </button>
      <button type="button" className="jg-replay-btn" onClick={() => onJump(-10)}
              title="Back 10 candles" aria-label="Back 10 candles">
        ⏪
      </button>
      <button type="button" className="jg-replay-btn" onClick={() => onJump(10)}
              disabled={atEnd} title="Forward 10 candles"
              aria-label="Forward 10 candles">
        ⏩
      </button>

      <select value={speed} onChange={(e) => onSpeed(Number(e.target.value))}
              aria-label="Replay speed" className="jg-replay-speed">
        {REPLAY_SPEEDS.map((s) => (
          <option key={s} value={s}>{s}×</option>
        ))}
      </select>

      <span className="jg-replay-count">
        {index + 1} / {total}
      </span>

      <button type="button" className="jg-replay-btn" onClick={onReset}
              title="Back to the start" aria-label="Reset replay">
        ↺
      </button>
      <button type="button" className="btn sm" onClick={onExit}
              title="Return to the live chart">
        Exit
      </button>
    </div>
  );
}
