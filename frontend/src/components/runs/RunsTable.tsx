import { Link } from 'react-router-dom';

import {
  formatDateTime,
  formatExecutorType,
  formatNumber,
  formatPct,
  formatRunLabel,
  formatRunType,
  formatSavedSweepVariantSource,
  isSavedSweepVariantResult,
  shortRunId
} from '../../lib/formatters';
import type { RunDashboardListItem } from '../../types/api';
import { RunStatusBadge } from './RunStatusBadge';

const ACTIVE_PROGRESS_STATUSES = new Set(['PENDING', 'QUEUED', 'LEASED', 'RUNNING']);

interface RunsTableProps {
  runs: RunDashboardListItem[];
  loading: boolean;
  compact?: boolean;
  referenceRunId?: string | null;
  emptyTitle?: string;
  emptyDescription?: string;
}

export function RunsTable({
  runs,
  loading,
  compact = false,
  referenceRunId = null,
  emptyTitle = 'No results match these filters.',
  emptyDescription = 'Try clearing filters or start from the Home builder.'
}: RunsTableProps) {
  const columns = compact ? 7 : 9;

  return (
    <div className="app-table app-shadow overflow-hidden rounded-3xl border">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y app-divider text-sm">
          <thead className="app-table-head">
            <tr className="text-left text-xs font-semibold uppercase tracking-[0.18em]">
              <HeaderCell>Result</HeaderCell>
              <HeaderCell>Status</HeaderCell>
              <HeaderCell>Created</HeaderCell>
              <HeaderCell>Finished</HeaderCell>
              <HeaderCell>Total Return</HeaderCell>
              <HeaderCell>CAGR</HeaderCell>
              {!compact ? <HeaderCell>Max Drawdown</HeaderCell> : null}
              {!compact ? <HeaderCell>Trades</HeaderCell> : null}
              <HeaderCell>Progress</HeaderCell>
            </tr>
          </thead>
          <tbody className="divide-y app-divider">
            {loading ? (
              <tr>
                <td colSpan={columns} className="px-5 py-16 text-center app-text-muted">
                  Loading results…
                </td>
              </tr>
            ) : runs.length === 0 ? (
              <tr>
                <td colSpan={columns} className="px-5 py-16 text-center">
                  <div className="mx-auto max-w-sm">
                    <p className="app-title text-sm font-semibold">{emptyTitle}</p>
                    <p className="app-text-muted mt-2 text-sm">{emptyDescription}</p>
                    {!compact ? (
                      <Link to="/" className="app-button-secondary mt-4 inline-flex rounded-xl px-3 py-1.5 text-xs font-medium">
                        Build a strategy
                      </Link>
                    ) : null}
                  </div>
                </td>
              </tr>
            ) : (
              runs.map((run) => {
                const progress = getProgressDisplay(run);
                const isSavedSweepVariant = isSavedSweepVariantResult(run);
                const isReferenceRun = referenceRunId === run.run_id;

                return (
                  <tr key={run.run_id} className="app-row-hover align-top transition">
                    <td className="px-5 py-4">
                      <div className="max-w-[280px]">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link to={`/runs/${run.run_id}`} className="font-semibold app-title transition hover:text-cyan-400">
                            {formatRunLabel(run.strategy_name, run.strategy_version_number)}
                          </Link>
                          {isSavedSweepVariant ? (
                            <span className="app-badge rounded-full px-2 py-0.5 text-[10px] font-semibold">
                              Saved sweep variant
                            </span>
                          ) : null}
                          {isReferenceRun ? (
                            <span className="app-chip-info rounded-full px-2 py-0.5 text-[10px] font-semibold">
                              Reference
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-2 text-xs app-text-soft">
                          {isSavedSweepVariant ? (
                            <span>{formatSavedSweepVariantSource(run)}</span>
                          ) : (
                            <>
                              <span>{formatRunType(run.run_type)}</span>
                              <span className="mx-1.5">·</span>
                              <span className="app-text-muted">{formatExecutorType(run.executor_type)}</span>
                            </>
                          )}
                        </p>
                        <p className="mt-1 font-mono text-[11px] app-text-muted" title={run.run_id}>
                          ID {shortRunId(run.run_id)}
                        </p>
                        {run.strategy_id ? (
                          <p className="mt-1 text-xs app-text-muted">
                            Strategy:{' '}
                            <Link to={`/strategies/${run.strategy_id}`} className="font-semibold transition hover:text-cyan-400">
                              {run.strategy_name ?? 'Open strategy'}
                            </Link>
                            {run.strategy_version_number ? (
                              <span className="app-text-soft"> · v{run.strategy_version_number}</span>
                            ) : null}
                          </p>
                        ) : null}
                        <div className="mt-3 flex items-center gap-2">
                          <Link
                            to={`/runs/${run.run_id}`}
                            className="app-button-secondary inline-flex items-center rounded-xl px-3 py-1.5 text-xs font-semibold whitespace-nowrap"
                          >
                            Open result
                          </Link>
                          {!compact && run.status === 'SUCCEEDED' ? (
                            <Link
                              to={`/compare?runIds=${run.run_id}`}
                              className="inline-flex items-center rounded-xl border app-border-soft px-3 py-1.5 text-xs font-semibold app-text-soft transition hover:border-cyan-400/50 hover:text-cyan-500 dark:hover:text-cyan-300 whitespace-nowrap"
                            >
                              Compare
                            </Link>
                          ) : null}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <RunStatusBadge status={run.status} />
                    </td>
                    <td className="px-5 py-4 app-text-muted">{formatDateTime(run.created_at)}</td>
                    <td className="px-5 py-4 app-text-muted">{formatDateTime(run.finished_at)}</td>
                    <td className="px-5 py-4 font-medium app-title">{formatPct(run.total_return_pct)}</td>
                    <td className="px-5 py-4 app-text-muted">{formatPct(run.cagr_pct)}</td>
                    {!compact ? <td className="px-5 py-4 app-text-muted">{formatPct(run.max_drawdown_pct)}</td> : null}
                    {!compact ? <td className="px-5 py-4 app-text-muted">{formatNumber(run.trade_count)}</td> : null}
                    <td className="px-5 py-4 pr-6">
                      <div className="w-full min-w-[150px] max-w-[220px]">
                        <div className={`flex items-center justify-between gap-3 text-xs ${progress.textClass}`}>
                          {progress.badgeClass ? (
                            <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold ${progress.badgeClass}`}>
                              {progress.label}
                            </span>
                          ) : (
                            <span className="truncate">{progress.label}</span>
                          )}
                          {progress.showPercent ? <span className="shrink-0">{progress.percentLabel}</span> : null}
                        </div>
                        {progress.showBar ? (
                          <div className="mt-2 h-2 w-full overflow-hidden rounded-full app-surface-soft">
                            <div
                              className={`h-2 rounded-full transition-all ${progress.barClass}`}
                              style={{ width: `${progress.barPct}%` }}
                            />
                          </div>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HeaderCell({ children }: { children: React.ReactNode }) {
  return <th className="px-5 py-4">{children}</th>;
}

function getProgressDisplay(run: RunDashboardListItem) {
  const status = run.status.toUpperCase();
  const pct = Math.max(0, Math.min(run.progress_pct, 100));

  if (status === 'SUCCEEDED') {
    return {
      label: 'Completed',
      showPercent: false,
      showBar: false,
      percentLabel: null,
      barPct: 0,
      textClass: 'app-text-soft',
      barClass: '',
      badgeClass: 'app-chip-success'
    };
  }

  if (status === 'FAILED' || status === 'CANCELED' || status === 'CANCELLED') {
    return {
      label: status === 'FAILED' ? 'Stopped before completion' : 'Canceled',
      showPercent: false,
      showBar: false,
      percentLabel: null,
      barPct: pct,
      textClass: 'app-text-muted',
      barClass: '',
      badgeClass: null
    };
  }

  if (!ACTIVE_PROGRESS_STATUSES.has(status)) {
    return {
      label: run.progress_message ?? status,
      showPercent: false,
      showBar: false,
      percentLabel: null,
      barPct: pct,
      textClass: 'app-text-muted',
      barClass: '',
      badgeClass: null
    };
  }

  return {
    label: run.progress_message ?? 'Waiting to start',
    showPercent: true,
    showBar: true,
    percentLabel: `${pct}%`,
    barPct: pct,
    textClass: 'app-text-muted',
    barClass: 'bg-cyan-400',
    badgeClass: null
  };
}
