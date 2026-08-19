import { Outlet } from 'react-router-dom';
import { Header } from './Header';
import { SafetyBanner } from './SafetyBanner';

export function AppShell() {
  return (
    <div className="min-h-screen">
      <Header />
      <SafetyBanner />
      <main className="mx-auto max-w-[1800px] px-3 py-4 sm:px-5 sm:py-6">
        <Outlet />
      </main>
      <footer className="mx-auto max-w-[1800px] px-3 pb-8 sm:px-5">
        <p className="border-t border-base-800 pt-4 text-[11px] leading-relaxed text-ink-500">
          Jamil AI Trading Dashboard · Demo build. Data flows Website → Backend API → MT5 Bridge →
          MetaTrader 5 → demo broker; the browser never connects to MetaTrader 5 directly. AI output
          is analysis of past price structure, not investment advice and not a guaranteed prediction.
        </p>
      </footer>
    </div>
  );
}
