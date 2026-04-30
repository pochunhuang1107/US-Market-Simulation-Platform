import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { PaginationBar } from '../components/runs/PaginationBar';
import { RunFilters } from '../components/runs/RunFilters';
import { RunsTable } from '../components/runs/RunsTable';
import { PageHeader } from '../components/shared/PageHeader';
import { StateCard } from '../components/shared/StateCard';
import { fetchRunsDashboard, fetchStrategies } from '../lib/api';
import type { RunDashboardListResponse, RunSortBy, RunSortOrder, StrategyListItem } from '../types/api';

const DEFAULT_PAGE_SIZE = 20;
const ACTIVE_RUN_STATUSES = ['PENDING', 'QUEUED', 'LEASED', 'RUNNING'];
const ACTIVE_RUN_STATUS_SET = new Set(ACTIVE_RUN_STATUSES);
const UNSUCCESSFUL_RUN_STATUSES = new Set(['FAILED', 'CANCELED']);

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
  const summary = useMemo(() => {
    const items = runsResponse?.items ?? [];

    return {
      total: items.length,
      succeeded: items.filter((run) => run.status === 'SUCCEEDED').length,
      active: items.filter((run) => ACTIVE_RUN_STATUS_SET.has(run.status)).length,
      unsuccessful: items.filter((run) => UNSUCCESSFUL_RUN_STATUSES.has(run.status)).length
    };
  }, [runsResponse?.items]);

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
          status: getStatusQuery(status),
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
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load research results');
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
        eyebrow="Results"
        title="Research Results"
        description="Review recorded simulation, sweep, and experiment outputs, then choose candidates for comparison."
        actions={
          <Link
            to="/runs/new"
            className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition"
          >
            Advanced manual run
          </Link>
        }
      />

      {runsResponse ? (
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Result inventory summary">
          <SummaryCard label="Visible results" value={summary.total} detail="Current page" />
          <SummaryCard label="Completed results" value={summary.succeeded} detail="Ready to reopen" tone="success" />
          <SummaryCard label="Active" value={summary.active} detail="In progress" tone="active" />
          <SummaryCard label="Failed / canceled" value={summary.unsuccessful} detail="Needs review" tone="danger" />
        </section>
      ) : null}

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

      {errorMessage ? <StateCard title="Failed to load results" description={errorMessage} tone="error" /> : null}

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

function getStatusQuery(status: string): string | string[] | undefined {
  if (!status) return undefined;
  if (status === 'ACTIVE') return ACTIVE_RUN_STATUSES;
  return status;
}

function SummaryCard({
  label,
  value,
  detail,
  tone = 'neutral'
}: {
  label: string;
  value: number;
  detail: string;
  tone?: 'neutral' | 'success' | 'active' | 'danger';
}) {
  const toneClass =
    tone === 'success'
      ? 'text-emerald-300'
      : tone === 'active'
        ? 'app-accent'
        : tone === 'danger'
          ? 'text-rose-300'
          : 'app-title';

  return (
    <div className="app-card rounded-2xl border px-4 py-3">
      <p className="app-text-soft text-xs font-semibold uppercase tracking-[0.16em]">{label}</p>
      <div className="mt-2 flex items-end justify-between gap-3">
        <p className={`text-2xl font-semibold ${toneClass}`}>{value}</p>
        <p className="app-text-muted pb-1 text-xs">{detail}</p>
      </div>
    </div>
  );
}
