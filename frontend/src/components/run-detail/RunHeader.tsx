import { Link } from 'react-router-dom';

import { formatDateTime, formatRunLabel } from '../../lib/formatters';
import type { RunResponse } from '../../types/api';
import { RunStatusBadge } from '../runs/RunStatusBadge';

export function RunHeader({ run }: { run: RunResponse }) {
  return (
    <div className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/40">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">Run Detail</p>
          <h2 className="mt-2 text-3xl font-semibold text-white">{formatRunLabel(run.strategy_name, run.strategy_version_number)}</h2>
          <p className="mt-3 font-mono text-xs text-slate-400">{run.id}</p>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-400">
            <span>{run.run_type}</span>
            <span className="text-slate-600">•</span>
            <span>{run.executor_type}</span>
            <span className="text-slate-600">•</span>
            <span>Created {formatDateTime(run.created_at)}</span>
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Link to="/runs" className="rounded-xl border border-slate-700 px-4 py-2 text-sm text-slate-200 transition hover:border-cyan-500/50 hover:text-cyan-300">
              Back to runs
            </Link>
            {run.strategy_id ? (
              <Link
                to={`/strategies/${run.strategy_id}`}
                className="rounded-xl border border-slate-700 px-4 py-2 text-sm text-slate-200 transition hover:border-cyan-500/50 hover:text-cyan-300"
              >
                Open strategy
              </Link>
            ) : null}
            {run.strategy_id ? (
              <Link
                to={`/runs/new?strategyId=${run.strategy_id}${run.strategy_version_id ? `&versionId=${run.strategy_version_id}` : ''}`}
                className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                Create similar run
              </Link>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col items-start gap-3 lg:items-end">
          <RunStatusBadge status={run.status} />
          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-300">
            Finished {formatDateTime(run.finished_at)}
          </div>
        </div>
      </div>
    </div>
  );
}
