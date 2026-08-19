import { useState } from 'react';
import { BarChart3, Crosshair, Maximize2, Target } from 'lucide-react';
import type { AiAnalysis, Candle, DataSource, Timeframe } from '@/types';
import { DataSourceTag, Panel, Segmented, Skeleton } from '@/components/ui';
import { TIMEFRAMES } from '@/demo/timeframes';
import { cn } from '@/lib/cn';
import { formatPrice, formatVolume } from '@/lib/format';
import { CandleChart } from './CandleChart';

interface ChartPanelProps {
  candles: Candle[];
  loading: boolean;
  timeframe: Timeframe;
  onTimeframeChange: (timeframe: Timeframe) => void;
  analysis: AiAnalysis | null;
  source: DataSource;
  height?: number;
}

function ToolButton({
  active,
  onClick,
  label,
  children,
}: {
  active?: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={cn(
        'grid h-7 w-7 place-items-center rounded-md border transition-colors',
        active
          ? 'border-gold-400/30 bg-gold-400/12 text-gold-300'
          : 'border-base-700 bg-base-900/70 text-ink-400 hover:text-ink-200',
      )}
    >
      {children}
    </button>
  );
}

export function ChartPanel({
  candles,
  loading,
  timeframe,
  onTimeframeChange,
  analysis,
  source,
  height = 460,
}: ChartPanelProps) {
  const [showVolume, setShowVolume] = useState(true);
  const [showLevels, setShowLevels] = useState(true);
  const [fitSignal, setFitSignal] = useState(0);

  const last = candles[candles.length - 1];
  const previous = candles[candles.length - 2];
  const up = last && previous ? last.close >= previous.close : true;

  return (
    <Panel
      icon={<Crosshair className="h-4.5 w-4.5" />}
      title="GOLD · XAUUSD chart"
      subtitle="Scroll to zoom · drag to pan · hover for crosshair"
      className="min-w-0"
      bodyClassName="p-0 sm:p-0"
      actions={
        <>
          <Segmented
            options={TIMEFRAMES.map((t) => ({ id: t.id, label: t.label }))}
            value={timeframe}
            onChange={onTimeframeChange}
            ariaLabel="Chart timeframe"
          />
          <div className="hidden items-center gap-1 sm:flex">
            <ToolButton active={showVolume} onClick={() => setShowVolume((v) => !v)} label="Toggle volume">
              <BarChart3 className="h-3.5 w-3.5" />
            </ToolButton>
            <ToolButton
              active={showLevels}
              onClick={() => setShowLevels((v) => !v)}
              label="Toggle AI levels"
            >
              <Target className="h-3.5 w-3.5" />
            </ToolButton>
            <ToolButton onClick={() => setFitSignal((n) => n + 1)} label="Reset zoom">
              <Maximize2 className="h-3.5 w-3.5" />
            </ToolButton>
          </div>
          <DataSourceTag source={source} />
        </>
      }
      footer={
        last ? (
          <div className="num flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
            <span>
              O <span className="text-ink-200">{formatPrice(last.open)}</span>
            </span>
            <span>
              H <span className="text-bull-400">{formatPrice(last.high)}</span>
            </span>
            <span>
              L <span className="text-bear-400">{formatPrice(last.low)}</span>
            </span>
            <span>
              C{' '}
              <span className={cn('font-semibold', up ? 'text-bull-400' : 'text-bear-400')}>
                {formatPrice(last.close)}
              </span>
            </span>
            <span>
              Vol <span className="text-ink-200">{formatVolume(last.volume)}</span>
            </span>
            <span className="text-ink-500">{candles.length} candles · {timeframe}</span>
          </div>
        ) : null
      }
    >
      {loading && candles.length === 0 ? (
        <div className="p-4 sm:p-5">
          <Skeleton className="w-full" />
          <div style={{ height }} className="mt-0 animate-pulse rounded-lg bg-base-750/50" />
        </div>
      ) : (
        <CandleChart
          candles={candles}
          analysis={analysis}
          showVolume={showVolume}
          showLevels={showLevels}
          fitSignal={fitSignal}
          height={height}
          className="w-full px-1 pt-2 pb-1"
        />
      )}
    </Panel>
  );
}
