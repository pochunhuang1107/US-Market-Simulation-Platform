import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { RunCharts } from '../components/run-detail/RunCharts';
import { RunInsightHero } from '../components/run-detail/RunInsightHero';
import { MetricCard } from '../components/shared/MetricCard';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchSweepVariantDetail } from '../lib/api';
import { formatDecimal, formatNumber, formatPct } from '../lib/formatters';
import {
  formatParameterLabel,
  formatParameterValue,
  formatRankingMetricName,
  isRecord,
  sortedParameterEntries,
  toNumber
} from '../lib/sweepVariants';
import type { RunResponse, SweepVariantDetailResponse } from '../types/api';

function getVariantId(variant: Record<string, unknown>, fallback: string | undefined): string {
  return typeof variant.variant_id === 'string' && variant.variant_id.trim() ? variant.variant_id : fallback ?? '';
}

function getConfig(variant: Record<string, unknown>): Record<string, unknown> | null {
  return isRecord(variant.config) ? variant.config : null;
}

function getMetricTone(value: number | null, positiveIsGood = true) {
  if (value === null || value === 0) return 'default' as const;
  if (positiveIsGood) return value > 0 ? ('positive' as const) : ('negative' as const);
  return value < 0 ? ('positive' as const) : ('negative' as const);
}

function shortRunId(runId: string | undefined): string {
  return (runId ?? '').split('-')[0] || 'run';
}

function getVariantRows(data: SweepVariantDetailResponse): Record<string, unknown>[] {
  const results = data.run.summary_json?.results;
  return Array.isArray(results) ? results.filter(isRecord) : [];
}

function rankingValue(row: Record<string, unknown>, metric: string): number {
  const value = toNumber(row[metric]);
  if (value === null) return Number.NEGATIVE_INFINITY;
  if (metric === 'max_drawdown_pct') {
    return value <= 0 ? value : -value;
  }
  return value;
}

function rankForMetric(data: SweepVariantDetailResponse, variantId: string, metric: string): number {
  const ranked = getVariantRows(data).sort((left, right) => rankingValue(right, metric) - rankingValue(left, metric));
  const index = ranked.findIndex((row) => row.variant_id === variantId);
  return index === -1 ? data.rank : index + 1;
}

export function SweepVariantDetailPage() {
  const { runId, variantId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [data, setData] = useState<SweepVariantDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    async function load() {
      if (!runId || !variantId) {
        setErrorMessage('Missing sweep variant route parameters.');
        setLoading(false);
        return;
      }

      setLoading(true);
      setErrorMessage(null);

      try {
        const response = await fetchSweepVariantDetail(runId, variantId);
        if (!ignore) {
          setData(response);
        }
      } catch (error) {
        if (!ignore) {
          setData(null);
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load sweep variant.');
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      ignore = true;
    };
  }, [runId, variantId]);

  const config = data ? getConfig(data.variant) : null;
  const displayRun = useMemo<RunResponse | null>(() => {
    if (!data) return null;
    return {
      ...data.run,
      strategy_name: 'Sweep variant',
      summary_json: data.variant,
      request_payload: {
        ...data.run.request_payload,
        draft_config: config ?? undefined
      }
    };
  }, [config, data]);

  function handleEditAsNewVersion() {
    if (!runId || !variantId || !data || !data.run.strategy_id || !config) return;

    const rankingMetric = searchParams.get('rankingMetric') || data.ranking_metric || 'sharpe_ratio';
    const rank = rankForMetric(data, variantId, rankingMetric);
    const changeNote = `Promoted from parameter sweep run ${shortRunId(runId)}, rank #${rank} by ${formatRankingMetricName(rankingMetric)}.`;
    const query = new URLSearchParams({
      sweepRunId: runId,
      variantId,
      rankingMetric
    });

    navigate(`/strategies/${data.run.strategy_id}/versions/new?${query.toString()}`, {
      state: {
        builderDraft: {
          configText: JSON.stringify(config, null, 2),
          changeNote,
          sourceLabel: 'parameter sweep variant'
        }
      }
    });
  }

  if (loading) {
    return <StateCard title="Loading sweep variant" description="Fetching the selected variant metrics and config." />;
  }

  if (errorMessage || !data) {
    return <StateCard title="Unable to load sweep variant" description={errorMessage ?? 'Variant detail was not available.'} tone="error" />;
  }

  const variant = data.variant;
  const resolvedVariantId = getVariantId(variant, variantId);
  const rankingMetric = searchParams.get('rankingMetric') || data.ranking_metric || 'sharpe_ratio';
  const displayRank = variantId ? rankForMetric(data, variantId, rankingMetric) : data.rank;
  const parameterRows = sortedParameterEntries(variant.parameters);
  const hasChartData = Boolean(data.chart_data && data.chart_data.equity_curve.length > 0);

  const metrics = [
    { label: 'Total Return', value: formatPct(toNumber(variant.total_return_pct)), tone: getMetricTone(toNumber(variant.total_return_pct)) },
    { label: 'Benchmark Return', value: formatPct(toNumber(variant.benchmark_return_pct)), tone: getMetricTone(toNumber(variant.benchmark_return_pct)) },
    { label: 'Alpha', value: formatPct(toNumber(variant.alpha_vs_benchmark_pct)), tone: getMetricTone(toNumber(variant.alpha_vs_benchmark_pct)) },
    { label: 'CAGR', value: formatPct(toNumber(variant.cagr_pct)), tone: getMetricTone(toNumber(variant.cagr_pct)) },
    { label: 'Sharpe', value: formatDecimal(toNumber(variant.sharpe_ratio)) },
    { label: 'Max Drawdown', value: formatPct(toNumber(variant.max_drawdown_pct)), tone: 'negative' as const },
    { label: 'Trades', value: formatNumber(toNumber(variant.trade_count)) }
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={`Sweep run ${shortRunId(data.run.id)}`}
        title="Sweep Variant"
        description={`Rank #${displayRank || '?'} by ${formatRankingMetricName(rankingMetric)}.`}
        actions={
          <>
            <Link
              to={`/runs/${data.run.id}`}
              className="app-button-secondary rounded-xl px-4 py-2 text-sm font-semibold transition"
            >
              Back to sweep
            </Link>
            {data.run.strategy_id ? (
              <button
                type="button"
                onClick={handleEditAsNewVersion}
                className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition"
              >
                Edit as new version
              </button>
            ) : (
              <span className="app-button-secondary rounded-xl px-4 py-2 text-sm font-semibold opacity-60">
                Save as strategy draft
              </span>
            )}
          </>
        }
      />

      {!data.run.strategy_id ? (
        <div className="app-note rounded-2xl border px-4 py-3 text-sm">
          Saving standalone sweep variants will be added next.
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-7">
        {metrics.map((metric) => (
          <MetricCard key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />
        ))}
      </div>

      <SectionCard title="Changed Parameters" subtitle="Parameters changed from the sweep base config.">
        {parameterRows.length > 0 ? (
          <dl className="grid gap-3 md:grid-cols-2">
            {parameterRows.map(([path, value]) => (
              <div key={path} className="app-surface-soft rounded-2xl border px-4 py-3">
                <dt className="app-label text-[11px] font-semibold uppercase tracking-[0.18em]">
                  {formatParameterLabel(path)}
                </dt>
                <dd className="app-title mt-2 text-sm font-semibold">{formatParameterValue(value)}</dd>
                <dd className="app-text-soft mt-1 text-xs">{path}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="app-text-muted text-sm">No parameter changes were recorded for this variant.</p>
        )}
      </SectionCard>

      {hasChartData && data.chart_data && displayRun ? (
        <>
          <RunInsightHero run={displayRun} chartData={data.chart_data} />
          <RunCharts run={displayRun} chartData={data.chart_data} />
        </>
      ) : (
        <div className="app-note rounded-2xl border px-4 py-3 text-sm">
          Variant chart artifacts are not available yet. Metrics and config are available.
        </div>
      )}

      <SectionCard title="Variant Config" subtitle={`Strategy V2 config for variant ${resolvedVariantId}.`}>
        <details className="app-surface-soft rounded-2xl border px-4 py-3">
          <summary className="cursor-pointer text-sm font-semibold app-title">
            View read-only JSON
          </summary>
          <pre className="app-text-muted mt-4 max-h-[520px] overflow-auto text-xs leading-5">
            {JSON.stringify(config ?? {}, null, 2)}
          </pre>
        </details>
      </SectionCard>
    </div>
  );
}
