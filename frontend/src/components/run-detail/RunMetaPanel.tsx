import { useState } from 'react';

import { formatDateTime, formatDecimal } from '../../lib/formatters';
import type { RunResponse } from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

export function RunMetaPanel({ run }: { run: RunResponse }) {
  const summary = run.execution;
  const artifactKeys = Object.keys(run.artifact_summary?.manifest ?? {});
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <SectionCard
      title="Result details"
      subtitle="Operational metadata is still available, but it stays secondary to the performance story."
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-3 text-sm app-text-muted">
          <span>Artifacts: {artifactKeys.length}</span>
          <span>•</span>
          <span>Attempts: {summary?.attempt_count ?? run.attempt_count}</span>
          <span>•</span>
          <span>Duration: {formatDecimal(summary?.duration_seconds ?? null)} sec</span>
        </div>

        <button
          type="button"
          onClick={() => setIsExpanded((value) => !value)}
          className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
        >
          {isExpanded ? 'Hide details' : 'Show details'}
        </button>
      </div>

      {isExpanded ? (
        <div className="mt-5 grid gap-6 xl:grid-cols-[1.7fr_1fr]">
          <div className="app-panel rounded-2xl border">
            <dl className="divide-y app-divider rounded-2xl">
              <MetaRow label="Run ID" value={run.id} mono />
              <MetaRow label="Strategy ID" value={run.strategy_id} mono />
              <MetaRow label="Strategy Version ID" value={run.strategy_version_id} mono />
              <MetaRow label="Storage type" value={run.artifact_storage_type} />
              <MetaRow label="Queued at" value={formatDateTime(run.queued_at)} />
              <MetaRow label="Started at" value={formatDateTime(run.started_at)} />
              <MetaRow label="Finished at" value={formatDateTime(run.finished_at)} />
              <MetaRow label="Heartbeat at" value={formatDateTime(run.heartbeat_at)} />
              <MetaRow label="Worker ID" value={run.worker_id} mono />
              <MetaRow label="Attempts" value={`${run.attempt_count} / ${run.max_attempts}`} />
              <MetaRow label="Progress" value={`${run.progress_pct}%`} />
              <MetaRow label="Daily tracking run" value={run.is_daily_tracking_run ? 'Yes' : 'No'} />
              <MetaRow label="Parent run ID" value={run.parent_run_id} mono />
              <MetaRow label="Progress message" value={run.progress_message} />
              <MetaRow label="Error message" value={run.error_message} />
            </dl>
          </div>

          <div className="grid gap-6">
            <div className="app-card-soft rounded-2xl border p-4">
              <h4 className="text-sm font-semibold app-title">Execution Summary</h4>
              <dl className="mt-4 space-y-4 text-sm">
                <SummaryRow label="Duration (seconds)" value={formatDecimal(summary?.duration_seconds ?? null)} />
                <SummaryRow label="Attempts" value={String(summary?.attempt_count ?? run.attempt_count)} />
                <SummaryRow label="Max attempts" value={String(summary?.max_attempts ?? run.max_attempts)} />
                <SummaryRow label="Terminal" value={summary?.is_terminal ? 'Yes' : 'No'} />
              </dl>
            </div>

            <div className="app-card-soft rounded-2xl border p-4">
              <h4 className="text-sm font-semibold app-title">Artifacts</h4>
              <div className="mt-4 space-y-4">
                <SummaryRow label="Artifact files" value={String(artifactKeys.length)} />
                <SummaryRow label="Downloadable entries" value={String(Object.keys(run.artifact_download_urls ?? {}).length)} />
                <div className="flex flex-wrap gap-2">
                  {artifactKeys.length === 0 ? (
                    <span className="text-sm app-text-soft">No artifact manifest entries.</span>
                  ) : (
                    artifactKeys.map((key) => (
                      <span key={key} className="rounded-full border app-card px-3 py-1 text-xs font-medium app-text-muted">
                        {key}
                      </span>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </SectionCard>
  );
}

function MetaRow({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div className="grid gap-3 px-4 py-3 md:grid-cols-[220px_1fr]">
      <dt className="text-sm app-text-soft">{label}</dt>
      <dd className={`text-sm ${mono ? 'font-mono text-xs break-all' : ''} app-title`}>{value || '—'}</dd>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl border app-card px-4 py-3">
      <span className="app-text-muted">{label}</span>
      <span className="font-medium app-title">{value}</span>
    </div>
  );
}
