import { formatDecimal, formatNumber, formatPct } from '../../lib/formatters';
import type { RunResponse } from '../../types/api';

type Tone = 'default' | 'positive' | 'negative' | 'warning';

type InsightItem = {
  title: string;
  body: string;
  tone?: Tone;
};

function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function getSummaryNumber(summary: Record<string, unknown>, key: string): number | null {
  return toNumber(summary[key]);
}

function toneClass(tone: Tone = 'default') {
  if (tone === 'positive') return 'app-chip-success';
  if (tone === 'negative') return 'app-alert-error';
  if (tone === 'warning') return 'app-alert-warning';
  return 'app-note';
}

function InsightCard({ item }: { item: InsightItem }) {
  return (
    <div className={`${toneClass(item.tone)} rounded-3xl p-5`}>
      <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
        {item.title}
      </div>
      <p className="app-title mt-3 text-sm leading-6">{item.body}</p>
    </div>
  );
}

function buildReturnInsight({
  totalReturnPct,
  benchmarkReturnPct,
  alphaPct
}: {
  totalReturnPct: number | null;
  benchmarkReturnPct: number | null;
  alphaPct: number | null;
}): InsightItem {
  if (alphaPct !== null && alphaPct > 0) {
    return {
      title: 'Return profile',
      tone: 'positive',
      body: `Strategy return was ${formatPct(totalReturnPct)} versus benchmark return of ${formatPct(
        benchmarkReturnPct
      )}, producing ${formatPct(alphaPct)} alpha.`
    };
  }

  if (alphaPct !== null && alphaPct < 0) {
    return {
      title: 'Return profile',
      tone: 'warning',
      body: `Strategy return was ${formatPct(totalReturnPct)} versus benchmark return of ${formatPct(
        benchmarkReturnPct
      )}, trailing by ${formatPct(Math.abs(alphaPct))}.`
    };
  }

  return {
    title: 'Return profile',
    body: `Strategy return was ${formatPct(totalReturnPct)}. Benchmark comparison was ${
      benchmarkReturnPct === null ? 'not available' : formatPct(benchmarkReturnPct)
    }.`
  };
}

function buildRiskInsight({
  maxDrawdownPct,
  sharpeRatio
}: {
  maxDrawdownPct: number | null;
  sharpeRatio: number | null;
}): InsightItem {
  if (maxDrawdownPct !== null && maxDrawdownPct <= -30) {
    return {
      title: 'Risk profile',
      tone: 'warning',
      body: `Max drawdown reached ${formatPct(
        maxDrawdownPct
      )}. Review whether the return profile justifies this downside risk. Sharpe ratio was ${formatDecimal(
        sharpeRatio
      )}.`
    };
  }

  if (sharpeRatio !== null && sharpeRatio >= 1) {
    return {
      title: 'Risk profile',
      tone: 'positive',
      body: `Sharpe ratio was ${formatDecimal(
        sharpeRatio
      )}, suggesting stronger risk-adjusted behavior in this backtest. Max drawdown was ${formatPct(
        maxDrawdownPct
      )}.`
    };
  }

  return {
    title: 'Risk profile',
    body: `Max drawdown was ${formatPct(maxDrawdownPct)} and Sharpe ratio was ${formatDecimal(
      sharpeRatio
    )}. Use the drawdown chart below to understand when the strategy struggled.`
  };
}

function buildActivityInsight({ tradeCount }: { tradeCount: number | null }): InsightItem {
  if (tradeCount === 0) {
    return {
      title: 'Trading activity',
      tone: 'warning',
      body: 'No trades were detected. The entry rule may be too restrictive for this date range.'
    };
  }

  if (tradeCount !== null && tradeCount <= 5) {
    return {
      title: 'Trading activity',
      body: `The strategy only generated ${formatNumber(
        tradeCount
      )} trades. Results may be sensitive to a small number of signals.`
    };
  }

  return {
    title: 'Trading activity',
    tone: 'positive',
    body: `The strategy generated ${formatNumber(
      tradeCount
    )} trades, giving more signal samples to evaluate than a very sparse rule set.`
  };
}

function buildNextSteps({
  alphaPct,
  maxDrawdownPct,
  tradeCount
}: {
  alphaPct: number | null;
  maxDrawdownPct: number | null;
  tradeCount: number | null;
}): string[] {
  const steps: string[] = [];

  if (maxDrawdownPct !== null && maxDrawdownPct <= -25) {
    steps.push('Try a tighter stop loss or lower max position size.');
  }

  if (alphaPct !== null && alphaPct < 0) {
    steps.push('Test whether a different entry/exit rule improves benchmark-relative return.');
  }

  if (tradeCount !== null && tradeCount <= 5) {
    steps.push('Relax the entry rule or extend the backtest range to get more trade samples.');
  }

  steps.push('Compare this run against another version before deciding whether to save it.');

  return Array.from(new Set(steps)).slice(0, 4);
}

export function RunInsightBreakdown({ run }: { run: RunResponse }) {
  const summary = run.summary_json ?? {};

  const totalReturnPct = getSummaryNumber(summary, 'total_return_pct');
  const benchmarkReturnPct = getSummaryNumber(summary, 'benchmark_return_pct');
  const alphaPct = getSummaryNumber(summary, 'alpha_vs_benchmark_pct');
  const maxDrawdownPct = getSummaryNumber(summary, 'max_drawdown_pct');
  const sharpeRatio = getSummaryNumber(summary, 'sharpe_ratio');
  const tradeCount = getSummaryNumber(summary, 'trade_count');

  const insights = [
    buildReturnInsight({ totalReturnPct, benchmarkReturnPct, alphaPct }),
    buildRiskInsight({ maxDrawdownPct, sharpeRatio }),
    buildActivityInsight({ tradeCount })
  ];

  const nextSteps = buildNextSteps({ alphaPct, maxDrawdownPct, tradeCount });

  return (
    <section className="app-card app-shadow rounded-[32px] border p-5">
      <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
        Result breakdown
      </div>
      <h2 className="app-title mt-2 text-xl font-semibold tracking-tight">
        What this run suggests
      </h2>
      <p className="app-text-muted mt-2 text-sm leading-6">
        Use this as a quick interpretation layer before reviewing the detailed charts and artifacts.
      </p>

      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        {insights.map((item) => (
          <InsightCard key={item.title} item={item} />
        ))}
      </div>

      <div className="app-surface-soft mt-5 rounded-3xl border p-5">
        <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
          Suggested next research steps
        </div>
        <ul className="mt-3 space-y-2 text-sm">
          {nextSteps.map((step) => (
            <li key={step} className="app-title flex items-start gap-3">
              <span
                aria-hidden="true"
                className="mt-1 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-cyan-400/40 bg-cyan-500/10"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-cyan-300" />
              </span>
              <span className="min-w-0 leading-6">{step}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}