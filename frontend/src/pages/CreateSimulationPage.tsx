import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { createRun, enqueueRun, fetchStrategies, fetchStrategyDashboard } from '../lib/api';
import {
  formatDateTime,
  formatExecutorType,
  formatRunType,
  formatStrategyStatus,
  formatStrategyType
} from '../lib/formatters';
import { getStrategyBehaviorFields } from '../lib/strategyBehaviorSummary';
import type { CreateRunRequest, RunType, StrategyDashboardResponse, StrategyListItem } from '../types/api';

const RUN_TYPE_OPTIONS = [
  { value: 'SIMULATION', label: formatRunType('SIMULATION') },
  { value: 'PORTFOLIO', label: formatRunType('PORTFOLIO') },
  { value: 'COMPARISON', label: formatRunType('COMPARISON') },
  { value: 'PARAMETER_SWEEP', label: formatRunType('PARAMETER_SWEEP') }
] as const;

function getExecutorTypeForRunType(runType: RunType): string {
  switch (runType) {
    case 'SIMULATION':
      return 'SIMULATION_EXECUTOR';
    case 'PORTFOLIO':
      return 'PORTFOLIO_EXECUTOR';
    case 'COMPARISON':
      return 'COMPARISON_EXECUTOR';
    case 'PARAMETER_SWEEP':
      return 'SWEEP_EXECUTOR';
    default:
      return 'SIMULATION_EXECUTOR';
  }
}

function buildDefaultRequestPayload(config: Record<string, unknown> | null | undefined): string {
  const payload: Record<string, unknown> = {};
  if (typeof config?.start_date === 'string') {
    payload.start_date = config.start_date;
  }
  if (typeof config?.end_date === 'string') {
    payload.end_date = config.end_date;
  }
  if (typeof config?.initial_capital === 'number') {
    payload.initial_capital = config.initial_capital;
  }
  return JSON.stringify(payload, null, 2);
}

function sanitizeInternalValues(value: unknown): unknown {
  const cloudPrefix = ['s3', '://'].join('');
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeInternalValues(item));
  }

  if (!value || typeof value !== 'object') {
    if (typeof value === 'string' && (value.startsWith(cloudPrefix) || value.includes('local_artifacts'))) {
      return '[managed by platform]';
    }
    return value;
  }

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => {
        const normalized = key.toLowerCase();
        return !normalized.includes('artifact') && !normalized.includes('path') && !normalized.includes('uri');
      })
      .map(([key, nestedValue]) => [key, sanitizeInternalValues(nestedValue)])
  );
}

export function CreateSimulationPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [strategies, setStrategies] = useState<StrategyListItem[]>([]);
  const [strategyLoading, setStrategyLoading] = useState(true);
  const [strategyError, setStrategyError] = useState<string | null>(null);

  const [selectedStrategyId, setSelectedStrategyId] = useState(searchParams.get('strategyId') ?? '');
  const [strategyDashboard, setStrategyDashboard] = useState<StrategyDashboardResponse | null>(null);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionsError, setVersionsError] = useState<string | null>(null);

  const [selectedVersionId, setSelectedVersionId] = useState(searchParams.get('versionId') ?? '');
  const [runType, setRunType] = useState<RunType>('SIMULATION');
  const [maxAttempts, setMaxAttempts] = useState(3);
  const [enqueueImmediately, setEnqueueImmediately] = useState(true);
  const [requestPayloadText, setRequestPayloadText] = useState(buildDefaultRequestPayload(null));

  const [submitError, setSubmitError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [createdRunId, setCreatedRunId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let ignore = false;

    async function loadStrategies() {
      setStrategyLoading(true);
      setStrategyError(null);

      try {
        const response = await fetchStrategies();
        if (!ignore) {
          setStrategies(response);
          if (!selectedStrategyId && response.length > 0) {
            setSelectedStrategyId(response[0].id);
          }
        }
      } catch (error) {
        if (!ignore) {
          setStrategyError(error instanceof Error ? error.message : 'Failed to load strategies');
        }
      } finally {
        if (!ignore) {
          setStrategyLoading(false);
        }
      }
    }

    void loadStrategies();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let ignore = false;

    async function loadStrategyDashboard() {
      if (!selectedStrategyId) {
        setStrategyDashboard(null);
        setVersionsError(null);
        return;
      }

      setVersionsLoading(true);
      setVersionsError(null);

      try {
        const response = await fetchStrategyDashboard(selectedStrategyId);
        if (!ignore) {
          setStrategyDashboard(response);

          const requestedVersionId = searchParams.get('versionId');
          if (requestedVersionId && response.versions.some((version) => version.id === requestedVersionId)) {
            setSelectedVersionId(requestedVersionId);
          } else {
            const currentVersion = response.versions.find((version) => version.is_current) ?? response.versions[0] ?? null;
            setSelectedVersionId(currentVersion?.id ?? '');
          }
        }
      } catch (error) {
        if (!ignore) {
          setStrategyDashboard(null);
          setVersionsError(error instanceof Error ? error.message : 'Failed to load strategy versions');
        }
      } finally {
        if (!ignore) {
          setVersionsLoading(false);
        }
      }
    }

    void loadStrategyDashboard();
    return () => {
      ignore = true;
    };
  }, [selectedStrategyId]);

  const selectedStrategy = useMemo(
    () => strategies.find((strategy) => strategy.id === selectedStrategyId) ?? null,
    [strategies, selectedStrategyId]
  );

  const selectedVersion = useMemo(
    () => strategyDashboard?.versions.find((version) => version.id === selectedVersionId) ?? null,
    [strategyDashboard, selectedVersionId]
  );

  useEffect(() => {
    setRequestPayloadText(buildDefaultRequestPayload(selectedVersion?.config_json));
  }, [selectedVersion?.id]);

  const executorType = useMemo(() => getExecutorTypeForRunType(runType), [runType]);
  const selectedBehaviorFields = useMemo(
    () => getStrategyBehaviorFields(selectedVersion?.config_json),
    [selectedVersion?.config_json]
  );

  async function handleSubmit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError(null);
    setSuccessMessage(null);
    setCreatedRunId(null);

    if (!selectedStrategyId) {
      setSubmitError('Choose a strategy before creating a result.');
      return;
    }

    if (!selectedVersionId) {
      setSubmitError('Choose a strategy version before creating a result.');
      return;
    }

    let parsedPayload: Record<string, unknown>;
    try {
      const value = JSON.parse(requestPayloadText) as unknown;
      if (!value || typeof value !== 'object' || Array.isArray(value)) {
        throw new Error('Request payload must be a JSON object.');
      }
      parsedPayload = value as Record<string, unknown>;
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Request payload must be valid JSON.');
      return;
    }

    const payload: CreateRunRequest = {
      strategy_id: selectedStrategyId,
      strategy_version_id: selectedVersionId,
      run_type: runType,
      executor_type: executorType,
      request_payload: parsedPayload,
      max_attempts: maxAttempts
    };

    setSubmitting(true);

    try {
      const run = await createRun(payload);
      setCreatedRunId(run.id);

      if (enqueueImmediately) {
        const action = await enqueueRun(run.id);
        setSuccessMessage(`Result created and queued. ${action.message}`);
      } else {
        setSuccessMessage('Result created successfully. It is still pending until you enqueue it.');
      }
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Failed to create simulation result');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Advanced"
        title="Advanced Manual Run"
        description="Manually submit a new run using existing strategy and version records. The workspace builder remains the primary path for drafting and running ideas."
        actions={
          <>
            <Link to="/runs" className="app-button-secondary rounded-xl px-4 py-2 text-sm transition">
              Back to results
            </Link>
            {createdRunId ? (
              <button
                type="button"
                onClick={() => navigate(`/runs/${createdRunId}`)}
                className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition"
              >
                Open created result
              </button>
            ) : null}
          </>
        }
      />

      {strategyError ? <StateCard title="Failed to load strategies" description={strategyError} tone="error" /> : null}
      {versionsError ? <StateCard title="Failed to load strategy versions" description={versionsError} tone="error" /> : null}
      {submitError ? <StateCard title="Result creation failed" description={submitError} tone="error" /> : null}
      {successMessage ? <StateCard title="Result request accepted" description={successMessage} /> : null}

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <SectionCard title="Manual Run Request" subtitle="Choose a strategy and version, then submit a manual run request payload.">
          <form className="space-y-6" onSubmit={handleSubmit}>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Strategy">
                <select
                  value={selectedStrategyId}
                  onChange={(event) => setSelectedStrategyId(event.target.value)}
                  disabled={strategyLoading || strategies.length === 0}
                  className={inputClassName}
                >
                  {strategyLoading ? <option>Loading strategies…</option> : null}
                  {!strategyLoading && strategies.length === 0 ? <option value="">No strategies available</option> : null}
                  {!strategyLoading
                    ? strategies.map((strategy) => (
                        <option key={strategy.id} value={strategy.id}>
                          {strategy.name}
                        </option>
                      ))
                    : null}
                </select>
              </Field>

              <Field label="Version">
                <select
                  value={selectedVersionId}
                  onChange={(event) => setSelectedVersionId(event.target.value)}
                  disabled={versionsLoading || !strategyDashboard || strategyDashboard.versions.length === 0}
                  className={inputClassName}
                >
                  {versionsLoading ? <option>Loading versions…</option> : null}
                  {!versionsLoading && (!strategyDashboard || strategyDashboard.versions.length === 0) ? (
                    <option value="">No versions available</option>
                  ) : null}
                  {!versionsLoading
                    ? strategyDashboard?.versions.map((version) => (
                        <option key={version.id} value={version.id}>
                          v{version.version_number} {version.is_current ? '· current' : ''}
                        </option>
                      ))
                    : null}
                </select>
              </Field>

              <Field label="Run Type">
                <select
                  value={runType}
                  onChange={(event) => setRunType(event.target.value as RunType)}
                  className={inputClassName}
                >
                  {RUN_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
              <p className="text-xs app-text-muted">
                Executor is selected automatically from run type.
              </p>

              <Field label="Max Attempts">
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={maxAttempts}
                  onChange={(event) => {
                    const nextValue = Number(event.target.value);
                    setMaxAttempts(Number.isNaN(nextValue) ? 1 : Math.max(1, Math.min(10, nextValue)));
                  }}
                  className={inputClassName}
                />
              </Field>

              <Field label="Queue after create">
                <label className="app-form-field flex h-[46px] items-center gap-3 rounded-2xl px-4 text-sm">
                  <input
                    type="checkbox"
                    checked={enqueueImmediately}
                    onChange={(event) => setEnqueueImmediately(event.target.checked)}
                    className="app-checkbox h-4 w-4 rounded"
                  />
                  Enqueue immediately after the result is created
                </label>
              </Field>
            </div>

            <Field label="Request Payload JSON">
              <textarea
                value={requestPayloadText}
                onChange={(event) => setRequestPayloadText(event.target.value)}
                rows={14}
                spellCheck={false}
                className="app-form-code min-h-[320px] w-full rounded-2xl px-4 py-3 font-mono text-xs leading-6 outline-none transition"
              />
            </Field>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={submitting || strategyLoading || versionsLoading}
                className="app-button-primary rounded-xl px-5 py-2.5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
              >
                {submitting ? 'Submitting…' : 'Create manual run'}
              </button>
              {createdRunId ? (
                <Link
                  to={`/runs/${createdRunId}`}
                  className="app-button-secondary rounded-xl px-4 py-2 text-sm transition"
                >
                  View created result
                </Link>
              ) : null}
            </div>
          </form>
        </SectionCard>

        <div className="space-y-6">
          <SectionCard title="Selection Preview" subtitle="Confirm the strategy and version that will back this result.">
            <dl className="space-y-4 text-sm">
              <Row label="Strategy name" value={selectedStrategy?.name} />
              <Row label="Strategy type" value={selectedStrategy ? formatStrategyType(selectedStrategy.strategy_type) : '—'} />
              <Row label="Strategy status" value={selectedStrategy ? formatStrategyStatus(selectedStrategy.status) : '—'} />
              <Row label="Version" value={selectedVersion ? `v${selectedVersion.version_number}` : '—'} />
              <Row label="Executor type" value={formatExecutorType(executorType)} />
              <Row label="Version created" value={selectedVersion ? formatDateTime(selectedVersion.created_at) : '—'} />
              <Row label="Change note" value={selectedVersion?.change_note ?? '—'} />
              {selectedBehaviorFields.map((field) => (
                <Row key={`${field.label}-${field.value}`} label={field.label} value={field.value} />
              ))}
            </dl>
          </SectionCard>

          <SectionCard title="Version Config Snapshot" subtitle="Read-only preview of the selected strategy version.">
            {selectedVersion ? (
              <pre className="app-form-code max-h-[420px] overflow-auto rounded-2xl p-4 font-mono text-xs leading-6">
                {prettyJson(sanitizeInternalValues(selectedVersion.config_json) as Record<string, unknown>)}
              </pre>
            ) : (
              <p className="text-sm app-text-muted">Choose a strategy version to inspect its config.</p>
            )}
          </SectionCard>

          <SectionCard title="What this advanced page supports" subtitle="Manual controls for experienced workflows.">
            <ul className="app-list space-y-2 text-sm">
              <li>• Create a result from an existing strategy and version.</li>
              <li>• Optionally enqueue the result immediately after creation.</li>
              <li>• Reuse the selected strategy version config as a read-only reference.</li>
              <li>• Keep request payloads explicit for advanced workflows.</li>
            </ul>
          </SectionCard>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="app-value-block rounded-2xl px-4 py-3 flex flex-col gap-1">
      <span className="text-xs font-semibold uppercase tracking-[0.18em] app-text-soft">{label}</span>
      <span className="app-title">{value || '—'}</span>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">{label}</span>
      {children}
    </label>
  );
}

function prettyJson(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2);
}

const inputClassName =
  'app-form-field w-full rounded-2xl px-4 py-3 text-sm outline-none transition';
