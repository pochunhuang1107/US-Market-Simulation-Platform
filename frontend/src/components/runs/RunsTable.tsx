import { Link } from 'react-router-dom';

import { formatDateTime, formatNumber, formatPct, formatRunLabel } from '../../lib/formatters';
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
    <div className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-900/70 shadow-2xl shadow-slate-950/40">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-900">
            <tr className="text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
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
          <tbody className="divide-y divide-slate-800">
            {loading ? (
              <tr>
                <td colSpan={columns} className="px-5 py-16 text-center text-slate-400">
                  Loading runs…
                </td>
              </tr>
            ) : runs.length === 0 ? (
              <tr>
                <td colSpan={columns} className="px-5 py-16 text-center text-slate-400">
                  No runs matched the current view.
                </td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr key={run.run_id} className="align-top transition hover:bg-slate-800/50">
                  <td className="px-5 py-4">
                    <div className="max-w-[280px]">
                      <div className="flex flex-wrap items-center gap-2">
                        {run.strategy_id ? (
                          <Link to={`/strategies/${run.strategy_id}`} className="font-semibold text-white transition hover:text-cyan-300">
                            {formatRunLabel(run.strategy_name, run.strategy_version_number)}
                          </Link>
                        ) : (
                          <span className="font-semibold text-white">{formatRunLabel(run.strategy_name, run.strategy_version_number)}</span>
                        )}
                      </div>
                      <p className="mt-1 font-mono text-xs text-slate-400">{run.run_id}</p>
                      <p className="mt-2 text-xs text-slate-500">
                        {run.run_type} · {run.executor_type}
                      </p>
                      <Link
                        to={`/runs/${run.run_id}`}
                        className="mt-3 inline-flex rounded-xl border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-cyan-500/50 hover:bg-slate-800 hover:text-cyan-300"
                      >
                        View detail
                      </Link>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <RunStatusBadge status={run.status} />
                  </td>
                  <td className="px-5 py-4 text-slate-300">{formatDateTime(run.created_at)}</td>
                  <td className="px-5 py-4 text-slate-300">{formatDateTime(run.finished_at)}</td>
                  <td className="px-5 py-4 font-medium text-slate-100">{formatPct(run.total_return_pct)}</td>
                  <td className="px-5 py-4 text-slate-300">{formatPct(run.cagr_pct)}</td>
                  {!compact ? <td className="px-5 py-4 text-slate-300">{formatPct(run.max_drawdown_pct)}</td> : null}
                  {!compact ? <td className="px-5 py-4 text-slate-300">{formatNumber(run.trade_count)}</td> : null}
                  <td className="px-5 py-4">
                    <div className="min-w-[160px]">
                      <div className="flex items-center justify-between gap-3 text-xs text-slate-400">
                        <span className="truncate">{run.progress_message ?? 'No message'}</span>
                        <span>{run.progress_pct}%</span>
                      </div>
                      <div className="mt-2 h-2 rounded-full bg-slate-800">
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
