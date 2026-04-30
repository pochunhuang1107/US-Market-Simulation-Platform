import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { VersionsTable } from '../components/strategy/VersionsTable';
import { RunsTable } from '../components/runs/RunsTable';
import { MetricCard } from '../components/shared/MetricCard';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { archiveStrategy, createRun, enqueueRun, fetchStrategyDashboard, restoreStrategy } from '../lib/api';
import {
  formatDateTime,
  formatPct,
  formatSavedSweepVariantSource,
  isSavedSweepVariantResult
} from '../lib/formatters';
import type { StrategyDashboardResponse, StrategyVersionSummary } from '../types/api';

function formatStrategyType(value: string | null | undefined) {
  if (!value) return 'Strategy';

  const labels: Record<string, string> = {
    SINGLE_ASSET: 'Single ETF',
    SIMULATION: 'Single ETF',
    PORTFOLIO: 'Portfolio',
    COMPARISON: 'Comparison',
    PARAMETER_SWEEP: 'Parameter Sweep'
  };

  if (labels[value]) return labels[value];

  return value
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function hasConfig(value: Record<string, unknown> | null | undefined) {
  return Boolean(value && Object.keys(value).length > 0);
}

function getRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function formatConfigValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/\.?0+$/, '');
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
  if (Array.isArray(value)) return value.map(formatConfigValue).join(', ');
  return String(value);
}

function formatConfigPct(value: unknown): string | null {
  if (typeof value !== 'number') return null;
  return `${(value * 100).toFixed(1).replace(/\.0$/, '')}%`;
}

function summarizeAtomicRule(rule: Record<string, unknown>): string {
  const type = String(rule.type ?? 'rule').replace(/_/g, ' ');
  const symbol = formatConfigValue(rule.symbol ?? 'asset');
  const lookback = rule.lookback ?? 14;
  const threshold = formatConfigValue(rule.threshold);
  const fastWindow = rule.fast_window;
  const slowWindow = rule.slow_window;

  if (rule.type === 'rsi_below') return `${symbol} RSI(${lookback}) below ${threshold}`;
  if (rule.type === 'rsi_above') return `${symbol} RSI(${lookback}) above ${threshold}`;
  if (rule.type === 'sma_above') return `${symbol} ${formatConfigValue(fastWindow)}-day SMA above ${formatConfigValue(slowWindow)}-day SMA`;
  if (rule.type === 'sma_cross_above') return `${symbol} SMA crosses above ${formatConfigValue(slowWindow)}-day SMA`;
  if (rule.type === 'sma_cross_below') return `${symbol} SMA crosses below ${formatConfigValue(slowWindow)}-day SMA`;
  if (rule.type === 'relative_return_above') {
    return `${symbol} beats ${formatConfigValue(rule.reference_symbol ?? 'reference')} over ${formatConfigValue(rule.lookback)} bars`;
  }

  return type;
}

function summarizeRule(value: unknown): string {
  const rule = getRecord(value);
  if (!rule) return '—';

  if (rule.kind === 'atomic') return summarizeAtomicRule(rule);
  if (rule.kind === 'not') return `Not: ${summarizeRule(rule.rule)}`;
  if (rule.kind === 'window') return `${formatConfigValue(rule.mode ?? 'Any')} within ${formatConfigValue(rule.window_bars)} bars: ${summarizeRule(rule.rule)}`;
  if (rule.kind === 'sequence') {
    const steps = Array.isArray(rule.steps) ? rule.steps.map(summarizeRule).filter((item) => item !== '—') : [];
    return steps.length ? `${steps.join(' then ')} within ${formatConfigValue(rule.window_bars)} bars` : 'Sequence rule';
  }
  if (rule.kind === 'group') {
    const joiner = String(rule.operator ?? 'AND').toUpperCase() === 'OR' ? ' or ' : ' and ';
    const rules = Array.isArray(rule.rules) ? rule.rules.map(summarizeRule).filter((item) => item !== '—') : [];
    return rules.length ? rules.join(joiner) : `${formatConfigValue(rule.operator ?? 'Group')} rule`;
  }

  return String(rule.type ?? rule.kind ?? 'Rule').replace(/_/g, ' ');
}

function selectedVersionLabel(version: StrategyVersionSummary | null): string {
  if (!version) return 'No version selected';
  return `v${version.version_number}${version.is_current ? ' · Current' : ''}${version.reference_run_id ? ' · Reference result' : ' · No reference result yet'}`;
}

function configSummaryRows(config: Record<string, unknown> | null | undefined) {
  if (!config) return [];

  const risk = getRecord(config.risk);
  const allocation = getRecord(config.allocation);
  const coreOverlay = getRecord(config.core_overlay);
  const dateRange = [config.start_date, config.end_date].filter(Boolean).map(formatConfigValue).join(' to ');
  const riskParts = [
    risk?.stop_loss_pct !== undefined ? `Stop ${formatConfigPct(risk.stop_loss_pct) ?? formatConfigValue(risk.stop_loss_pct)}` : null,
    risk?.take_profit_pct !== undefined ? `Take profit ${formatConfigPct(risk.take_profit_pct) ?? formatConfigValue(risk.take_profit_pct)}` : null,
    risk?.cooldown_bars !== undefined ? `Cooldown ${formatConfigValue(risk.cooldown_bars)} bars` : null,
    allocation?.entry_value !== undefined ? `Position ${formatConfigPct(allocation.entry_value) ?? formatConfigValue(allocation.entry_value)}` : null
  ].filter(Boolean);
  const coreOverlayText = coreOverlay
    ? [
        `Core ${coreOverlay.enabled ? 'enabled' : 'disabled'}`,
        coreOverlay.core_allocation_pct !== undefined ? formatConfigPct(coreOverlay.core_allocation_pct) : null
      ].filter(Boolean).join(' · ')
    : null;

  return [
    { label: 'Tradable symbol', value: formatConfigValue(config.tradable_symbol) },
    { label: 'Benchmark', value: formatConfigValue(config.benchmark_symbol ?? config.benchmark) },
    { label: 'Date range', value: dateRange || '—' },
    { label: 'Entry rule', value: summarizeRule(config.entry_rule) },
    { label: 'Exit rule', value: summarizeRule(config.exit_rule) },
    { label: 'Risk controls', value: riskParts.length ? riskParts.join(' · ') : '—' },
    { label: 'Core / overlay', value: coreOverlayText ?? '—' }
  ];
}

type PageNotice = {
  tone: 'success' | 'info' | 'error';
  message: string;
};

export function StrategyPage() {
  const { strategyId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<StrategyDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusActionLoading, setStatusActionLoading] = useState(false);
  const [runVersionLoading, setRunVersionLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [statusActionError, setStatusActionError] = useState<string | null>(null);
  const [runVersionError, setRunVersionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<PageNotice | null>(
    (location.state as { notice?: PageNotice } | null)?.notice ?? null
  );

  const loadStrategy = useCallback(
    async (shouldIgnore: () => boolean = () => false) => {
      if (!strategyId) {
        setLoading(false);
        setErrorMessage('Missing strategy id');
        return;
      }

      setErrorMessage(null);

      try {
        const response = await fetchStrategyDashboard(strategyId);
        if (!shouldIgnore()) {
          setData(response);
        }
      } catch (error) {
        if (!shouldIgnore()) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load strategy dashboard');
          setData(null);
        }
      } finally {
        if (!shouldIgnore()) {
          setLoading(false);
        }
      }
    },
    [strategyId]
  );

  useEffect(() => {
    let ignore = false;

    setLoading(true);
    void loadStrategy(() => ignore);
    return () => {
      ignore = true;
    };
  }, [loadStrategy]);

  const currentVersion = useMemo(() => {
    if (!data) return null;
    return data.versions.find((version) => version.is_current) ?? data.versions[0] ?? null;
  }, [data]);

  const selectedVersion = useMemo(() => {
    if (!data) return null;

    const versionId = searchParams.get('versionId');
    if (versionId) {
      const version = data.versions.find((item) => item.id === versionId);
      return version ?? currentVersion;
    }

    const versionNumberParam = searchParams.get('version');
    if (versionNumberParam) {
      const versionNumber = Number(versionNumberParam);
      if (Number.isInteger(versionNumber)) {
        const version = data.versions.find((item) => item.version_number === versionNumber);
        if (version) return version;
      }
    }

    return currentVersion;
  }, [currentVersion, data, searchParams]);

  useEffect(() => {
    if (!selectedVersion) return;

    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('versionId', selectedVersion.id);
    nextParams.delete('version');

    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true });
    }
  }, [searchParams, selectedVersion, setSearchParams]);

  const referencePerformance =
    selectedVersion?.reference_performance ??
    (selectedVersion?.id === currentVersion?.id ? data?.reference_performance ?? null : null);
  const referenceRunId = selectedVersion?.reference_run_id ?? referencePerformance?.run_id ?? null;
  const referenceFinishedAt =
    referencePerformance?.finished_at ??
    (selectedVersion?.id === currentVersion?.id ? data?.reference_finished_at ?? null : null);

  const referenceMetrics = useMemo(() => {
    const reference = referencePerformance;
    if (!reference) return [];

    return [
      { label: 'Reference Total Return', value: formatPct(reference.total_return_pct) },
      { label: 'Reference Benchmark Return', value: formatPct(reference.benchmark_return_pct) },
      {
        label: 'Reference Alpha',
        value: formatPct(reference.alpha_vs_benchmark_pct),
        tone: (reference.alpha_vs_benchmark_pct ?? 0) >= 0 ? ('positive' as const) : ('negative' as const)
      },
      { label: 'Reference CAGR', value: formatPct(reference.cagr_pct) }
    ];
  }, [referencePerformance]);

  const selectedConfig = selectedVersion?.config_json ?? null;
  const selectedVersionRuns = useMemo(
    () =>
      selectedVersion
        ? data?.associated_runs.filter((run) => run.strategy_version_id === selectedVersion.id) ?? []
        : [],
    [data, selectedVersion]
  );
  const selectedConfigRows = useMemo(() => configSummaryRows(selectedConfig), [selectedConfig]);
  const strategyStatus = data?.strategy.status?.toUpperCase();
  const isArchived = strategyStatus === 'ARCHIVED';
  const isActive = strategyStatus === 'ACTIVE';
  const canContinueInChat = hasConfig(selectedConfig);
  const chatState = canContinueInChat
    ? {
        source: 'strategy',
        sourceDraftConfig: selectedConfig,
        prefillPrompt: `Create a draft variant of ${data?.strategy.name ?? 'this strategy'} v${selectedVersion?.version_number ?? ''}.`
      }
    : undefined;
  const noticeClass =
    notice?.tone === 'error'
      ? 'app-alert-error'
      : notice?.tone === 'info'
        ? 'app-note'
        : 'app-alert-success';
  const referenceIsSavedSweepVariant = referencePerformance ? isSavedSweepVariantResult(referencePerformance) : false;

  function handleSelectVersion(version: StrategyVersionSummary) {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set('versionId', version.id);
    nextParams.delete('version');
    setSearchParams(nextParams);
  }

  async function handleStatusAction() {
    if (!strategyId || !data) return;

    if (isActive) {
      const confirmed = window.confirm('Archive this strategy? It will leave the active library, but versions and results stay available.');
      if (!confirmed) return;
    }

    setStatusActionLoading(true);
    setStatusActionError(null);

    try {
      if (isArchived) {
        await restoreStrategy(strategyId);
      } else {
        await archiveStrategy(strategyId);
      }
      await loadStrategy();
    } catch (error) {
      setStatusActionError(error instanceof Error ? error.message : 'Failed to update strategy status');
    } finally {
      setStatusActionLoading(false);
    }
  }

  async function handleRunSelectedVersion() {
    if (!strategyId || !selectedVersion) return;

    setRunVersionLoading(true);
    setRunVersionError(null);

    try {
      const requestPayload: Record<string, unknown> = {
        source: 'strategy_version_reference_run',
        set_as_reference_on_success: true,
        reference_strategy_version_id: selectedVersion.id
      };
      if (typeof selectedVersion.config_json.start_date === 'string') {
        requestPayload.start_date = selectedVersion.config_json.start_date;
      }
      if (typeof selectedVersion.config_json.end_date === 'string') {
        requestPayload.end_date = selectedVersion.config_json.end_date;
      }

      const run = await createRun({
        strategy_id: strategyId,
        strategy_version_id: selectedVersion.id,
        run_type: 'SIMULATION',
        executor_type: 'SIMULATION_EXECUTOR',
        request_payload: requestPayload,
        max_attempts: 1
      });
      await enqueueRun(run.id);
      navigate(`/runs/${run.id}`);
    } catch (error) {
      setRunVersionError(error instanceof Error ? error.message : 'Failed to run this version');
    } finally {
      setRunVersionLoading(false);
    }
  }

  if (loading) {
    return <StateCard title="Loading strategy dashboard" description="Fetching strategy metadata, versions, and associated results." />;
  }

  if (errorMessage || !data) {
    return <StateCard title="Unable to load strategy" description={errorMessage ?? 'Strategy dashboard was not available.'} tone="error" />;
  }

  return (
    <div className="space-y-6">
      {notice ? (
        <div className={`${noticeClass} rounded-2xl border px-4 py-3 text-sm`}>
          <div className="flex items-start justify-between gap-4">
            <p>{notice.message}</p>
            <button
              type="button"
              onClick={() => setNotice(null)}
              className="text-xs font-semibold uppercase tracking-[0.2em] opacity-80 transition hover:opacity-100"
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      <PageHeader
        eyebrow="Strategy Library"
        title={data.strategy.name}
        description={data.strategy.description ?? 'No strategy description was provided.'}
        actions={
          <div className="flex items-center gap-3">
            <Link
              to="/strategies"
              className="app-button-secondary rounded-xl px-4 py-2 text-sm transition"
            >
              Back to Strategy Library
            </Link>
            {isActive || isArchived ? (
              <button
                type="button"
                onClick={() => void handleStatusAction()}
                disabled={statusActionLoading}
                className="app-button-secondary rounded-xl px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isArchived ? 'Restore strategy' : 'Archive strategy'}
              </button>
            ) : null}
          </div>
        }
      />

      {statusActionError ? <StateCard title="Could not update strategy status" description={statusActionError} tone="error" /> : null}
      {runVersionError ? <StateCard title="Could not run version" description={runVersionError} tone="error" /> : null}

      <section className="app-card app-shadow-soft rounded-3xl border p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
              Selected Version
            </div>
            <h2 className="app-title mt-2 text-2xl font-semibold">
              {selectedVersion ? `v${selectedVersion.version_number}` : 'No version'}
            </h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {selectedVersion?.is_current ? (
                <span className="app-chip-info rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em]">
                  Current
                </span>
              ) : null}
              <span className={`${referenceRunId ? 'app-chip-success' : 'app-surface-soft app-text-muted'} rounded-full border px-3 py-1 text-xs font-semibold`}>
                {referenceRunId ? `Reference ${referenceRunId.split('-')[0]}` : 'No reference result yet'}
              </span>
            </div>
          </div>
          <label className="flex min-w-[240px] flex-col gap-2">
            <span className="app-label text-xs font-semibold uppercase tracking-[0.18em]">Version selector</span>
            <select
              value={selectedVersion?.id ?? ''}
              onChange={(event) => {
                const version = data.versions.find((item) => item.id === event.target.value);
                if (version) handleSelectVersion(version);
              }}
              className="app-version-input rounded-2xl px-4 py-3 text-sm font-semibold outline-none"
            >
              {data.versions.map((version) => (
                <option key={version.id} value={version.id}>
                  {selectedVersionLabel(version)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      <section className="app-card app-shadow-soft rounded-3xl border p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
              Continue Research
            </div>
            <p className="app-text-muted mt-2 text-sm leading-6">
              Open the selected version's reference result, compare reference performance, or continue from that saved config in chat.
            </p>
            {referenceIsSavedSweepVariant && referencePerformance ? (
              <div className="app-note mt-3 inline-flex flex-wrap items-center gap-2 rounded-2xl border px-3 py-2 text-xs">
                <span>{formatSavedSweepVariantSource(referencePerformance)}</span>
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {referenceRunId ? (
              <Link
                to={`/runs/${referenceRunId}`}
                className="app-button-primary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Open reference result
              </Link>
            ) : (
              <span className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold opacity-60">
                Open reference result
              </span>
            )}
            {referenceRunId ? (
              <Link
                to={`/compare?runIds=${referenceRunId}`}
                className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Compare reference result
              </Link>
            ) : (
              <span className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold opacity-60">
                Compare reference result
              </span>
            )}
            {canContinueInChat ? (
              <Link
                to="/chat"
                state={chatState}
                className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
              >
                Continue in Chat
              </Link>
            ) : null}
            <Link
              to={`/strategies/${data.strategy.id}/versions/new${selectedVersion ? `?fromVersionId=${selectedVersion.id}` : ''}`}
              className="app-button-secondary rounded-xl px-3 py-2 text-sm font-semibold transition"
            >
              New Version
            </Link>
            {!referenceRunId ? (
              <button
                type="button"
                onClick={() => void handleRunSelectedVersion()}
                disabled={!selectedVersion || runVersionLoading}
                className="app-button-primary rounded-xl px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
              >
                {runVersionLoading ? 'Creating result...' : 'Run this version'}
              </button>
            ) : null}
          </div>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <SectionCard title="Saved Strategy" subtitle="Core metadata and saved-strategy status.">
          <dl className="space-y-4 text-sm">
            <Row label="Type" value={formatStrategyType(data.strategy.strategy_type)} />
            <Row label="Created" value={formatDateTime(data.strategy.created_at)} />
            <Row label="Updated" value={formatDateTime(data.strategy.updated_at)} />
            <Row label="Total results" value={String(data.total_runs)} />
            <Row label="Selected version" value={selectedVersion ? `v${selectedVersion.version_number}` : '—'} />
            <Row label="Reference finished at" value={formatDateTime(referenceFinishedAt)} />
            <div className="flex flex-wrap gap-2 pt-1">
              <span className="app-surface-soft app-text-muted rounded-full border px-3 py-1 text-xs">
                {formatStrategyType(data.strategy.status)}
              </span>
              <span className="app-surface-soft app-text-muted rounded-full border px-3 py-1 text-xs">
                {formatStrategyType(data.strategy.visibility)}
              </span>
            </div>
          </dl>
        </SectionCard>

        <section className="app-card app-shadow-soft rounded-3xl border p-5 lg:p-6">
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="app-label text-xs font-semibold uppercase tracking-[0.22em]">Key Insight</p>
              <h3 className="app-title mt-2 text-xl font-semibold">Reference Performance</h3>
              <p className="app-text-muted mt-1 text-sm">
                Pinned result for {selectedVersion ? `v${selectedVersion.version_number}` : 'the selected version'}.
              </p>
            </div>
          </div>
          {referencePerformance ? (
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                {referenceMetrics.map((metric) => (
                  <MetricCard key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />
                ))}
              </div>
            </div>
          ) : (
            <div className="app-surface-soft rounded-2xl border px-4 py-5">
              <p className="app-title text-sm font-semibold">No reference result yet</p>
              <p className="app-text-muted mt-2 text-sm">Run this version to create a reference result.</p>
              <button
                type="button"
                onClick={() => void handleRunSelectedVersion()}
                disabled={!selectedVersion || runVersionLoading}
                className="app-button-primary mt-4 rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
              >
                {runVersionLoading ? 'Creating result...' : 'Run this version'}
              </button>
            </div>
          )}
        </section>
      </div>

      <SectionCard
        title="Version Config Summary"
        subtitle={selectedVersion ? `Read-only summary for v${selectedVersion.version_number}.` : 'Read-only summary for the selected version.'}
      >
        <div className="grid gap-3 md:grid-cols-2">
          {selectedConfigRows.map((row) => (
            <Row key={row.label} label={row.label} value={row.value} />
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Versions" subtitle="Select any saved version. The current version remains marked for orientation.">
        <VersionsTable versions={data.versions} selectedVersionId={selectedVersion?.id ?? null} onSelectVersion={handleSelectVersion} />
      </SectionCard>

      <SectionCard
        title={selectedVersion ? `Results for v${selectedVersion.version_number}` : 'Result History'}
        subtitle="Recent simulations created from the selected saved strategy version."
      >
        <RunsTable
          runs={selectedVersionRuns}
          loading={false}
          compact
          referenceRunId={referenceRunId}
          emptyTitle={selectedVersion ? `No results recorded for v${selectedVersion.version_number}.` : undefined}
          emptyDescription="Run this version to create its first research result."
        />
      </SectionCard>
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string | null | undefined; mono?: boolean }) {
  return (
    <div className="app-surface-soft flex flex-col gap-1 rounded-2xl border px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <dt className="app-label text-xs font-semibold uppercase tracking-[0.18em]">{label}</dt>
      <dd className={`${mono ? 'font-mono text-xs break-all' : 'text-sm font-medium'} app-title sm:text-right`}>{value || '—'}</dd>
    </div>
  );
}
