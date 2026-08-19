import { useDashboard } from '@/context/dashboardContext';
import { PageHeading } from '@/components/layout/PageHeading';
import { AiAnalystPanel } from '@/components/ai/AiAnalystPanel';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { Badge, DataSourceTag, Panel } from '@/components/ui';

export function AiAnalystPage() {
  const {
    source,
    analysis,
    analysisLoading,
    refreshAnalysis,
    quote,
    candles,
    candlesLoading,
    timeframe,
    setTimeframe,
  } = useDashboard();

  return (
    <>
      <PageHeading
        title="AI Analyst"
        description="Structured read of GOLD price action. Output is analysis of historical structure, not a prediction and not investment advice."
        actions={
          <>
            <Badge tone="info">AI analysis</Badge>
            <DataSourceTag source={source} />
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <AiAnalystPanel
            analysis={analysis}
            loading={analysisLoading}
            source={source}
            onRefresh={refreshAnalysis}
            currentPrice={quote?.price ?? null}
          />
        </div>

        <div className="min-w-0 space-y-4 xl:col-span-5">
          <ChartPanel
            candles={candles}
            loading={candlesLoading}
            timeframe={timeframe}
            onTimeframeChange={setTimeframe}
            analysis={analysis}
            source={source}
            height={380}
          />
          <Panel title="How to read this panel">
            <ul className="space-y-2.5 text-xs leading-relaxed text-ink-300">
              <li>
                <span className="font-semibold text-ink-100">Bias</span> is the direction the model
                reads from moving-average structure and swing points. It is not a signal to trade.
              </li>
              <li>
                <span className="font-semibold text-ink-100">Confidence</span> is a self-reported
                score. A high number means the inputs agree with each other — not that the market
                will follow.
              </li>
              <li>
                <span className="font-semibold text-ink-100">Entry / stop / target</span> levels are
                an illustration of how the read could be expressed as a trade. Nothing is sent
                anywhere; there is no order path in this build.
              </li>
              <li>
                <span className="font-semibold text-ink-100">Risk / reward</span> assumes the second
                target and ignores spread, slippage, swap and news risk.
              </li>
            </ul>
          </Panel>
        </div>
      </div>
    </>
  );
}
