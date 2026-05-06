import { Link } from 'react-router-dom';

import type { RunResponse } from '../../types/api';
import { getModifyBuilderState } from './RunHeader';

interface NextResearchStepsPanelProps {
  run: RunResponse;
  canSaveDraftStrategy: boolean;
  isSavingDraftStrategy: boolean;
  onSaveDraftStrategy: () => void;
}

export function NextResearchStepsPanel({
  run,
  canSaveDraftStrategy,
  isSavingDraftStrategy,
  onSaveDraftStrategy
}: NextResearchStepsPanelProps) {
  const modifyBuilderState = getModifyBuilderState(run);
  const isSavedSweepVariantResult = run.source === 'sweep_variant_save';
  const canCompareWithParent = Boolean(run.parent_run_id) && !isSavedSweepVariantResult;

  return (
    <section className="app-card-soft rounded-2xl border p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="app-eyebrow text-[11px] font-semibold uppercase tracking-[0.22em]">
            Next research steps
          </p>
          <p className="app-text-muted mt-1 text-sm">
            Turn this result into the next draft, comparison, or saved strategy.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {modifyBuilderState ? (
            <Link
              to="/workspace"
              state={modifyBuilderState}
              className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition"
            >
              Create Draft Variant
            </Link>
          ) : null}

          {canCompareWithParent ? (
            <Link
              to={`/compare?runIds=${run.parent_run_id},${run.id}`}
              className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
            >
              Compare with parent
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
    </section>
  );
}
