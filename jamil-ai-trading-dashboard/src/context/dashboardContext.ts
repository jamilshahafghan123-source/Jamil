import { createContext, useContext } from 'react';
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

export interface DashboardState {
  /** Where the currently displayed data came from. Always surfaced in the UI. */
  source: DataSource;
  timeframe: Timeframe;
  setTimeframe: (timeframe: Timeframe) => void;

  quote: Quote | null;
  candles: Candle[];
  candlesLoading: boolean;

  analysis: AiAnalysis | null;
  analysisLoading: boolean;
  refreshAnalysis: () => void;

  account: AccountSnapshot | null;
  positions: Position[];
  history: HistoryTrade[];

  riskSettings: RiskSettings | null;
  riskUsage: RiskUsage | null;
  updateRiskSettings: (patch: Partial<RiskSettings>) => Promise<void>;

  connection: ConnectionStatus;
  lastMarketDataAt: string | null;
  /** Errors raised by the data layer, newest first. */
  errors: { at: string; service: string; message: string }[];
}

export const DashboardContext = createContext<DashboardState | null>(null);

export function useDashboard(): DashboardState {
  const value = useContext(DashboardContext);
  if (!value) throw new Error('useDashboard must be used inside <DashboardProvider>');
  return value;
}
