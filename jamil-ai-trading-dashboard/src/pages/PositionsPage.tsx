import { useDashboard } from '@/context/dashboardContext';
import { PageHeading } from '@/components/layout/PageHeading';
import { PositionsTable } from '@/components/positions/PositionsTable';
import { AccountPanel } from '@/components/account/AccountPanel';
import { RiskPanel } from '@/components/risk/RiskPanel';
import { DataSourceTag } from '@/components/ui';

export function PositionsPage() {
  const { source, positions, account, riskSettings, riskUsage, updateRiskSettings } = useDashboard();

  return (
    <>
      <PageHeading
        title="Positions"
        description="Simulated exposure on the demo account. Order placement is disabled in this build."
        actions={<DataSourceTag source={source} />}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-12">
          <PositionsTable positions={positions} source={source} />
        </div>
        <div className="xl:col-span-5">
          <AccountPanel account={account} source={source} />
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
      </div>
    </>
  );
}
