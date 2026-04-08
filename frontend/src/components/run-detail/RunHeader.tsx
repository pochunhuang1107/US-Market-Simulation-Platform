import { Link } from 'react-router-dom';

import { formatDateTime, formatRunLabel } from '../../lib/formatters';
import type { RunResponse } from '../../types/api';
import { RunStatusBadge } from '../runs/RunStatusBadge';

interface RunHeaderProps {
  run: RunResponse;
}

export function RunHeader({ run }: RunHeaderProps) {
  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-slate-950/40">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.26em] text-cyan-300">
              Run Detail
            </p>
            <h1 className="mt-2 text-4xl font-semibold tracking-tight text-white">
              {formatRunLabel(run.strategy_name, run.strategy_version_number)}
            </h1>
            <p className="mt-3 font-mono text-sm text-slate-400">{run.id}</p>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-400">
            <span>{run.run_type}</span>
            <span>•</span>
            <span>{run.executor_type}</span>
            <span>•</span>
            <span>Created {formatDateTime(run.created_at)}</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Link
              to="/runs"
              className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition hover:border-cyan-500/50 hover:text-cyan-300"
            >
              Back to runs
            </Link>

            {run.strategy_id ? (
              <Link
                to={`/strategies/${run.strategy_id}`}
                className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition hover:border-cyan-500/50 hover:text-cyan-300"
              >
                Open strategy
              </Link>
            ) : null}

            {run.strategy_id ? (
              <Link
                to={`/strategies/${run.strategy_id}/versions/new`}
                className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                New version
              </Link>
            ) : null}

            {run.strategy_id ? (
              <Link
                to={`/runs/new?strategyId=${run.strategy_id}`}
                className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                Create similar run
              </Link>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col items-start gap-4 lg:items-end">
          <RunStatusBadge status={run.status} />
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm text-slate-300">
            Finished {formatDateTime(run.finished_at)}
          </div>
        </div>
      </div>
    </section>
  );
}