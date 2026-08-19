import { useDashboard } from '@/context/dashboardContext';
import { GoldMarketCard } from '@/components/market/GoldMarketCard';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { AiAnalystPanel } from '@/components/ai/AiAnalystPanel';
import { AccountPanel } from '@/components/account/AccountPanel';
import { PositionsTable } from '@/components/positions/PositionsTable';
import { RiskPanel } from '@/components/risk/RiskPanel';
import { ConnectionPanel } from '@/components/status/ConnectionPanel';

export function DashboardPage() {
  const {
    source,
    quote,
    candles,
    candlesLoading,
    timeframe,
    setTimeframe,
    analysis,
    analysisLoading,
    refreshAnalysis,
    account,
    positions,
    riskSettings,
    riskUsage,
    updateRiskSettings,
    connection,
    lastMarketDataAt,
    errors,
  } = useDashboard();

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
      <div className="xl:col-span-8">
        <GoldMarketCard quote={quote} source={source} lastUpdatedAt={lastMarketDataAt} />
      </div>
      <div className="xl:col-span-4">
        <AccountPanel account={account} source={source} />
      </div>

      {/* Chart and positions stack on the left so the tall AI panel on the
          right does not leave a void beneath the chart. */}
      <div className="grid min-w-0 grid-cols-1 content-start gap-4 xl:col-span-8">
        <ChartPanel
          candles={candles}
          loading={candlesLoading}
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
          analysis={analysis}
          source={source}
        />
        <PositionsTable positions={positions} source={source} />
        <RiskPanel
          settings={riskSettings}
          usage={riskUsage}
          account={account}
          source={source}
          onChange={(patch) => void updateRiskSettings(patch)}
        />
      </div>

      <div className="grid grid-cols-1 content-start gap-4 xl:col-span-4">
        <AiAnalystPanel
          analysis={analysis}
          loading={analysisLoading}
          source={source}
          onRefresh={refreshAnalysis}
          currentPrice={quote?.price ?? null}
        />
        <ConnectionPanel
          connection={connection}
          lastMarketDataAt={lastMarketDataAt}
          errors={errors}
        />
      </div>
    </div>
  );
}
