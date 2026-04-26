import { formatNumber, formatPct, formatRunLabel } from '../../lib/formatters';
import type { RunComparisonResponse, RunComparisonSummary } from '../../types/api';

type MetricWinner = {
  label: string;
  run: RunComparisonSummary | null;
  value: string;
  description: string;
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function getRunLabel(run: RunComparisonSummary) {
  return formatRunLabel(run.strategy_name, run.strategy_version_number, run.run_id);
}

function pickBestRun(
  runs: RunComparisonSummary[],
  selector: (run: RunComparisonSummary) => number | null,
  higherIsBetter = true
) {
  const candidates = runs
    .map((run) => ({ run, value: selector(run) }))
    .filter((item): item is { run: RunComparisonSummary; value: number } => isFiniteNumber(item.value));

  if (candidates.length === 0) return null;

  return candidates.sort((a, b) =>
    higherIsBetter ? b.value - a.value : a.value - b.value
  )[0];
}

function buildWinnerCards(runs: RunComparisonSummary[]): MetricWinner[] {
  const bestReturn = pickBestRun(runs, (run) => run.total_return_pct);
  const bestAlpha = pickBestRun(runs, (run) => run.alpha_vs_benchmark_pct);
  const bestSharpe = pickBestRun(runs, (run) => run.sharpe_ratio);
  const smallestDrawdown = pickBestRun(runs, (run) => run.max_drawdown_pct);

  return [
    {
      label: 'Best return',
      run: bestReturn?.run ?? null,
      value: bestReturn ? formatPct(bestReturn.value) : '—',
      description: bestReturn
        ? `${getRunLabel(bestReturn.run)} had the highest total return.`
        : 'Total return was not available.'
    },
    {
      label: 'Best alpha',
      run: bestAlpha?.run ?? null,
      value: bestAlpha ? formatPct(bestAlpha.value) : '—',
      description: bestAlpha
        ? `${getRunLabel(bestAlpha.run)} had the strongest benchmark-relative return.`
        : 'Alpha was not available.'
    },
    {
      label: 'Best Sharpe',
      run: bestSharpe?.run ?? null,
      value: bestSharpe ? formatNumber(bestSharpe.value) : '—',
      description: bestSharpe
        ? `${getRunLabel(bestSharpe.run)} had the best risk-adjusted score.`
        : 'Sharpe ratio was not available.'
    },
    {
      label: 'Smallest drawdown',
      run: smallestDrawdown?.run ?? null,
      value: smallestDrawdown ? formatPct(smallestDrawdown.value) : '—',
      description: smallestDrawdown
        ? `${getRunLabel(smallestDrawdown.run)} had the shallowest max drawdown.`
        : 'Drawdown was not available.'
    }
  ];
}

function buildTakeaway(runs: RunComparisonSummary[]) {
  const bestReturn = pickBestRun(runs, (run) => run.total_return_pct);
  const bestSharpe = pickBestRun(runs, (run) => run.sharpe_ratio);
  const smallestDrawdown = pickBestRun(runs, (run) => run.max_drawdown_pct);

  if (!bestReturn && !bestSharpe && !smallestDrawdown) {
    return 'Comparison data is available, but there is not enough metric coverage to produce a clear takeaway.';
  }

  if (
    bestReturn &&
    bestSharpe &&
    smallestDrawdown &&
    bestReturn.run.run_id === bestSharpe.run.run_id &&
    bestReturn.run.run_id === smallestDrawdown.run.run_id
  ) {
    return `${getRunLabel(bestReturn.run)} currently looks strongest across return, Sharpe, and drawdown.`;
  }

  if (bestReturn && bestSharpe && bestReturn.run.run_id !== bestSharpe.run.run_id) {
    return `${getRunLabel(bestReturn.run)} led on return, while ${getRunLabel(
      bestSharpe.run
    )} had better risk-adjusted behavior. Review the drawdown charts before choosing between them.`;
  }

  if (bestReturn) {
    return `${getRunLabel(bestReturn.run)} led on total return. Use the chart overlays to check whether that came with larger drawdowns.`;
  }

  return 'Review the metric winners and chart overlays to decide which run is more attractive.';
}

function WinnerCard({ winner }: { winner: MetricWinner }) {
  return (
    <div className="app-surface-soft rounded-3xl border p-4">
      <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
        {winner.label}
      </div>
      <div className="app-title mt-2 text-xl font-semibold">{winner.value}</div>
      <p className="app-text-muted mt-2 text-sm leading-6">{winner.description}</p>
    </div>
  );
}

export function ComparisonInsightSummary({ comparison }: { comparison: RunComparisonResponse }) {
  const winners = buildWinnerCards(comparison.runs);
  const takeaway = buildTakeaway(comparison.runs);

  return (
    <section className="app-card app-shadow rounded-[32px] border p-5">
      <div className="app-label text-xs font-semibold uppercase tracking-[0.22em]">
        Comparison insight
      </div>
      <h2 className="app-title mt-2 text-xl font-semibold tracking-tight">
        Which run looks stronger?
      </h2>
      <p className="app-text-muted mt-2 text-sm leading-6">{takeaway}</p>

      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {winners.map((winner) => (
          <WinnerCard key={winner.label} winner={winner} />
        ))}
      </div>
    </section>
  );
}
