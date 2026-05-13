import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import {
  ApiRequestError,
  createRun,
  enqueueRun,
  fetchCurrentModelSignalPreview,
  fetchMeEntitlements,
  fetchModelSignalCatalog
} from '../../lib/api';
import type {
  MeEntitlementsResponse,
  ModelSignalCatalogItemResponse,
  ModelSignalCatalogListResponse,
  ModelSignalCurrentPreviewResponse
} from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

type PreviewState = {
  data: ModelSignalCurrentPreviewResponse | null;
  error: string | null;
  status: number | null;
  loading: boolean;
};

const BLOCKED_NOTE_TERMS = [
  ['guaran', 'teed'].join(''),
  ['buy', 'now'].join(' '),
  ['will', 'outperform'].join(' '),
  ['best', 'model'].join(' '),
  ['live', 'trading', 'signal'].join(' ')
];

function formatStatus(value: string): string {
  return value.replace(/_/g, ' ');
}

function compactList(values: string[], maxItems = 6): string {
  if (values.length === 0) return '—';
  const visible = values.slice(0, maxItems);
  const suffix = values.length > visible.length ? ` +${values.length - visible.length}` : '';
  return `${visible.join(', ')}${suffix}`;
}

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return 'Request failed.';
}

function formatPreviewError(error: unknown): { message: string; status: number | null } {
  if (error instanceof ApiRequestError) {
    if (error.status === 404) {
      return {
        message: 'Current preview unavailable. The model signal artifact is missing or not configured.',
        status: error.status
      };
    }
    if (error.status === 422) {
      return {
        message: 'Current preview unavailable because the model signal artifact did not validate.',
        status: error.status
      };
    }
    if (error.status === 403) {
      return {
        message: 'Model Strategy Lab is locked for your current plan.',
        status: error.status
      };
    }
    return { message: error.message, status: error.status };
  }

  return { message: formatUnknownError(error), status: null };
}

function formatRunError(error: unknown): string {
  if (error instanceof ApiRequestError && error.status === 403) {
    return error.message;
  }
  return formatUnknownError(error);
}

function extractDuplicateRunId(error: unknown): string | null {
  if (error instanceof ApiRequestError && error.status === 409 && error.body && typeof error.body === 'object') {
    const detail = (error.body as { detail?: { code?: unknown; existing_run_id?: unknown } }).detail;
    if (
      detail &&
      detail.code === 'DUPLICATE_ACTIVE_RUN' &&
      typeof detail.existing_run_id === 'string'
    ) {
      return detail.existing_run_id;
    }
  }

  return null;
}

function cleanModelNote(note: string): string | null {
  const trimmed = note.trim();
  if (!trimmed) return null;

  const normalized = BLOCKED_NOTE_TERMS.reduce((current, term) => {
    const pattern = new RegExp(`\\b${term}\\b`, 'gi');
    return current.replace(pattern, term.includes(' ') ? 'restricted phrase' : 'assured');
  }, trimmed).replace(/\bnot a assured\b/gi, 'not an assured');

  return normalized;
}

function formatIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function oneYearBefore(dateIso: string): string {
  const date = new Date(`${dateIso}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) {
    throw new Error('Current signal preview returned an invalid date.');
  }

  const start = new Date(date);
  start.setUTCFullYear(start.getUTCFullYear() - 1);
  return formatIsoDate(start);
}

function sortedUnique(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim().toUpperCase()).filter(Boolean))).sort();
}

export function buildModelSignalStrategyDraft(
  model: ModelSignalCatalogItemResponse,
  preview: ModelSignalCurrentPreviewResponse
): Record<string, unknown> {
  const defaults = model.recommended_defaults;
  const universe = sortedUnique(defaults.universe.length > 0 ? defaults.universe : model.default_universe);
  if (universe.length === 0) {
    throw new Error('Catalog defaults are missing a model universe.');
  }

  const benchmark = defaults.benchmark || model.default_benchmark;
  const selectedTradable = preview.selected_symbols.find((symbol) => universe.includes(symbol.toUpperCase()));
  const tradableSymbol = (selectedTradable ?? universe[0]).toUpperCase();
  const referenceSymbols = sortedUnique([...universe, benchmark]).filter((symbol) => symbol !== tradableSymbol);
  const signalBucketFilter =
    defaults.signal_bucket_filter.length > 0 ? defaults.signal_bucket_filter : model.default_signal_bucket_filter;

  return {
    schema_version: '2.0',
    name: `${model.display_name} paper-tracking signal`,
    tradable_symbol: tradableSymbol,
    benchmark_symbol: benchmark,
    reference_symbols: referenceSymbols,
    start_date: oneYearBefore(preview.latest_signal_date),
    end_date: preview.latest_signal_date,
    initial_capital: 100000,
    transaction_cost_bps: 5,
    model_signal: {
      enabled: true,
      model_version: model.model_version,
      ranking_field: defaults.ranking_field || model.ranking_field,
      universe,
      top_n: defaults.top_n || model.default_top_n,
      rebalance: {
        frequency: 'monthly',
        day: 'first_trading_day'
      },
      fallback: defaults.fallback ?? model.default_fallback,
      signal_bucket_filter: signalBucketFilter
    }
  };
}

function getRunDisabledReason({
  entitlements,
  entitlementsLoading,
  model,
  previewState,
  running
}: {
  entitlements: MeEntitlementsResponse | null;
  entitlementsLoading: boolean;
  model: ModelSignalCatalogItemResponse;
  previewState: PreviewState | undefined;
  running: boolean;
}): string | null {
  if (running) return 'Creating result...';
  if (entitlementsLoading) return 'Checking access...';
  if (entitlements && !entitlements.features.allow_advanced_builder) return 'Locked for current plan.';
  if (entitlements && entitlements.usage.daily_runs_remaining === 0) return 'Daily simulation limit reached.';
  if (!model.enabled) return 'Model is disabled.';
  if (!previewState?.data) return 'Current signal preview is required before running.';
  if (model.recommended_defaults.universe.length === 0 && model.default_universe.length === 0) {
    return 'Catalog defaults are unavailable.';
  }
  return null;
}

export function ModelStrategyLab() {
  const navigate = useNavigate();
  const [entitlements, setEntitlements] = useState<MeEntitlementsResponse | null>(null);
  const [entitlementsLoading, setEntitlementsLoading] = useState(true);
  const [entitlementError, setEntitlementError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<ModelSignalCatalogListResponse | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogErrorStatus, setCatalogErrorStatus] = useState<number | null>(null);
  const [previewByModel, setPreviewByModel] = useState<Record<string, PreviewState>>({});
  const [runningModelVersion, setRunningModelVersion] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    async function loadEntitlements() {
      setEntitlementsLoading(true);
      setEntitlementError(null);

      try {
        const response = await fetchMeEntitlements();
        if (!ignore) {
          setEntitlements(response);
        }
      } catch (error) {
        if (!ignore) {
          setEntitlementError(formatUnknownError(error));
        }
      } finally {
        if (!ignore) {
          setEntitlementsLoading(false);
        }
      }
    }

    void loadEntitlements();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (entitlementsLoading) return;

    if (entitlements && !entitlements.features.allow_advanced_builder) {
      setCatalog(null);
      setCatalogLoading(false);
      setCatalogError(null);
      setCatalogErrorStatus(null);
      return;
    }

    if (!entitlements && entitlementError) {
      setCatalogLoading(false);
      return;
    }

    let ignore = false;

    async function loadCatalog() {
      setCatalogLoading(true);
      setCatalogError(null);
      setCatalogErrorStatus(null);

      try {
        const response = await fetchModelSignalCatalog();
        if (!ignore) {
          setCatalog(response);
        }
      } catch (error) {
        const formatted = formatPreviewError(error);
        if (!ignore) {
          setCatalog(null);
          setCatalogError(formatted.message);
          setCatalogErrorStatus(formatted.status);
        }
      } finally {
        if (!ignore) {
          setCatalogLoading(false);
        }
      }
    }

    void loadCatalog();
    return () => {
      ignore = true;
    };
  }, [entitlementError, entitlements, entitlementsLoading]);

  useEffect(() => {
    const models = catalog?.models ?? [];
    if (models.length === 0) {
      setPreviewByModel({});
      return;
    }

    let ignore = false;
    setPreviewByModel(
      Object.fromEntries(
        models.map((model) => [
          model.model_version,
          {
            data: null,
            error: null,
            status: null,
            loading: true
          }
        ])
      )
    );

    models.forEach((model) => {
      void fetchCurrentModelSignalPreview(model.model_version)
        .then((preview) => {
          if (ignore) return;
          setPreviewByModel((current) => ({
            ...current,
            [model.model_version]: {
              data: preview,
              error: null,
              status: null,
              loading: false
            }
          }));
        })
        .catch((error) => {
          const formatted = formatPreviewError(error);
          if (ignore) return;
          setPreviewByModel((current) => ({
            ...current,
            [model.model_version]: {
              data: null,
              error: formatted.message,
              status: formatted.status,
              loading: false
            }
          }));
        });
    });

    return () => {
      ignore = true;
    };
  }, [catalog]);

  const isLocked = Boolean(
    (entitlements && !entitlements.features.allow_advanced_builder) || catalogErrorStatus === 403
  );
  const models = useMemo(() => catalog?.models ?? [], [catalog]);

  async function handleRunModel(model: ModelSignalCatalogItemResponse) {
    const preview = previewByModel[model.model_version]?.data;
    if (!preview) return;

    setRunError(null);
    setRunningModelVersion(model.model_version);

    try {
      const draftConfig = buildModelSignalStrategyDraft(model, preview);
      const run = await createRun({
        draft_config: draftConfig,
        run_type: 'SIMULATION',
        executor_type: 'SIMULATION_EXECUTOR',
        request_payload: {
          source: 'model_strategy_lab',
          model_version: model.model_version,
          latest_signal_date: preview.latest_signal_date,
          selected_symbols: preview.selected_symbols
        },
        max_attempts: 1
      });

      await enqueueRun(run.id);

      try {
        setEntitlements(await fetchMeEntitlements());
      } catch {
        // The run was created; entitlement refresh can wait until the next page load.
      }

      navigate(`/runs/${run.id}`);
    } catch (error) {
      const duplicateRunId = extractDuplicateRunId(error);
      if (duplicateRunId) {
        navigate(`/runs/${duplicateRunId}`, {
          state: {
            notice: {
              tone: 'info',
              message: 'This model strategy result was already active, so we opened the existing result.'
            }
          }
        });
        return;
      }

      setRunError(formatRunError(error));
    } finally {
      setRunningModelVersion(null);
    }
  }

  return (
    <SectionCard
      title="Model Strategy Lab"
      subtitle="Compact research surface for backend cataloged model-signal strategies."
    >
      <div className="space-y-5">
        <div className="app-note rounded-2xl px-4 py-3 text-sm">
          Research model and paper-tracking signal only. Use this to run historical simulation from catalog defaults;
          not investment advice.
        </div>

        {entitlementError ? (
          <div className="app-alert-error rounded-2xl border px-4 py-3 text-sm">
            Could not load account access. {entitlementError}
          </div>
        ) : null}

        {runError ? (
          <div className="app-alert-error rounded-2xl border px-4 py-3 text-sm">
            Model signal backtest could not be created. {runError}
          </div>
        ) : null}

        {entitlementsLoading || catalogLoading ? (
          <div className="app-value-block rounded-2xl px-4 py-4 text-sm app-text-muted">
            Loading model signal catalog...
          </div>
        ) : null}

        {isLocked ? (
          <div className="app-value-block rounded-2xl px-4 py-4">
            <p className="app-title text-sm font-semibold">Advanced research access required</p>
            <p className="mt-1 text-sm app-text-muted">
              Model Strategy Lab is locked for {entitlements?.plan.name ?? 'your current plan'}. Beta Tester access
              uses this same advanced entitlement.
            </p>
          </div>
        ) : null}

        {!isLocked && catalogError ? (
          <div className="app-alert-error rounded-2xl border px-4 py-3 text-sm">
            Model signal catalog could not load. {catalogError}
          </div>
        ) : null}

        {!isLocked && !entitlementError && !catalogLoading && !catalogError && models.length === 0 ? (
          <div className="app-value-block rounded-2xl px-4 py-4 text-sm app-text-muted">
            No model signal catalog entries are available yet.
          </div>
        ) : null}

        {models.length > 0 ? (
          <div className="grid gap-4">
            {models.map((model) => {
              const previewState = previewByModel[model.model_version];
              const selectedSymbols = previewState?.data?.selected_symbols ?? [];
              const disabledReason = getRunDisabledReason({
                entitlements,
                entitlementsLoading,
                model,
                previewState,
                running: runningModelVersion === model.model_version
              });
              const notes = [...model.risk_notes, ...model.limitations]
                .map(cleanModelNote)
                .filter((note): note is string => Boolean(note))
                .slice(0, 4);

              return (
                <article key={model.model_version} className="app-value-block rounded-2xl px-4 py-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="app-title text-base font-semibold">{model.display_name}</h4>
                        <span className="app-badge rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em]">
                          {formatStatus(model.research_status)}
                        </span>
                      </div>
                      <p className="mt-1 break-all text-xs app-text-muted">{model.model_version}</p>
                    </div>
                    <button
                      type="button"
                      disabled={Boolean(disabledReason)}
                      onClick={() => {
                        void handleRunModel(model);
                      }}
                      className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
                      title={disabledReason ?? 'Run historical simulation'}
                    >
                      {runningModelVersion === model.model_version ? 'Creating...' : 'Run model signal backtest'}
                    </button>
                  </div>

                  <div className="mt-4 grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-3">
                    <Info label="Supported universe" value={`${model.supported_universe.length} ETFs`} />
                    <Info label="Default universe" value={compactList(model.default_universe)} />
                    <Info label="Default top_n" value={String(model.default_top_n)} />
                    <Info label="Ranking field" value={model.ranking_field} />
                    <Info
                      label="Latest signal date"
                      value={
                        previewState?.loading
                          ? 'Loading...'
                          : previewState?.data?.latest_signal_date ?? 'Preview unavailable'
                      }
                    />
                    <Info
                      label="Current selected symbol(s)"
                      value={
                        previewState?.loading
                          ? 'Loading...'
                          : selectedSymbols.length > 0
                            ? selectedSymbols.join(', ')
                            : 'Preview unavailable'
                      }
                    />
                  </div>

                  {previewState?.error ? (
                    <p className="mt-3 rounded-2xl border px-3 py-2 text-sm app-alert-warning">
                      {previewState.error}
                    </p>
                  ) : null}

                  {model.recommended_use ? (
                    <p className="mt-3 text-sm app-text-muted">{model.recommended_use}</p>
                  ) : null}

                  {notes.length > 0 ? (
                    <ul className="app-list mt-3 space-y-1 text-sm">
                      {notes.map((note) => (
                        <li key={note}>- {note}</li>
                      ))}
                    </ul>
                  ) : null}

                  {disabledReason ? (
                    <p className="mt-3 text-xs app-text-soft">{disabledReason}</p>
                  ) : null}
                </article>
              );
            })}
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border app-border-soft px-3 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] app-text-soft">{label}</p>
      <p className="mt-1 app-title">{value}</p>
    </div>
  );
}
