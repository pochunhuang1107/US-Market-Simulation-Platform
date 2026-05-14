import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { formatDecimal, formatNumber, formatPct } from '../../lib/formatters';
import { isModelSignalRun } from '../../lib/modelSignalRunContext';
import type { RunResponse } from '../../types/api';

type Tone = 'default' | 'positive' | 'negative' | 'warning';

type InsightItem = {
  title: string;
  body: string;
  tone?: Tone;
};

type NextStep = {
  label: string;
  prompt: string;
};

function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function getSummaryNumber(summary: Record<string, unknown>, key: string): number | null {
  return toNumber(summary[key]);
}

function getDraftConfig(run: RunResponse): Record<string, unknown> | null {
  const draftConfig = run.request_payload?.draft_config;

  if (draftConfig && typeof draftConfig === 'object' && !Array.isArray(draftConfig)) {
    return draftConfig as Record<string, unknown>;
  }

  return null;
}

function getStrategySymbol(run: RunResponse): string {
  const draftConfig = getDraftConfig(run);
  const symbol = draftConfig?.tradable_symbol;

  return typeof symbol === 'string' && symbol.trim() ? symbol : 'this ETF';
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

function ResearchPromptButton({
  step,
  onOpen
}: {
  step: NextStep;
  onOpen: (prompt: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(step.prompt)}
      className="app-note inline-flex items-center gap-2 rounded-2xl px-4 py-3 text-left text-sm font-semibold transition hover:opacity-90 cursor-pointer shadow-sm"
    >
      <span>{step.label}</span>
      <span aria-hidden="true">Open in builder ↗</span>
    </button>
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
  run,
  alphaPct,
  maxDrawdownPct,
  tradeCount
}: {
  run: RunResponse;
  alphaPct: number | null;
  maxDrawdownPct: number | null;
  tradeCount: number | null;
}): NextStep[] {
  const symbol = getStrategySymbol(run);
  const steps: NextStep[] = [];

  if (maxDrawdownPct !== null && maxDrawdownPct <= -25) {
    steps.push({
      label: 'Reduce drawdown',
      prompt: `Create a variant of this ${symbol} strategy with a tighter stop loss and lower max position size.`
    });
  }

  if (alphaPct !== null && alphaPct < 0) {
    steps.push({
      label: 'Improve benchmark alpha',
      prompt: `Create a variant of this ${symbol} strategy with a different entry and exit rule to improve benchmark-relative return.`
    });
  }

  if (tradeCount !== null && tradeCount <= 5) {
    steps.push({
      label: 'Get more trade samples',
      prompt: `Create a less restrictive version of this ${symbol} strategy so it can generate more trade samples.`
    });
  }

  steps.push({
    label: 'Compare another version',
    prompt: `Create another version of this ${symbol} strategy so I can compare it against this result.`
  });

  return Array.from(
    new Map(steps.map((step) => [step.label, step])).values()
  ).slice(0, 4);
}

export function RunInsightBreakdown({ run }: { run: RunResponse }) {
  const navigate = useNavigate();
  const [openedPrompt, setOpenedPrompt] = useState<string | null>(null);
  const summary = run.summary_json ?? {};

  const totalReturnPct = getSummaryNumber(summary, 'total_return_pct');
  const benchmarkReturnPct = getSummaryNumber(summary, 'benchmark_return_pct');
  const alphaPct = getSummaryNumber(summary, 'alpha_vs_benchmark_pct');
  const maxDrawdownPct = getSummaryNumber(summary, 'max_drawdown_pct');
  const sharpeRatio = getSummaryNumber(summary, 'sharpe_ratio');
  const tradeCount = getSummaryNumber(summary, 'trade_count');
  const isModelSignal = isModelSignalRun(run);

  const insights = [
    buildReturnInsight({ totalReturnPct, benchmarkReturnPct, alphaPct }),
    buildRiskInsight({ maxDrawdownPct, sharpeRatio }),
    buildActivityInsight({ tradeCount })
  ];

  const nextSteps = isModelSignal ? [] : buildNextSteps({ run, alphaPct, maxDrawdownPct, tradeCount });

  function handleOpenPrompt(prompt: string) {
    const sourceDraftConfig = getDraftConfig(run);

    setOpenedPrompt(prompt);
    navigate('/workspace', {
      state: {
        prefillPrompt: prompt,
        source: 'run_insight',
        sourceRunId: run.id,
        sourceDraftConfig
      }
    });
  }

  return (
    <section className="app-card app-shadow rounded-[32px] border p-5">
      <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
        Result breakdown
      </div>
      <h2 className="app-title mt-2 text-xl font-semibold tracking-tight">
        What this result suggests
      </h2>
      <p className="app-text-muted mt-2 text-sm leading-6">
        Use this as a quick interpretation layer before reviewing the detailed charts and artifacts.
      </p>

      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        {insights.map((item) => (
          <InsightCard key={item.title} item={item} />
        ))}
      </div>

      {nextSteps.length > 0 ? (
        <div className="app-surface-soft mt-5 rounded-3xl border p-5">
          <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
            Suggested next research steps
          </div>
          <p className="app-text-muted mt-2 text-sm leading-6">
            Open one of these prompts in the builder to create the next strategy variant.
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {nextSteps.map((step) => (
              <ResearchPromptButton
                key={step.label}
                step={step}
                onOpen={handleOpenPrompt}
              />
            ))}
          </div>

          {openedPrompt ? (
            <div className="app-note mt-4 rounded-2xl px-4 py-3 text-sm">
              <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
                Opening builder with prompt
              </div>
              <p className="app-title mt-2 leading-6">{openedPrompt}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
