import { createBrowserRouter, Navigate } from 'react-router-dom';

import { AppShell } from './components/layout/AppShell';
import { ComparePage } from './pages/ComparePage';
import { CreateSimulationPage } from './pages/CreateSimulationPage';
import { CreateStrategyPage } from './pages/CreateStrategyPage';
import { CreateStrategyVersionPage } from './pages/CreateStrategyVersionPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { RunsPage } from './pages/RunsPage';
import { StrategyBuilderPage } from './pages/StrategyBuilderPage';
import { StrategyPage } from './pages/StrategyPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/runs" replace /> },
      { path: '/runs', element: <RunsPage /> },
      { path: '/runs/new', element: <CreateSimulationPage /> },
      { path: '/runs/:runId', element: <RunDetailPage /> },
      { path: '/compare', element: <ComparePage /> },
      { path: '/strategy-builder', element: <StrategyBuilderPage /> },
      { path: '/strategies/new', element: <CreateStrategyPage /> },
      { path: '/strategies/:strategyId/versions/new', element: <CreateStrategyVersionPage /> },
      { path: '/strategies/:strategyId', element: <StrategyPage /> }
    ]
  }
]);