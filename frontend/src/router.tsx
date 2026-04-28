import { createBrowserRouter } from 'react-router-dom';

import { AppShell } from './components/layout/AppShell';
import { ComparePage } from './pages/ComparePage';
import { CreateSimulationPage } from './pages/CreateSimulationPage';
import { CreateStrategyPage } from './pages/CreateStrategyPage';
import { CreateStrategyVersionPage } from './pages/CreateStrategyVersionPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { RunsPage } from './pages/RunsPage';
import { StrategyBuilderPage } from './pages/StrategyBuilderPage';
import { StrategyChatPage } from './pages/StrategyChatPage';
import { StrategyLibraryPage } from './pages/StrategyLibraryPage';
import { StrategyPage } from './pages/StrategyPage';
import { SweepVariantDetailPage } from './pages/SweepVariantDetailPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <StrategyChatPage /> },
      { path: '/chat', element: <StrategyChatPage /> },
      { path: '/runs', element: <RunsPage /> },
      { path: '/runs/new', element: <CreateSimulationPage /> },
      { path: '/runs/:runId', element: <RunDetailPage /> },
      { path: '/runs/:runId/variants/:variantId', element: <SweepVariantDetailPage /> },
      { path: '/compare', element: <ComparePage /> },
      { path: '/strategy-builder', element: <StrategyBuilderPage /> },
      { path: '/strategies', element: <StrategyLibraryPage /> },
      { path: '/strategies/new', element: <CreateStrategyPage /> },
      { path: '/strategies/:strategyId/versions/new', element: <CreateStrategyVersionPage /> },
      { path: '/strategies/:strategyId', element: <StrategyPage /> }
    ]
  }
]);
