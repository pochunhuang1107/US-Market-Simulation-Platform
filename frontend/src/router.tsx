import { Navigate, createBrowserRouter } from 'react-router-dom';

import { AppShell } from './components/layout/AppShell';
import { ComparePage } from './pages/ComparePage';
import { CreateSimulationPage } from './pages/CreateSimulationPage';
import { CreateStrategyPage } from './pages/CreateStrategyPage';
import { CreateStrategyVersionPage } from './pages/CreateStrategyVersionPage';
import { LandingPage } from './pages/LandingPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { RunsPage } from './pages/RunsPage';
import { StrategyBuilderPage } from './pages/StrategyBuilderPage';
import { StrategyChatPage } from './pages/StrategyChatPage';
import { StrategyGalleryPage } from './pages/StrategyGalleryPage';
import { StrategyLibraryPage } from './pages/StrategyLibraryPage';
import { StrategyPage } from './pages/StrategyPage';
import { SweepVariantDetailPage } from './pages/SweepVariantDetailPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <LandingPage />
  },
  {
    element: <AppShell />,
    children: [
      { path: '/workspace', element: <StrategyChatPage /> },
      { path: '/chat', element: <Navigate to="/workspace" replace /> },
      { path: '/runs', element: <RunsPage /> },
      { path: '/runs/new', element: <CreateSimulationPage /> },
      { path: '/runs/:runId', element: <RunDetailPage /> },
      { path: '/runs/:runId/variants/:variantId', element: <SweepVariantDetailPage /> },
      { path: '/compare', element: <ComparePage /> },
      { path: '/gallery', element: <StrategyGalleryPage /> },
      { path: '/strategy-builder', element: <StrategyBuilderPage /> },
      { path: '/strategies', element: <StrategyLibraryPage /> },
      { path: '/strategies/new', element: <CreateStrategyPage /> },
      { path: '/strategies/:strategyId/versions/new', element: <CreateStrategyVersionPage /> },
      { path: '/strategies/:strategyId', element: <StrategyPage /> }
    ]
  }
]);
