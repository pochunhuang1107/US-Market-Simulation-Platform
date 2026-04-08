import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { PaginationBar } from '../components/runs/PaginationBar';
import { RunFilters } from '../components/runs/RunFilters';
import { RunsTable } from '../components/runs/RunsTable';
import { PageHeader } from '../components/shared/PageHeader';
import { StateCard } from '../components/shared/StateCard';
import { fetchRunsDashboard, fetchStrategies } from '../lib/api';
import type { RunDashboardListResponse, RunSortBy, RunSortOrder, StrategyListItem } from '../types/api';

const DEFAULT_PAGE_SIZE = 20;

export function RunsPage() {
  const [runsResponse, setRunsResponse] = useState<RunDashboardListResponse | null>(null);
  const [strategies, setStrategies] = useState<StrategyListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [status, setStatus] = useState('');
  const [strategyId, setStrategyId] = useState('');
  const [sortBy, setSortBy] = useState<RunSortBy>('created_at');
  const [sortOrder, setSortOrder] = useState<RunSortOrder>('desc');
  const [page, setPage] = useState(1);

  useEffect(() => {
    void fetchStrategies().then(setStrategies).catch(() => setStrategies([]));
  }, []);

  useEffect(() => {
    let ignore = false;

    async function loadRuns() {
      setLoading(true);
      setErrorMessage(null);

      try {
        const response = await fetchRunsDashboard({
          status: status || undefined,
          strategy_id: strategyId || undefined,
          page,
          page_size: DEFAULT_PAGE_SIZE,
          sort_by: sortBy,
          sort_order: sortOrder
        });

        if (!ignore) {
          setRunsResponse(response);
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load runs dashboard');
          setRunsResponse(null);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    void loadRuns();
    return () => {
      ignore = true;
    };
  }, [status, strategyId, page, sortBy, sortOrder]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Runs"
        title="Run Monitor"
        description="Browse simulation runs with dashboard-aware filters, sorting, and pagination. This page stays aligned to GET /runs/dashboard without modifying backend response shapes."
        actions={
          <Link
            to="/runs/new"
            className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
          >
            Create simulation
          </Link>
        }
      />

      <RunFilters
        status={status}
        strategyId={strategyId}
        sortBy={sortBy}
        sortOrder={sortOrder}
        strategies={strategies}
        onStatusChange={(value) => {
          setStatus(value);
          setPage(1);
        }}
        onStrategyChange={(value) => {
          setStrategyId(value);
          setPage(1);
        }}
        onSortByChange={(value) => {
          setSortBy(value);
          setPage(1);
        }}
        onSortOrderChange={(value) => {
          setSortOrder(value);
          setPage(1);
        }}
      />

      {errorMessage ? <StateCard title="Failed to load runs" description={errorMessage} tone="error" /> : null}

      <RunsTable runs={runsResponse?.items ?? []} loading={loading} />

      <PaginationBar
        page={runsResponse?.page ?? page}
        pageSize={runsResponse?.page_size ?? DEFAULT_PAGE_SIZE}
        total={runsResponse?.total ?? 0}
        hasNext={runsResponse?.has_next ?? false}
        onPageChange={setPage}
      />
    </div>
  );
}
