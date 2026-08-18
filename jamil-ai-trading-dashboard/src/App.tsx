import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { DashboardProvider } from '@/context/DashboardProvider';
import { AppShell } from '@/components/layout/AppShell';
import { DashboardPage } from '@/pages/DashboardPage';
import { MarketsPage } from '@/pages/MarketsPage';
import { AiAnalystPage } from '@/pages/AiAnalystPage';
import { PositionsPage } from '@/pages/PositionsPage';
import { HistoryPage } from '@/pages/HistoryPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

export default function App() {
  return (
    <BrowserRouter>
      <DashboardProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="markets" element={<MarketsPage />} />
            <Route path="ai-analyst" element={<AiAnalystPage />} />
            <Route path="positions" element={<PositionsPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </DashboardProvider>
    </BrowserRouter>
  );
}
