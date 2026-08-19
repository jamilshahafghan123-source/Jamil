import { Database, Server, ShieldAlert } from 'lucide-react';
import { useDashboard } from '@/context/dashboardContext';
import { PageHeading } from '@/components/layout/PageHeading';
import { RiskPanel } from '@/components/risk/RiskPanel';
import { ConnectionPanel } from '@/components/status/ConnectionPanel';
import { Badge, DataSourceTag, Panel, Stat } from '@/components/ui';
import { API_BASE_URL, API_ENDPOINTS, TRADING_ENABLED, USE_DEMO_DATA } from '@/services';

const PIPELINE = [
  { label: 'Website', detail: 'React dashboard (this app)' },
  { label: 'Backend API', detail: 'Owns auth, risk, AI and data caching' },
  { label: 'MT5 Bridge', detail: 'Windows host running the MetaTrader 5 Python API' },
  { label: 'MetaTrader 5', detail: 'Terminal logged in to the demo account' },
  { label: 'Demo broker', detail: 'Simulated fills only' },
];

export function SettingsPage() {
  const {
    source,
    riskSettings,
    riskUsage,
    account,
    updateRiskSettings,
    connection,
    lastMarketDataAt,
    errors,
  } = useDashboard();

  return (
    <>
      <PageHeading
        title="Settings"
        description="Data source, risk limits and the connection chain to MetaTrader 5."
        actions={<DataSourceTag source={source} />}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="xl:col-span-7">
          <Panel
            icon={<Database className="h-4.5 w-4.5" />}
            title="Data source"
            subtitle="Configured through environment variables"
            actions={<Badge tone={USE_DEMO_DATA ? 'warn' : 'bull'}>{USE_DEMO_DATA ? 'Demo' : 'Live'}</Badge>}
          >
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
                <Stat
                  label="VITE_API_BASE_URL"
                  value={API_BASE_URL || 'not set'}
                  size="sm"
                  tone={API_BASE_URL ? 'default' : 'muted'}
                />
              </div>
              <div className="rounded-lg border border-base-700 bg-base-900/50 px-3 py-2.5">
                <Stat
                  label="Trading enabled"
                  value={TRADING_ENABLED ? 'true' : 'false'}
                  size="sm"
                  tone={TRADING_ENABLED ? 'bear' : 'bull'}
                />
              </div>
            </div>

            <p className="mt-3 text-xs leading-relaxed text-ink-400">
              With no backend URL configured the dashboard runs entirely on locally generated demo
              data. Set <code className="num text-gold-300">VITE_API_BASE_URL</code> and{' '}
              <code className="num text-gold-300">VITE_FORCE_DEMO_DATA=false</code> to switch the
              service layer over to the real Backend API — no component changes are required.
            </p>

            <div className="mt-4">
              <div className="text-[11px] font-medium tracking-wider text-ink-400 uppercase">
                Endpoints the service layer calls
              </div>
              <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
                {Object.entries(API_ENDPOINTS).map(([name, path]) => (
                  <li
                    key={name}
                    className="num flex items-center justify-between gap-2 rounded-md border border-base-700 bg-base-900/50 px-2.5 py-1.5 text-[11px]"
                  >
                    <span className="text-ink-500">{name}</span>
                    <span className="truncate text-ink-200">{path}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Panel>
        </div>

        <div className="xl:col-span-5">
          <Panel
            icon={<Server className="h-4.5 w-4.5" />}
            title="Architecture"
            subtitle="The browser never talks to MetaTrader 5"
          >
            <ol className="space-y-2">
              {PIPELINE.map((step, index) => (
                <li key={step.label} className="flex items-start gap-3">
                  <span className="num mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md bg-base-800 text-[11px] font-bold text-gold-300">
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1 border-b border-base-800 pb-2 last:border-0">
                    <div className="text-sm font-semibold text-ink-100">{step.label}</div>
                    <div className="text-[11px] text-ink-400">{step.detail}</div>
                  </div>
                </li>
              ))}
            </ol>
          </Panel>
        </div>

        <div className="xl:col-span-12">
          <Panel
            icon={<ShieldAlert className="h-4.5 w-4.5" />}
            title="Safety policy"
            subtitle="Applies for the whole demo phase"
          >
            <ul className="grid gap-2.5 text-xs leading-relaxed text-ink-300 sm:grid-cols-2">
              <li className="rounded-lg border border-base-700 bg-base-900/50 px-3.5 py-3">
                <span className="font-semibold text-ink-100">No real-money trading.</span> There is
                no code path in this build that can place a live order. The switch is present only to
                display its state.
              </li>
              <li className="rounded-lg border border-base-700 bg-base-900/50 px-3.5 py-3">
                <span className="font-semibold text-ink-100">No automatic execution.</span> The AI
                panel produces analysis for a human to read. Nothing acts on it.
              </li>
              <li className="rounded-lg border border-base-700 bg-base-900/50 px-3.5 py-3">
                <span className="font-semibold text-ink-100">Demo account only.</span> When the
                bridge is connected it must be pointed at a demo login, and the backend must reject
                any live account.
              </li>
              <li className="rounded-lg border border-base-700 bg-base-900/50 px-3.5 py-3">
                <span className="font-semibold text-ink-100">Data is labelled.</span> Every panel
                shows whether its numbers came from the demo generator or a live backend.
              </li>
            </ul>
          </Panel>
        </div>

        <div className="xl:col-span-7">
          <RiskPanel
            settings={riskSettings}
            usage={riskUsage}
            account={account}
            source={source}
            onChange={(patch) => void updateRiskSettings(patch)}
          />
        </div>
        <div className="xl:col-span-5">
          <ConnectionPanel
            connection={connection}
            lastMarketDataAt={lastMarketDataAt}
            errors={errors}
          />
        </div>
      </div>
    </>
  );
}
