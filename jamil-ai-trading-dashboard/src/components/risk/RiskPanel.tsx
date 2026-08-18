import { AlertTriangle, CheckCircle2, ShieldCheck } from 'lucide-react';
import type { AccountSnapshot, DataSource, RiskSettings, RiskUsage } from '@/types';
import {
  Badge,
  DataSourceTag,
  Meter,
  Panel,
  RangeField,
  SkeletonRows,
  Stat,
  Toggle,
} from '@/components/ui';
import { cn } from '@/lib/cn';
import { clamp, formatMoney } from '@/lib/format';

export function RiskPanel({
  settings,
  usage,
  account,
  source,
  onChange,
  editable = true,
}: {
  settings: RiskSettings | null;
  usage: RiskUsage | null;
  account: AccountSnapshot | null;
  source: DataSource;
  onChange: (patch: Partial<RiskSettings>) => void;
  editable?: boolean;
}) {
  if (!settings) {
    return (
      <Panel icon={<ShieldCheck className="h-4.5 w-4.5" />} title="Risk management">
        <SkeletonRows rows={5} />
      </Panel>
    );
  }

  const equity = account?.equity ?? 0;
  const riskPerTradeMoney = (equity * settings.riskPerTradePercent) / 100;
  const dailyLossPct = usage && usage.dailyLossLimit > 0
    ? clamp((usage.dailyLossUsed / usage.dailyLossLimit) * 100, 0, 100)
    : 0;
  const positionsPct = usage
    ? clamp((usage.openPositions / settings.maxOpenPositions) * 100, 0, 100)
    : 0;
  const stopViolations = usage?.positionsWithoutStop ?? 0;

  return (
    <Panel
      icon={<ShieldCheck className="h-4.5 w-4.5" />}
      title="Risk management"
      subtitle="Limits applied before any order is accepted"
      actions={
        <>
          <Badge tone={settings.liveTradingEnabled ? 'bear' : 'bull'}>
            {settings.liveTradingEnabled ? 'Live enabled' : 'Live locked'}
          </Badge>
          <DataSourceTag source={source} />
        </>
      }
      footer={
        <span>
          The UI is not the safety boundary — the backend must enforce these limits independently
          before forwarding anything to the MT5 bridge.
        </span>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <RangeField
            label="Risk per trade"
            value={settings.riskPerTradePercent}
            min={0.1}
            max={5}
            step={0.1}
            unit="%"
            disabled={!editable}
            hint={`≈ ${formatMoney(riskPerTradeMoney)} of current equity`}
            onChange={(value) => onChange({ riskPerTradePercent: value })}
          />
          <RangeField
            label="Maximum daily loss"
            value={settings.maxDailyLossPercent}
            min={0.5}
            max={10}
            step={0.5}
            unit="%"
            disabled={!editable}
            hint={
              usage
                ? `${formatMoney(usage.dailyLossUsed)} used of ${formatMoney(usage.dailyLossLimit)}`
                : undefined
            }
            onChange={(value) => onChange({ maxDailyLossPercent: value })}
          />
          <RangeField
            label="Maximum open positions"
            value={settings.maxOpenPositions}
            min={1}
            max={20}
            step={1}
            disabled={!editable}
            hint={usage ? `${usage.openPositions} currently open` : undefined}
            onChange={(value) => onChange({ maxOpenPositions: value })}
          />
          <RangeField
            label="Maximum lot size"
            value={settings.maxLotSize}
            min={0.01}
            max={5}
            step={0.01}
            disabled={!editable}
            hint="Hard cap per single order"
            onChange={(value) => onChange({ maxLotSize: value })}
          />
        </div>

        <div className="space-y-3 rounded-lg border border-base-700 bg-base-900/50 p-3.5">
          <Toggle
            checked={settings.requireStopLoss}
            onChange={(checked) => onChange({ requireStopLoss: checked })}
            label="Require stop loss on every order"
            description="Orders without a protective stop are rejected before reaching the bridge."
            locked={!editable}
            lockReason="Managed by the backend risk engine."
          />
          <div className="border-t border-base-800 pt-3">
            <Toggle
              checked={settings.demoTradingEnabled}
              onChange={(checked) => onChange({ demoTradingEnabled: checked })}
              label="Demo trading (paper orders)"
              description="Sends simulated orders to the demo account once the bridge is connected."
              locked
              lockReason="Disabled until the MT5 bridge is connected and explicitly configured."
            />
          </div>
          <div className="border-t border-base-800 pt-3">
            <Toggle
              checked={settings.liveTradingEnabled}
              onChange={() => undefined}
              label="Real-money trading"
              locked
              lockReason="Not implemented in this build. There is no live-money order path in the code."
            />
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
            <Stat
              label="Daily loss budget"
              value={`${dailyLossPct.toFixed(0)}%`}
              size="sm"
              tone={dailyLossPct > 75 ? 'bear' : 'default'}
            />
            <Meter
              value={dailyLossPct}
              tone={dailyLossPct > 75 ? 'bear' : dailyLossPct > 40 ? 'warn' : 'bull'}
              className="mt-2"
            />
          </div>
          <div className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
            <Stat
              label="Position slots"
              value={`${usage?.openPositions ?? 0} / ${settings.maxOpenPositions}`}
              size="sm"
            />
            <Meter value={positionsPct} tone={positionsPct > 80 ? 'warn' : 'info'} className="mt-2" />
          </div>
          <div
            className={cn(
              'flex items-center gap-2.5 rounded-lg border px-3 py-2.5',
              stopViolations > 0
                ? 'border-warn-400/30 bg-warn-400/8'
                : 'border-bull-500/25 bg-bull-500/8',
            )}
          >
            {stopViolations > 0 ? (
              <AlertTriangle className="h-5 w-5 shrink-0 text-warn-400" />
            ) : (
              <CheckCircle2 className="h-5 w-5 shrink-0 text-bull-400" />
            )}
            <div>
              <div className="text-[11px] font-medium tracking-wider text-ink-400 uppercase">
                Stop-loss compliance
              </div>
              <div
                className={cn(
                  'text-sm font-semibold',
                  stopViolations > 0 ? 'text-warn-400' : 'text-bull-400',
                )}
              >
                {stopViolations > 0
                  ? `${stopViolations} position${stopViolations === 1 ? '' : 's'} unprotected`
                  : 'All positions protected'}
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-start gap-2.5 rounded-lg border border-bull-500/25 bg-bull-500/8 px-3.5 py-3">
          <ShieldCheck className="mt-0.5 h-4.5 w-4.5 shrink-0 text-bull-400" />
          <div className="text-xs leading-relaxed text-ink-300">
            <span className="font-semibold text-bull-400">Demo trading status: disabled.</span> No
            order-sending code path exists in this build. Enabling any form of trading requires an
            explicit, reviewed configuration change on both the frontend and the backend.
          </div>
        </div>
      </div>
    </Panel>
  );
}
