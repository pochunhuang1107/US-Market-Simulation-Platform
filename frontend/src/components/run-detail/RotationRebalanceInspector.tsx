import { useMemo, useState } from 'react';

import {
  formatCurrency,
  formatNumber,
  formatPct,
  formatShortDate
} from '../../lib/formatters';
import type {
  RotationRebalanceEvent,
  RotationReviewResponse,
  RotationSummaryMetrics
} from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

type RebalanceInspectorMode = 'rotation' | 'model_signal';

function formatShares(value: number | null): string {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 4
  }).format(value);
}

function formatPrice(value: number | null): string {
  if (value === null || value === undefined) return '—';
  return `$${value.toFixed(2)}`;
}

function formatSymbolList(symbols: string[]): string {
  return symbols.length > 0 ? symbols.join(', ') : 'Cash';
}

function MetricTable({ metrics }: { metrics: RotationSummaryMetrics }) {
  const rows = [
    ['Strategy return', formatPct(metrics.strategy_return_pct)],
    ['Market benchmark return', formatPct(metrics.market_benchmark_return_pct)],
    ['Universe equal-weight return', formatPct(metrics.universe_equal_weight_return_pct)],
    ['Alpha vs equal-weight universe', formatPct(metrics.alpha_vs_universe_equal_weight_pct)],
    ['Max drawdown', formatPct(metrics.max_drawdown_pct)],
    ['Rebalances', formatNumber(metrics.rebalance_count)],
    [
      'Held / universe',
      metrics.held_assets_count !== null && metrics.held_assets_count !== undefined
        ? `${formatNumber(metrics.held_assets_count)} / ${formatNumber(metrics.universe_size)}`
        : '—'
    ]
  ];

  return (
    <div className="app-table-frame overflow-auto rounded-2xl">
      <table className="min-w-full divide-y text-sm app-divider">
        <tbody className="app-table-body divide-y app-divider">
          {rows.map(([label, value]) => (
            <tr key={label}>
              <th className="app-table-head w-1/2 px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.18em]">
                {label}
              </th>
              <td className="app-title px-4 py-3 font-semibold">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RebalanceList({
  rebalances,
  selectedId,
  onSelect
}: {
  rebalances: RotationRebalanceEvent[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="app-table-frame max-h-[460px] overflow-auto rounded-2xl">
      <table className="min-w-full divide-y text-sm app-divider">
        <thead className="app-table-head sticky top-0 text-left text-xs font-semibold uppercase tracking-[0.18em]">
          <tr>
            <th className="px-4 py-3">Date</th>
            <th className="px-4 py-3">Selected</th>
            <th className="px-4 py-3">Trades</th>
            <th className="px-4 py-3">Cash</th>
          </tr>
        </thead>
        <tbody className="app-table-body divide-y app-divider">
          {rebalances.map((rebalance) => {
            const isSelected = rebalance.id === selectedId;
            return (
              <tr
                key={rebalance.id}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(rebalance.id)}
                onKeyDown={(keyboardEvent) => {
                  if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
                    keyboardEvent.preventDefault();
                    onSelect(rebalance.id);
                  }
                }}
                className={`cursor-pointer ${isSelected ? 'bg-cyan-500/10' : 'app-row-hover'}`}
              >
                <td className="app-title px-4 py-3 font-medium">{formatShortDate(rebalance.date)}</td>
                <td className="px-4 py-3">{formatSymbolList(rebalance.selected_assets)}</td>
                <td className="px-4 py-3">{formatNumber(rebalance.trades.length)}</td>
                <td className="px-4 py-3">{formatCurrency(rebalance.cash)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AssetRankTable({
  rebalance,
  mode
}: {
  rebalance: RotationRebalanceEvent;
  mode: RebalanceInspectorMode;
}) {
  if (rebalance.asset_ranks.length === 0) {
    return (
      <div className="app-text-muted text-sm">
        {mode === 'model_signal'
          ? 'No model signal rank fields were available.'
          : 'No rank or trailing return fields were available.'}
      </div>
    );
  }

  if (mode === 'model_signal') {
    return (
      <div className="app-table-frame overflow-auto rounded-xl">
        <table className="min-w-[760px] divide-y text-sm app-divider">
          <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
            <tr>
              <th className="px-3 py-2">Asset</th>
              <th className="px-3 py-2">Score</th>
              <th className="px-3 py-2">Rank</th>
              <th className="px-3 py-2">Signal date</th>
              <th className="px-3 py-2">Bucket</th>
              <th className="px-3 py-2">Target</th>
              <th className="min-w-24 px-3 py-2">Selected</th>
            </tr>
          </thead>
          <tbody className="app-table-body divide-y app-divider">
            {rebalance.asset_ranks.map((row) => (
              <tr key={row.symbol}>
                <td className="app-title px-3 py-2 font-medium">{row.symbol}</td>
                <td className="px-3 py-2">{formatNumber(row.model_score)}</td>
                <td className="px-3 py-2">{formatNumber(row.model_rank ?? row.rank)}</td>
                <td className="px-3 py-2">{row.model_signal_date ? formatShortDate(row.model_signal_date) : '-'}</td>
                <td className="px-3 py-2">{row.model_signal_bucket ?? '-'}</td>
                <td className="px-3 py-2">{formatPct(row.target_weight_pct)}</td>
                <td className="min-w-24 px-3 py-2">{row.selected ? 'Yes' : 'No'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="app-table-frame overflow-auto rounded-xl">
      <table className="min-w-full divide-y text-sm app-divider">
        <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
          <tr>
            <th className="px-3 py-2">Asset</th>
            <th className="px-3 py-2">Rank</th>
            <th className="px-3 py-2">Trailing return</th>
            <th className="px-3 py-2">Target</th>
            <th className="px-3 py-2">Selected</th>
          </tr>
        </thead>
        <tbody className="app-table-body divide-y app-divider">
          {rebalance.asset_ranks.map((row) => (
            <tr key={row.symbol}>
              <td className="app-title px-3 py-2 font-medium">{row.symbol}</td>
              <td className="px-3 py-2">{formatNumber(row.rank)}</td>
              <td className="px-3 py-2">{formatPct(row.trailing_return_pct)}</td>
              <td className="px-3 py-2">{formatPct(row.target_weight_pct)}</td>
              <td className="px-3 py-2">{row.selected ? 'Yes' : 'No'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradeTable({ rebalance }: { rebalance: RotationRebalanceEvent }) {
  if (rebalance.trades.length === 0) {
    return <div className="app-text-muted text-sm">No same-date rebalance trades were available.</div>;
  }

  return (
    <div className="app-table-frame overflow-auto rounded-xl">
      <table className="min-w-full divide-y text-sm app-divider">
        <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
          <tr>
            <th className="px-3 py-2">Action</th>
            <th className="px-3 py-2">Asset</th>
            <th className="px-3 py-2">Shares</th>
            <th className="px-3 py-2">Price</th>
            <th className="px-3 py-2">Notional</th>
          </tr>
        </thead>
        <tbody className="app-table-body divide-y app-divider">
          {rebalance.trades.map((trade, index) => (
            <tr key={`${trade.action}-${trade.symbol ?? 'asset'}-${index}`}>
              <td className="app-title px-3 py-2 font-medium">{trade.action}</td>
              <td className="px-3 py-2">{trade.symbol ?? '—'}</td>
              <td className="px-3 py-2">{formatShares(trade.shares)}</td>
              <td className="px-3 py-2">{formatPrice(trade.price)}</td>
              <td className="px-3 py-2">{formatCurrency(trade.notional)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HoldingTable({ rebalance }: { rebalance: RotationRebalanceEvent }) {
  if (rebalance.holdings.length === 0) {
    return <div className="app-text-muted text-sm">No holdings snapshot was available after this rebalance.</div>;
  }

  return (
    <div className="app-table-frame overflow-auto rounded-xl">
      <table className="min-w-full divide-y text-sm app-divider">
        <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
          <tr>
            <th className="px-3 py-2">Asset</th>
            <th className="px-3 py-2">Shares</th>
            <th className="px-3 py-2">Value</th>
            <th className="px-3 py-2">Weight</th>
          </tr>
        </thead>
        <tbody className="app-table-body divide-y app-divider">
          {rebalance.holdings.map((holding) => (
            <tr key={holding.symbol}>
              <td className="app-title px-3 py-2 font-medium">{holding.symbol}</td>
              <td className="px-3 py-2">{formatShares(holding.shares)}</td>
              <td className="px-3 py-2">{formatCurrency(holding.market_value)}</td>
              <td className="px-3 py-2">{formatPct(holding.weight_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RebalancePanel({
  rebalance,
  mode
}: {
  rebalance: RotationRebalanceEvent | null;
  mode: RebalanceInspectorMode;
}) {
  if (!rebalance) {
    return (
      <div className="app-border-soft h-full rounded-2xl border p-5">
        <div className="app-text-muted text-sm">Select a rebalance date to inspect available allocation details.</div>
      </div>
    );
  }

  return (
    <div className="app-border-soft h-full rounded-2xl border p-5">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="app-text-muted text-xs font-semibold uppercase tracking-[0.18em]">
            Rebalance
          </div>
          <h4 className="app-title mt-1 text-base font-semibold">{formatShortDate(rebalance.date)}</h4>
        </div>
        <div className="text-left text-sm sm:text-right">
          <div className="app-title font-semibold">{formatSymbolList(rebalance.selected_assets)}</div>
          <div className="app-text-muted">Cash {formatCurrency(rebalance.cash)}</div>
        </div>
      </div>

      <div className="space-y-5">
        <div>
          <div className="app-title mb-3 text-sm font-semibold">
            {mode === 'model_signal' ? 'Model signal scores' : 'Ranks / trailing returns'}
          </div>
          <AssetRankTable rebalance={rebalance} mode={mode} />
        </div>
        <div>
          <div className="app-title mb-3 text-sm font-semibold">Rebalance trades</div>
          <TradeTable rebalance={rebalance} />
        </div>
        <div>
          <div className="app-title mb-3 text-sm font-semibold">Holdings after rebalance</div>
          <HoldingTable rebalance={rebalance} />
        </div>
      </div>
    </div>
  );
}

export function RotationRebalanceInspector({
  review,
  mode = 'rotation'
}: {
  review: RotationReviewResponse;
  mode?: RebalanceInspectorMode;
}) {
  const [selectedRebalanceId, setSelectedRebalanceId] = useState<string | null>(
    review.rebalances[0]?.id ?? null
  );

  const selectedRebalance = useMemo(
    () =>
      review.rebalances.find((rebalance) => rebalance.id === selectedRebalanceId) ??
      review.rebalances[0] ??
      null,
    [review.rebalances, selectedRebalanceId]
  );

  if (review.rebalances.length === 0) {
    return (
      <SectionCard
        title={mode === 'model_signal' ? 'Model Signal Selection Inspector' : 'Rotation Rebalance Inspector'}
        subtitle={
          mode === 'model_signal'
            ? 'Selection and allocation details from available model signal artifacts.'
            : 'Selection and allocation details from available rotation artifacts.'
        }
      >
        <MetricTable metrics={review.metrics} />
        <div className="app-text-muted mt-4 text-sm">No rebalance rows were available for this result.</div>
      </SectionCard>
    );
  }

  const countCopy =
    review.total_count > review.rebalances.length
      ? `Showing ${review.rebalances.length} of ${review.total_count} rebalances.`
      : `${review.total_count} rebalances.`;

  return (
    <SectionCard
      title={mode === 'model_signal' ? 'Model Signal Selection Inspector' : 'Rotation Rebalance Inspector'}
      subtitle={
        mode === 'model_signal'
          ? `Model scores, selected assets, target weights, trades, and holdings from model signal artifacts. ${countCopy}`
          : `Selection, target weights, trades, and holdings from rotation artifacts. ${countCopy}`
      }
    >
      <div className="space-y-5">
        <MetricTable metrics={review.metrics} />
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,1fr)]">
          <RebalanceList
            rebalances={review.rebalances}
            selectedId={selectedRebalance?.id ?? null}
            onSelect={setSelectedRebalanceId}
          />
          <RebalancePanel rebalance={selectedRebalance} mode={mode} />
        </div>
      </div>
    </SectionCard>
  );
}
