import { formatDateTime, formatDecimal } from '../../lib/formatters';
import type { RunResponse } from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

export function RunMetaPanel({ run }: { run: RunResponse }) {
  const summary = run.execution;
  const artifactKeys = Object.keys(run.artifact_summary?.manifest ?? {});

  return (
    <div className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
      <SectionCard title="Run Metadata" subtitle="Read-only fields from RunResponse that are safe and useful for UI monitoring.">
        <dl className="divide-y divide-slate-800 rounded-2xl border border-slate-800 bg-slate-950/40">
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
      </SectionCard>

      <div className="grid gap-6">
        <SectionCard title="Execution Summary" subtitle="Operational status pulled from the execution block.">
          <dl className="space-y-4 text-sm">
            <SummaryRow label="Duration (seconds)" value={formatDecimal(summary?.duration_seconds ?? null)} />
            <SummaryRow label="Attempts" value={String(summary?.attempt_count ?? run.attempt_count)} />
            <SummaryRow label="Max attempts" value={String(summary?.max_attempts ?? run.max_attempts)} />
            <SummaryRow label="Terminal" value={summary?.is_terminal ? 'Yes' : 'No'} />
          </dl>
        </SectionCard>

        <SectionCard title="Artifacts" subtitle="User-facing artifact summary without exposing raw internal storage paths in the main UI.">
          <div className="space-y-4">
            <SummaryRow label="Artifact files" value={String(artifactKeys.length)} />
            <SummaryRow label="Downloadable entries" value={String(Object.keys(run.artifact_download_urls ?? {}).length)} />
            <div className="flex flex-wrap gap-2">
              {artifactKeys.length === 0 ? (
                <span className="text-sm text-slate-500">No artifact manifest entries.</span>
              ) : (
                artifactKeys.map((key) => (
                  <span key={key} className="rounded-full border border-slate-700 bg-slate-950/70 px-3 py-1 text-xs font-medium text-slate-300">
                    {key}
                  </span>
                ))
              )}
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

function MetaRow({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div className="grid gap-3 px-4 py-3 md:grid-cols-[220px_1fr]">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className={`text-sm text-slate-200 ${mono ? 'font-mono text-xs break-all' : ''}`}>{value || '—'}</dd>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-800 bg-slate-950/50 px-4 py-3">
      <span className="text-slate-400">{label}</span>
      <span className="font-medium text-white">{value}</span>
    </div>
  );
}
