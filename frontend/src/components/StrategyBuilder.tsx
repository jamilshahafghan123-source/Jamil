import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { BacktestPanel } from "./BacktestPanel";
import type {
  Bar, SavedStrategy, StrategyCondition, StrategyGroup, StrategyRule,
  StrategyVocabulary, Timeframe,
} from "../lib/types";

/**
 * Strategy builder (sections 32-37).
 *
 * Every option offered here comes from `/api/strategies/vocabulary`, so
 * the builder cannot present a field, operator or action mode the backend
 * would refuse. There is no free-text rule input anywhere: a customer
 * assembles conditions from closed lists, which is what makes "no
 * arbitrary code" a property of the interface and not just of the parser
 * behind it.
 *
 * The backend re-validates everything regardless. This component is a
 * convenience, never the boundary.
 */

const OPERATOR_LABEL: Record<string, string> = {
  GT: "is greater than", LT: "is less than",
  GTE: "is at least", LTE: "is at most",
  EQUALS: "is", NOT_EQUALS: "is not",
  CROSSES_ABOVE: "crosses above", CROSSES_BELOW: "crosses below",
  ENTERS_ZONE: "enters zone", LEAVES_ZONE: "leaves zone",
  IS_TRUE: "is true", IS_FALSE: "is false",
};

const MODE_LABEL: Record<string, string> = {
  ALERT_ONLY: "Alert only — notify me, change nothing",
  AI_ASSIST: "AI Assist — fill the ticket, I confirm",
  DEMO_AUTO: "Demo Auto — trade the J Gold AI demo account",
};

const BOOLEAN_OPERATORS = ["IS_TRUE", "IS_FALSE"];
const ZONE_OPERATORS = ["ENTERS_ZONE", "LEAVES_ZONE"];

function isGroup(node: StrategyRule): node is StrategyGroup {
  return (node as StrategyGroup).logic !== undefined;
}

function blankCondition(): StrategyCondition {
  return { field: "RSI", operator: "GT", value: 55, period: 14,
           timeframe: "M15" };
}

function emptyRule(): StrategyGroup {
  return { logic: "AND", children: [blankCondition()] };
}

function countConditions(node: StrategyRule): number {
  return isGroup(node)
    ? node.children.reduce((n, c) => n + countConditions(c), 0)
    : 1;
}

export function StrategyBuilder({ open, onClose, symbol, timeframe, bars }: {
  open: boolean;
  onClose: () => void;
  symbol: string;
  timeframe: string;
  /** The loaded history, so backtest prerequisites are measured not assumed. */
  bars: Bar[];
}) {
  const [vocabulary, setVocabulary] = useState<StrategyVocabulary | null>(null);
  const [saved, setSaved] = useState<SavedStrategy[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [direction, setDirection] = useState<"BUY" | "SELL">("BUY");
  const [mode, setMode] = useState("ALERT_ONLY");
  const [notes, setNotes] = useState("");
  const [rule, setRule] = useState<StrategyGroup>(emptyRule);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setSaved(await api.strategies());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load strategies");
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    if (!vocabulary) {
      api.strategyVocabulary().then(setVocabulary).catch((err) =>
        setError(err instanceof Error ? err.message : "Builder unavailable"));
    }
    void refresh();
  }, [open, vocabulary, refresh]);

  const fieldInfo = useMemo(() => {
    const map = new Map<string, { boolean: boolean; zone: boolean; labels: string[] }>();
    for (const f of vocabulary?.fields ?? []) {
      map.set(f.field, { boolean: f.boolean, zone: f.zone, labels: f.labels });
    }
    return map;
  }, [vocabulary]);

  /** Operators that make sense for a field, so the form cannot build a
   *  combination the backend would reject. */
  const operatorsFor = useCallback((field: string): string[] => {
    const info = fieldInfo.get(field);
    const all = vocabulary?.operators ?? [];
    if (!info) return all;
    if (info.boolean) return all.filter((o) => BOOLEAN_OPERATORS.includes(o));
    if (info.labels.length > 0) return ["EQUALS", "NOT_EQUALS"];
    return all.filter(
      (o) => !BOOLEAN_OPERATORS.includes(o) &&
        (info.zone || !ZONE_OPERATORS.includes(o)),
    );
  }, [fieldInfo, vocabulary]);

  function editPath(path: number[], change: (node: StrategyRule) => StrategyRule) {
    setRule((current) => {
      const clone = structuredClone(current) as StrategyGroup;
      if (path.length === 0) return change(clone) as StrategyGroup;
      let parent: StrategyGroup = clone;
      for (const step of path.slice(0, -1)) {
        parent = parent.children[step] as StrategyGroup;
      }
      const last = path[path.length - 1];
      parent.children[last] = change(parent.children[last]);
      return clone;
    });
  }

  function removePath(path: number[]) {
    setRule((current) => {
      const clone = structuredClone(current) as StrategyGroup;
      let parent: StrategyGroup = clone;
      for (const step of path.slice(0, -1)) {
        parent = parent.children[step] as StrategyGroup;
      }
      parent.children.splice(path[path.length - 1], 1);
      // A group with nothing in it is not a rule; keep one condition.
      if (clone.children.length === 0) clone.children.push(blankCondition());
      return clone;
    });
  }

  function addTo(path: number[], node: StrategyRule) {
    setRule((current) => {
      const clone = structuredClone(current) as StrategyGroup;
      let target: StrategyGroup = clone;
      for (const step of path) target = target.children[step] as StrategyGroup;
      target.children.push(node);
      return clone;
    });
  }

  function reset() {
    setEditingId(null);
    setName("");
    setDirection("BUY");
    setMode("ALERT_ONLY");
    setNotes("");
    setRule(emptyRule());
    setError(null);
  }

  function load(strategy: SavedStrategy) {
    if (!strategy.valid) {
      setError("This strategy can no longer be read and cannot be edited.");
      return;
    }
    setEditingId(strategy.id);
    setName(strategy.name);
    setDirection(strategy.direction);
    setMode(strategy.action_mode);
    setNotes(strategy.notes);
    setRule(
      isGroup(strategy.rule as StrategyRule)
        ? (strategy.rule as StrategyGroup)
        : { logic: "AND", children: [strategy.rule as StrategyCondition] },
    );
    setError(null);
  }

  async function save() {
    setBusy(true);
    setError(null);
    const body = {
      name: name.trim(), symbol, timeframe, direction,
      action_mode: mode, rule, notes,
    };
    try {
      if (editingId != null) await api.updateStrategy(editingId, body);
      else await api.createStrategy(body);
      await refresh();
      reset();
    } catch (err) {
      // The backend's reason is the useful one — it names the condition.
      setError(err instanceof Error ? err.message : "Could not save strategy");
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  const conditionCount = countConditions(rule);
  const limit = vocabulary?.limits.max_conditions ?? 40;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-label="Strategy builder" onClick={onClose}>
      <div className="modal jg-strategy-modal" onClick={(e) => e.stopPropagation()}>
        <header className="jg-symbol-head">
          <h3 className="jg-strategy-title">
            {editingId != null ? "Edit strategy" : "New strategy"}
          </h3>
          <div className="jg-spacer" />
          <button type="button" className="btn sm" onClick={onClose}>Close</button>
        </header>

        {error && <p className="jg-ws-error">{error}</p>}

        <div className="jg-strategy-body">
          <section className="jg-strategy-form">
            <div className="jg-strategy-row">
              <label>
                Name
                <input value={name} maxLength={80}
                       placeholder="London EMA continuation"
                       onChange={(e) => setName(e.target.value)} />
              </label>
              <label>
                Direction
                <select value={direction}
                        onChange={(e) => setDirection(e.target.value as "BUY" | "SELL")}>
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                </select>
              </label>
            </div>

            <label className="jg-strategy-full">
              When it matches
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                {(vocabulary?.action_modes ?? []).map((m) => (
                  <option key={m} value={m}>{MODE_LABEL[m] ?? m}</option>
                ))}
              </select>
            </label>

            <p className="jg-strategy-scope">
              Applies to <strong>{symbol}</strong> on <strong>{timeframe}</strong>.
              A strategy proposes a setup — the risk manager still decides,
              and real broker trading stays disabled.
            </p>

            <div className="jg-strategy-rule">
              <RuleEditor
                node={rule}
                path={[]}
                vocabulary={vocabulary}
                operatorsFor={operatorsFor}
                fieldInfo={fieldInfo}
                onEdit={editPath}
                onRemove={removePath}
                onAdd={addTo}
                canAdd={conditionCount < limit}
              />
            </div>

            <p className="jg-strategy-count">
              {conditionCount} of {limit} conditions used.
            </p>

            <label className="jg-strategy-full">
              Notes
              <textarea value={notes} maxLength={500} rows={2}
                        onChange={(e) => setNotes(e.target.value)} />
            </label>

            <div className="jg-strategy-actions">
              <button type="button" className="btn primary" disabled={busy || !name.trim()}
                      onClick={() => void save()}>
                {editingId != null ? "Save changes" : "Create strategy"}
              </button>
              {editingId != null && (
                <button type="button" className="btn sm" onClick={reset}>
                  New instead
                </button>
              )}
            </div>
          </section>

          <section className="jg-strategy-saved">
            <h4 className="jg-symbol-group">Saved strategies ({saved.length})</h4>
            {saved.length === 0 && (
              <p className="jg-cc-note">
                No strategies yet. Build one on the left — it stays yours and
                is never shared.
              </p>
            )}
            {saved.map((strategy) => (
              <article key={strategy.id}
                       className={strategy.valid ? "jg-strategy-card"
                                                 : "jg-strategy-card invalid"}>
                <div className="jg-strategy-card-head">
                  <strong>{strategy.name}</strong>
                  <span className={`jg-symbol-status ${
                    strategy.enabled ? "enabled" : "coming_soon"}`}>
                    {strategy.enabled ? "Enabled" : "Disabled"}
                  </span>
                </div>
                <p className="jg-strategy-meta">
                  {strategy.symbol} · {strategy.timeframe} · {strategy.direction}
                  {" · "}{MODE_LABEL[strategy.action_mode]?.split(" — ")[0]
                          ?? strategy.action_mode}
                </p>
                <pre className="jg-strategy-desc">
                  {strategy.description.join("\n")}
                </pre>
                <div className="jg-strategy-card-actions">
                  <button type="button" className="btn sm" disabled={busy || !strategy.valid}
                          onClick={() => load(strategy)}>Edit</button>
                  <button type="button" className="btn sm" disabled={busy || !strategy.valid}
                          onClick={() => void act(() =>
                            api.setStrategyEnabled(strategy.id, !strategy.enabled))}>
                    {strategy.enabled ? "Disable" : "Enable"}
                  </button>
                  <button type="button" className="btn sm" disabled={busy}
                          onClick={() => void act(() => api.cloneStrategy(strategy.id))}>
                    Clone
                  </button>
                  <button type="button" className="btn sm danger" disabled={busy}
                          onClick={() => void act(() => api.deleteStrategy(strategy.id))}>
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </section>

          {/* Backtesting belongs with the strategies it would test, and
              its prerequisites belong beside the builder rather than in a
              panel nobody opens until they expect a result. */}
          <BacktestPanel bars={bars} symbol={symbol}
                         timeframe={timeframe as Timeframe} />
        </div>

        <footer className="jg-symbol-foot">
          {vocabulary?.note ??
            "Strategies are built from fixed conditions. No code is accepted or executed."}
        </footer>
      </div>
    </div>
  );
}

function RuleEditor({
  node, path, vocabulary, operatorsFor, fieldInfo, onEdit, onRemove, onAdd, canAdd,
}: {
  node: StrategyRule;
  path: number[];
  vocabulary: StrategyVocabulary | null;
  operatorsFor: (field: string) => string[];
  fieldInfo: Map<string, { boolean: boolean; zone: boolean; labels: string[] }>;
  onEdit: (path: number[], change: (n: StrategyRule) => StrategyRule) => void;
  onRemove: (path: number[]) => void;
  onAdd: (path: number[], node: StrategyRule) => void;
  canAdd: boolean;
}) {
  if (isGroup(node)) {
    return (
      <div className="jg-rule-group">
        <div className="jg-rule-group-head">
          <select
            value={node.logic}
            aria-label="Combine with"
            onChange={(e) =>
              onEdit(path, (n) => ({ ...(n as StrategyGroup), logic: e.target.value }))}
          >
            {(vocabulary?.logic ?? ["AND", "OR", "NOT"]).map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
          <button type="button" className="btn sm" disabled={!canAdd}
                  onClick={() => onAdd(path, blankCondition())}>
            + Condition
          </button>
          <button type="button" className="btn sm" disabled={!canAdd}
                  onClick={() => onAdd(path, emptyRule())}>
            + Group
          </button>
          {path.length > 0 && (
            <button type="button" className="btn sm danger"
                    onClick={() => onRemove(path)}>Remove</button>
          )}
        </div>
        <div className="jg-rule-children">
          {node.children.map((child, index) => (
            <RuleEditor
              key={index}
              node={child}
              path={[...path, index]}
              vocabulary={vocabulary}
              operatorsFor={operatorsFor}
              fieldInfo={fieldInfo}
              onEdit={onEdit}
              onRemove={onRemove}
              onAdd={onAdd}
              canAdd={canAdd}
            />
          ))}
        </div>
      </div>
    );
  }

  const condition = node;
  const info = fieldInfo.get(condition.field);
  const operators = operatorsFor(condition.field);
  const needsValue = !BOOLEAN_OPERATORS.includes(condition.operator);
  const labels = info?.labels ?? [];

  return (
    <div className="jg-rule-condition">
      <select
        value={condition.field}
        aria-label="Field"
        onChange={(e) => {
          const field = e.target.value;
          const next = operatorsFor(field);
          const nextInfo = fieldInfo.get(field);
          onEdit(path, (n) => ({
            ...(n as StrategyCondition),
            field,
            // Switching field can invalidate the operator and value, so
            // both are reset to something the backend will accept.
            operator: next.includes((n as StrategyCondition).operator)
              ? (n as StrategyCondition).operator : next[0],
            value: nextInfo?.labels.length ? nextInfo.labels[0]
                 : nextInfo?.boolean ? null : 0,
          }));
        }}
      >
        {(vocabulary?.fields ?? []).map((f) => (
          <option key={f.field} value={f.field}>{f.field}</option>
        ))}
      </select>

      <input
        className="jg-rule-period"
        type="number"
        min={1}
        max={500}
        placeholder="period"
        aria-label="Period"
        value={condition.period ?? ""}
        onChange={(e) =>
          onEdit(path, (n) => ({
            ...(n as StrategyCondition),
            period: e.target.value === "" ? null : Number(e.target.value),
          }))}
      />

      <select
        value={condition.operator}
        aria-label="Operator"
        onChange={(e) =>
          onEdit(path, (n) => ({
            ...(n as StrategyCondition), operator: e.target.value,
          }))}
      >
        {operators.map((o) => (
          <option key={o} value={o}>{OPERATOR_LABEL[o] ?? o}</option>
        ))}
      </select>

      {needsValue && (
        labels.length > 0 ? (
          <select
            value={String(condition.value ?? labels[0])}
            aria-label="Value"
            onChange={(e) =>
              onEdit(path, (n) => ({
                ...(n as StrategyCondition), value: e.target.value,
              }))}
          >
            {labels.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        ) : (
          <input
            className="jg-rule-value"
            type="number"
            step="any"
            aria-label="Value"
            value={typeof condition.value === "number" ? condition.value : ""}
            onChange={(e) =>
              onEdit(path, (n) => ({
                ...(n as StrategyCondition),
                value: e.target.value === "" ? 0 : Number(e.target.value),
              }))}
          />
        )
      )}

      <select
        className="jg-rule-tf"
        value={condition.timeframe}
        aria-label="Timeframe"
        onChange={(e) =>
          onEdit(path, (n) => ({
            ...(n as StrategyCondition), timeframe: e.target.value,
          }))}
      >
        {(vocabulary?.timeframes ?? ["M15"]).map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>

      <button type="button" className="btn sm danger"
              aria-label="Remove condition"
              onClick={() => onRemove(path)}>×</button>
    </div>
  );
}
