import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type {
  AccountSnapshot,
  AiAnalysis,
  Candle,
  ConnectionStatus,
  DataSource,
  HistoryTrade,
  Position,
  Quote,
  RiskSettings,
  RiskUsage,
  Timeframe,
} from '@/types';
import {
  deriveRiskUsage,
  fetchAccount,
  fetchAnalysis,
  fetchCandles,
  fetchConnectionStatus,
  fetchHistory,
  fetchPositions,
  fetchQuote,
  fetchRiskSettings,
  POLL_INTERVALS,
  saveRiskSettings,
  USE_DEMO_DATA,
} from '@/services';
import { DashboardContext } from './dashboardContext';
import type { DashboardState } from './dashboardContext';

const MAX_ERRORS = 12;

const INITIAL_CONNECTION: ConnectionStatus = {
  services: [
    { id: 'backend', label: 'Backend API', state: 'checking', detail: 'Checking…', latencyMs: null, lastCheckedAt: new Date().toISOString() },
    { id: 'mt5-bridge', label: 'MT5 Bridge', state: 'checking', detail: 'Checking…', latencyMs: null, lastCheckedAt: new Date().toISOString() },
    { id: 'ai', label: 'AI Analyst', state: 'checking', detail: 'Checking…', latencyMs: null, lastCheckedAt: new Date().toISOString() },
  ],
  lastMarketDataAt: null,
  errors: [],
};

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [timeframe, setTimeframe] = useState<Timeframe>('15m');
  const [quote, setQuote] = useState<Quote | null>(null);
  // Loading flags are derived from which slice is currently held rather than
  // set inside the effects, which keeps renders from cascading.
  const [candleState, setCandleState] = useState<{ timeframe: Timeframe | null; data: Candle[] }>({
    timeframe: null,
    data: [],
  });
  const [analysisState, setAnalysisState] = useState<{ key: string | null; data: AiAnalysis | null }>({
    key: null,
    data: null,
  });
  const [account, setAccount] = useState<AccountSnapshot | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [history, setHistory] = useState<HistoryTrade[]>([]);
  const [riskSettings, setRiskSettings] = useState<RiskSettings | null>(null);
  const [connection, setConnection] = useState<ConnectionStatus>(INITIAL_CONNECTION);
  const [lastMarketDataAt, setLastMarketDataAt] = useState<string | null>(null);
  const [errors, setErrors] = useState<DashboardState['errors']>([]);
  const [analysisNonce, setAnalysisNonce] = useState(0);

  const lastMarketDataRef = useRef<string | null>(null);

  const reportError = useCallback((service: string, error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    setErrors((prev) =>
      [{ at: new Date().toISOString(), service, message }, ...prev].slice(0, MAX_ERRORS),
    );
  }, []);

  // --- Quote -------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const run = async () => {
      try {
        const result = await fetchQuote(undefined, controller.signal);
        if (cancelled) return;
        setQuote(result.data);
        lastMarketDataRef.current = result.receivedAt;
        setLastMarketDataAt(result.receivedAt);
      } catch (error) {
        if (!cancelled) reportError('market/quote', error);
      }
    };

    void run();
    const id = window.setInterval(run, POLL_INTERVALS.quote);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [reportError]);

  // --- Candles -----------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const run = async () => {
      try {
        const result = await fetchCandles(timeframe, undefined, undefined, controller.signal);
        if (cancelled) return;
        setCandleState({ timeframe, data: result.data });
      } catch (error) {
        if (!cancelled) reportError('market/candles', error);
      }
    };

    void run();
    const id = window.setInterval(run, POLL_INTERVALS.candles);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [timeframe, reportError]);

  // --- AI analysis -------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const run = async () => {
      try {
        const result = await fetchAnalysis(timeframe, undefined, controller.signal);
        if (cancelled) return;
        setAnalysisState({ key: `${timeframe}:${analysisNonce}`, data: result.data });
      } catch (error) {
        if (!cancelled) reportError('ai/analysis', error);
      }
    };

    void run();
    const id = window.setInterval(run, POLL_INTERVALS.analysis);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [timeframe, analysisNonce, reportError]);

  // --- Account + positions ----------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const run = async () => {
      try {
        const [accountResult, positionsResult] = await Promise.all([
          fetchAccount(controller.signal),
          fetchPositions(controller.signal),
        ]);
        if (cancelled) return;
        setAccount(accountResult.data);
        setPositions(positionsResult.data);
      } catch (error) {
        if (!cancelled) reportError('account', error);
      }
    };

    void run();
    const id = window.setInterval(run, POLL_INTERVALS.account);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, [reportError]);

  // --- History + risk settings (fetched once) ----------------------------
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    void (async () => {
      try {
        const [historyResult, riskResult] = await Promise.all([
          fetchHistory(50, controller.signal),
          fetchRiskSettings(controller.signal),
        ]);
        if (cancelled) return;
        setHistory(historyResult.data);
        setRiskSettings(riskResult.data);
      } catch (error) {
        if (!cancelled) reportError('history/risk', error);
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [reportError]);

  // --- Connection health -------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const run = async () => {
      const status = await fetchConnectionStatus(lastMarketDataRef.current, controller.signal);
      if (!cancelled) setConnection(status);
    };

    void run();
    const id = window.setInterval(run, POLL_INTERVALS.health);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(id);
    };
  }, []);

  const updateRiskSettings = useCallback(
    async (patch: Partial<RiskSettings>) => {
      try {
        const result = await saveRiskSettings(patch);
        setRiskSettings(result.data);
      } catch (error) {
        reportError('risk/settings', error);
      }
    },
    [reportError],
  );

  const refreshAnalysis = useCallback(() => setAnalysisNonce((n) => n + 1), []);

  const candles = candleState.data;
  const candlesLoading = candleState.timeframe !== timeframe;
  const analysis = analysisState.data;
  const analysisLoading = analysisState.key !== `${timeframe}:${analysisNonce}`;

  const riskUsage = useMemo<RiskUsage | null>(
    () => (account && riskSettings ? deriveRiskUsage(account, positions, riskSettings) : null),
    [account, positions, riskSettings],
  );

  const source: DataSource = USE_DEMO_DATA ? 'demo' : 'live';

  const value = useMemo<DashboardState>(
    () => ({
      source,
      timeframe,
      setTimeframe,
      quote,
      candles,
      candlesLoading,
      analysis,
      analysisLoading,
      refreshAnalysis,
      account,
      positions,
      history,
      riskSettings,
      riskUsage,
      updateRiskSettings,
      connection,
      lastMarketDataAt,
      errors: [...errors, ...connection.errors].slice(0, MAX_ERRORS),
    }),
    [
      source,
      timeframe,
      quote,
      candles,
      candlesLoading,
      analysis,
      analysisLoading,
      refreshAnalysis,
      account,
      positions,
      history,
      riskSettings,
      riskUsage,
      updateRiskSettings,
      connection,
      lastMarketDataAt,
      errors,
    ],
  );

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}
