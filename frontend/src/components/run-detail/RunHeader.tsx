import { Link } from 'react-router-dom';

import { formatDateTime, formatRunLabel } from '../../lib/formatters';
import type { RunResponse } from '../../types/api';
import { RunStatusBadge } from '../runs/RunStatusBadge';

interface RunHeaderProps {
  run: RunResponse;
  canSaveDraftStrategy?: boolean;
  isSavingDraftStrategy?: boolean;
  onSaveDraftStrategy?: () => void;
}

function getDraftConfig(run: RunResponse): Record<string, unknown> | null {
  const draftConfig = run.request_payload?.draft_config;

  if (draftConfig && typeof draftConfig === 'object' && !Array.isArray(draftConfig)) {
    return draftConfig as Record<string, unknown>;
  }

  return null;
}

function getModifyBuilderState(run: RunResponse) {
  const sourceDraftConfig = getDraftConfig(run);

  if (!sourceDraftConfig) return null;

  return {
    source: 'run_header',
    sourceRunId: run.id,
    sourceDraftConfig
  };
}

export function RunHeader({
  run,
  canSaveDraftStrategy = false,
  isSavingDraftStrategy = false,
  onSaveDraftStrategy
}: RunHeaderProps) {
  const title = run.strategy_id
    ? formatRunLabel(run.strategy_name, run.strategy_version_number)
    : 'Unsaved draft run';

  const modifyBuilderState = getModifyBuilderState(run);

  return (
    <section className="app-card app-shadow rounded-3xl border p-6">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-4">
          <div>
            <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.26em]">
              Simulation Result
            </p>
            <h1 className="mt-2 text-4xl font-semibold tracking-tight app-title">
              {title}
            </h1>
            <p className="mt-3 font-mono text-sm app-text-muted">{run.id}</p>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-sm app-text-muted">
            <span>{run.run_type}</span>
            <span>•</span>
            <span>{run.executor_type}</span>
            <span>•</span>
            <span>Created {formatDateTime(run.created_at)}</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Link to="/runs" className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition">
              Back to runs
            </Link>

            {modifyBuilderState ? (
              <Link
                to="/chat"
                state={modifyBuilderState}
                className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition"
              >
                Create Draft Variant
              </Link>
            ) : null}

            {run.parent_run_id ? (
              <>
                <Link
                  to={`/runs/${run.parent_run_id}`}
                  className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
                >
                  Parent run
                </Link>

                <Link
                  to={`/compare?runIds=${run.parent_run_id},${run.id}`}
                  className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
                >
                  Compare with parent
                </Link>
              </>
            ) : null}

            {run.strategy_id ? (
              <Link
                to={`/strategies/${run.strategy_id}`}
                className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
              >
                Open strategy
              </Link>
            ) : null}

            {run.strategy_id ? (
              <Link
                to={`/strategies/${run.strategy_id}/versions/new`}
                className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
              >
                New version
              </Link>
            ) : null}

            {run.strategy_id ? (
              <Link
                to={`/runs/new?strategyId=${run.strategy_id}`}
                className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
              >
                Create similar run
              </Link>
            ) : null}

            {canSaveDraftStrategy ? (
              <button
                type="button"
                onClick={onSaveDraftStrategy}
                disabled={isSavingDraftStrategy}
                className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSavingDraftStrategy ? 'Saving...' : 'Save strategy'}
              </button>
            ) : null}
          </div>
        </div>

        <div className="flex flex-col items-start gap-4 lg:items-end">
          <RunStatusBadge status={run.status} />
          <div className="app-card-soft rounded-2xl border px-4 py-3 text-sm app-text-muted">
            Finished {formatDateTime(run.finished_at)}
          </div>
        </div>
      </div>
    </section>
  );
}