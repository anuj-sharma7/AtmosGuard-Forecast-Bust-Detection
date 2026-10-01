import { Route, Routes } from 'react-router-dom';

import { AtmosGuardHeader } from './components/AtmosGuardHeader';
import { Disclaimer } from './components/Disclaimer';
import { AboutPage } from './pages/AboutPage';
import { AlertsPage } from './pages/AlertsPage';
import { Dashboard } from './pages/Dashboard';
import { ForecastAnalysis } from './pages/ForecastAnalysis';
import { RiskMapPage } from './pages/RiskMapPage';
import { SystemPage } from './pages/SystemPage';
import { HistoricalReplayPage } from './pages/HistoricalReplayPage';
import { VerificationPage } from './pages/VerificationPage';
import { WarningPage } from './pages/WarningPage';
import { useAppState } from './state/AppState';

export default function App() {
  const { meta } = useAppState();

  return (
    <div className="flex min-h-full flex-col">
      <AtmosGuardHeader />
      <main className="mx-auto w-full max-w-[1800px] flex-1 px-4 py-4">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/analysis" element={<ForecastAnalysis />} />
          <Route path="/map" element={<RiskMapPage />} />
          <Route path="/warnings" element={<WarningPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/verification" element={<VerificationPage />} />
          <Route path="/replay" element={<HistoricalReplayPage />} />
          <Route path="/system" element={<SystemPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
      <Disclaimer text={meta.data?.disclaimer} />
    </div>
  );
}
