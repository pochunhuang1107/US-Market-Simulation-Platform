import { Link } from 'react-router-dom';

import {
  formatDateTime,
  formatExecutorType,
  formatNumber,
  formatPct,
  formatRunLabel,
  formatRunType
} from '../../lib/formatters';
import type { RunDashboardListItem } from '../../types/api';
import { RunStatusBadge } from './RunStatusBadge';

interface RunsTableProps {
  runs: RunDashboardListItem[];
  loading: boolean;
  compact?: boolean;
}

export function RunsTable({ runs, loading, compact = false }: RunsTableProps) {
  const columns = compact ? 7 : 9;

  return (
    <div className="app-table app-shadow overflow-hidden rounded-3xl border">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y app-divider text-sm">
          <thead className="app-table-head">
            <tr className="text-left text-xs font-semibold uppercase tracking-[0.18em]">
              <HeaderCell>Run</HeaderCell>
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
                  Loading runs…
                </td>
              </tr>
            ) : runs.length === 0 ? (
              <tr>
                <td colSpan={columns} className="px-5 py-16 text-center app-text-muted">
                  No runs match the current filters.
                </td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr key={run.run_id} className="app-row-hover align-top transition">
                  <td className="px-5 py-4">
                    <div className="max-w-[280px]">
                      <div className="flex flex-wrap items-center gap-2">
                        {run.strategy_id ? (
                          <Link to={`/strategies/${run.strategy_id}`} className="font-semibold app-title transition hover:text-cyan-400">
                            {formatRunLabel(run.strategy_name, run.strategy_version_number)}
                          </Link>
                        ) : (
                          <span className="font-semibold app-title">{formatRunLabel(run.strategy_name, run.strategy_version_number)}</span>
                        )}
                      </div>
                      <p className="mt-2 text-xs app-text-soft">
                        {formatRunType(run.run_type)} · {formatExecutorType(run.executor_type)}
                      </p>
                      <p className="mt-1 break-all font-mono text-[11px] app-text-muted">ID {run.run_id}</p>
                      <Link
                        to={`/runs/${run.run_id}`}
                        className="app-button-secondary mt-3 inline-flex rounded-xl px-3 py-1.5 text-xs font-medium"
                      >
                        View detail
                      </Link>
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
                  <td className="px-5 py-4">
                    <div className="min-w-[160px]">
                      <div className="flex items-center justify-between gap-3 text-xs app-text-muted">
                        <span className="truncate">{run.progress_message ?? 'No message'}</span>
                        <span>{run.progress_pct}%</span>
                      </div>
                      <div className="mt-2 h-2 rounded-full app-surface-soft">
                        <div
                          className="h-2 rounded-full bg-cyan-400 transition-all"
                          style={{ width: `${Math.max(0, Math.min(run.progress_pct, 100))}%` }}
                        />
                      </div>
                    </div>
                  </td>
                </tr>
              ))
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
