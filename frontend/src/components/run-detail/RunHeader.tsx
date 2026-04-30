import { Link } from 'react-router-dom';

import {
  formatDateTime,
  formatExecutorType,
  formatRunLabel,
  formatRunType,
  formatSavedSweepVariantSource,
  isSavedSweepVariantResult,
  shortRunId
} from '../../lib/formatters';
import type { RunResponse } from '../../types/api';
import { RunStatusBadge } from '../runs/RunStatusBadge';

interface RunHeaderProps {
  run: RunResponse;
}

export function getDraftConfig(run: RunResponse): Record<string, unknown> | null {
  const draftConfig = run.request_payload?.draft_config;

  if (draftConfig && typeof draftConfig === 'object' && !Array.isArray(draftConfig)) {
    return draftConfig as Record<string, unknown>;
  }

  return null;
}

export function getModifyBuilderState(run: RunResponse) {
  const sourceDraftConfig = getDraftConfig(run);

  if (!sourceDraftConfig) return null;

  return {
    source: 'run_header',
    sourceRunId: run.id,
    sourceDraftConfig
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function getCleanString(value: unknown): string | null {
  if (typeof value !== 'string') return null;

  const cleaned = value.trim();
  if (!cleaned) return null;

  const normalized = cleaned.toLowerCase();
  if (normalized === 'benchmark' || normalized === 'benchmark_equity') return null;

  return cleaned;
}

function getBenchmarkLabel(run: RunResponse): string | null {
  const requestPayload = run.request_payload ?? {};
  const sources: unknown[] = [run.summary_json, getDraftConfig(run), requestPayload];

  for (const source of sources) {
    if (!isRecord(source)) continue;

    const symbol =
      getCleanString(source.benchmark_symbol) ??
      getCleanString(source.benchmark_ticker) ??
      getCleanString(source.benchmark);
    if (symbol) return symbol.toUpperCase();

    const name = getCleanString(source.benchmark_name) ?? getCleanString(source.benchmark_label);
    if (name) return name;
  }

  return null;
}

function formatAllocationPct(value: number): string {
  const pct = value * 100;
  return Number.isInteger(pct) ? `${pct.toFixed(0)}%` : `${pct.toFixed(1)}%`;
}

function getCoreOverlayLabel(run: RunResponse): string | null {
  const requestPayload = run.request_payload ?? {};
  const sources: unknown[] = [getDraftConfig(run), requestPayload, run.summary_json];

  for (const source of sources) {
    if (!isRecord(source)) continue;

    const coreOverlay = source.core_overlay;
    if (!isRecord(coreOverlay) || coreOverlay.enabled !== true) continue;
    if (typeof coreOverlay.core_allocation_pct !== 'number' || !Number.isFinite(coreOverlay.core_allocation_pct)) continue;

    const coreAllocation = coreOverlay.core_allocation_pct;
    const overlayAllocation = 1 - coreAllocation;

    return `Core / Overlay: ${formatAllocationPct(coreAllocation)} core · ${formatAllocationPct(overlayAllocation)} overlay`;
  }

  return null;
}

export function RunHeader({ run }: RunHeaderProps) {
  const isSavedSweepVariant = isSavedSweepVariantResult(run);
  const title = run.strategy_id
    ? formatRunLabel(run.strategy_name, run.strategy_version_number)
    : 'Unsaved draft run';
  const resultLabel = isSavedSweepVariant
    ? 'Saved Sweep Variant Result'
    : run.run_type === 'PARAMETER_SWEEP' ? 'Parameter Sweep Result' : 'Simulation Result';
  const benchmarkLabel = getBenchmarkLabel(run);
  const coreOverlayLabel = getCoreOverlayLabel(run);
  const metadata = isSavedSweepVariant
    ? [
        formatSavedSweepVariantSource(run),
        `Created ${formatDateTime(run.created_at)}`
      ]
    : [
        formatRunType(run.run_type),
        formatExecutorType(run.executor_type),
        `Created ${formatDateTime(run.created_at)}`
      ];

  if (benchmarkLabel) {
    metadata.push(`Benchmark: ${benchmarkLabel}`);
  }

  if (coreOverlayLabel) {
    metadata.push(coreOverlayLabel);
  }

  return (
    <section className="app-card app-shadow rounded-3xl border p-6">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-4">
          <div>
            <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.26em]">
              {resultLabel}
            </p>
            <h1 className="mt-2 text-4xl font-semibold tracking-tight app-title">
              {title}
            </h1>
            <p className="mt-3 text-sm app-text-muted" title={run.id}>
              Result ID: <span className="font-mono">{shortRunId(run.id)}</span>
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-sm app-text-muted">
            {metadata.map((item, index) => (
              <span key={item} className="inline-flex items-center gap-3">
                {index > 0 ? <span aria-hidden="true">•</span> : null}
                <span>{item}</span>
              </span>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Link to="/runs" className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition">
              Back to results
            </Link>

            {!isSavedSweepVariant && run.parent_run_id ? (
              <Link
                to={`/runs/${run.parent_run_id}`}
                className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
              >
                Parent result
              </Link>
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
                to={`/runs/new?strategyId=${run.strategy_id}`}
                className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition"
              >
                Create similar result
              </Link>
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
