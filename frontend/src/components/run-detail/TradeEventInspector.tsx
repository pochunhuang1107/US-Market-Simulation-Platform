import { useEffect, useMemo, useState } from 'react';

import {
  artifactUnavailableMessage,
  fetchRunTradeEvents,
  fetchSweepVariantTradeEvents,
  isArtifactUnavailableError
} from '../../lib/api';
import { formatShortDate } from '../../lib/formatters';
import type {
  TradeCapitalContext,
  TradeEventContext,
  TradeEventContextResponse,
  TradeEventRuleContext
} from '../../types/api';
import { SectionCard } from '../shared/SectionCard';

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

function formatCurrency(value: number | null): string {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2
  }).format(value);
}

function formatPercent(value: number | null): string {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(2)}%`;
}

function formatValue(value: string | number | boolean): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return value;
}

function eventTitle(event: TradeEventContext): string {
  const date = event.date ? formatShortDate(event.date) : 'Unknown date';
  return `${event.action} · ${date}`;
}

function operatorSymbol(operator: string | null): string | null {
  if (operator === 'below') return '<';
  if (operator === 'above') return '>';
  return operator;
}

function formatRule(context: TradeEventRuleContext): string {
  const operator = operatorSymbol(context.operator);
  if (!operator || context.threshold === null || context.threshold === undefined) return '—';
  return `${operator} ${formatValue(context.threshold)}`;
}

function formatStatus(context: TradeEventRuleContext): string {
  if (context.actual_value === null || context.actual_value === undefined) return 'unavailable';
  return context.status || context.result || 'unknown';
}

function tradeSizePctOfEquity(context: TradeCapitalContext): number | null {
  if (
    context.trade_notional === null ||
    context.trade_notional === undefined ||
    context.equity_before_trade === null ||
    context.equity_before_trade === undefined ||
    context.equity_before_trade === 0
  ) {
    return null;
  }
  return (context.trade_notional / context.equity_before_trade) * 100;
}

function shouldShowSmallAddHint(event: TradeEventContext): boolean {
  const context = event.capital_context;
  if (!context || event.action.toUpperCase() !== 'BUY_ADD') return false;

  const tradePct = tradeSizePctOfEquity(context);
  const remainingCapacityPct =
    context.remaining_capacity_after !== null &&
    context.remaining_capacity_after !== undefined &&
    context.max_position_value !== null &&
    context.max_position_value !== undefined &&
    context.max_position_value > 0
      ? (context.remaining_capacity_after / context.max_position_value) * 100
      : null;

  return (tradePct !== null && tradePct < 1) || (remainingCapacityPct !== null && remainingCapacityPct < 1);
}

function CapitalUsageSection({ event }: { event: TradeEventContext }) {
  const context = event.capital_context;
  if (!context) return null;

  const tradePct = tradeSizePctOfEquity(context);

  return (
    <div>
      <p className="app-title text-sm font-semibold">Trade sizing</p>
      <div className="app-border-soft mt-3 grid gap-3 rounded-xl border p-3 text-sm sm:grid-cols-2">
        <div>
          <p className="app-text-muted text-xs uppercase tracking-[0.16em]">Trade value</p>
          <p className="app-title mt-1 font-semibold">{formatCurrency(context.trade_notional)}</p>
        </div>
        <div>
          <p className="app-text-muted text-xs uppercase tracking-[0.16em]">Trade % of equity</p>
          <p className="app-title mt-1 font-semibold">{formatPercent(tradePct)}</p>
        </div>
        <div>
          <p className="app-text-muted text-xs uppercase tracking-[0.16em]">Position shares</p>
          <p className="app-title mt-1 font-semibold">{formatShares(context.position_shares_after)}</p>
        </div>
        <div>
          <p className="app-text-muted text-xs uppercase tracking-[0.16em]">Position value</p>
          <p className="app-title mt-1 font-semibold">{formatCurrency(context.position_value_after)}</p>
        </div>
        <div>
          <p className="app-text-muted text-xs uppercase tracking-[0.16em]">Allocation after</p>
          <p className="app-title mt-1 font-semibold">{formatPercent(context.position_allocation_pct_after)}</p>
        </div>
        <div>
          <p className="app-text-muted text-xs uppercase tracking-[0.16em]">Cash after</p>
          <p className="app-title mt-1 font-semibold">{formatCurrency(context.cash_after_trade)}</p>
        </div>
      </div>
      {shouldShowSmallAddHint(event) ? (
        <p className="app-text-muted mt-2 text-sm">Small add because remaining cash/capacity was limited.</p>
      ) : null}
    </div>
  );
}

function EventList({
  events,
  selectedEventId,
  onSelectEvent
}: {
  events: TradeEventContext[];
  selectedEventId: string | null;
  onSelectEvent: (eventId: string) => void;
}) {
  return (
    <div className="app-table-frame max-h-[460px] overflow-auto rounded-2xl">
      <table className="min-w-full divide-y text-sm app-divider">
        <thead className="app-table-head sticky top-0 text-left text-xs font-semibold uppercase tracking-[0.18em]">
          <tr>
            <th className="px-4 py-3">Date</th>
            <th className="px-4 py-3">Action</th>
            <th className="px-4 py-3">Shares</th>
            <th className="px-4 py-3">Price</th>
          </tr>
        </thead>
        <tbody className="app-table-body divide-y app-divider">
          {events.map((event) => {
            const isSelected = event.id === selectedEventId;
            return (
              <tr
                key={event.id}
                role="button"
                tabIndex={0}
                onClick={() => onSelectEvent(event.id)}
                onKeyDown={(keyboardEvent) => {
                  if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
                    keyboardEvent.preventDefault();
                    onSelectEvent(event.id);
                  }
                }}
                className={`cursor-pointer ${isSelected ? 'bg-cyan-500/10' : 'app-row-hover'}`}
              >
                <td className="app-title px-4 py-3 font-medium">{event.date ? formatShortDate(event.date) : '—'}</td>
                <td className="px-4 py-3">{event.action}</td>
                <td className="px-4 py-3">{formatShares(event.shares)}</td>
                <td className="px-4 py-3">{formatPrice(event.price)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function EventPanel({ event }: { event: TradeEventContext | null }) {
  if (!event) {
    return (
      <div className="app-border-soft h-full rounded-2xl border p-5">
        <p className="app-text-muted text-sm">Select a trade event to inspect available rule context.</p>
      </div>
    );
  }

  const values = Object.entries(event.values_on_date);
  const ruleContext = event.rule_context ?? [];
  const hasSignalRows = ruleContext.length > 0 || values.length > 0;
  return (
    <div className="app-border-soft h-full rounded-2xl border p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="app-text-muted text-xs font-semibold uppercase tracking-[0.18em]">
            {event.event_category ?? 'trade'}
          </p>
          <h4 className="app-title mt-1 text-base font-semibold">{eventTitle(event)}</h4>
        </div>
        <div className="text-left text-sm sm:text-right">
          <p className="app-title font-semibold">{formatPrice(event.price)}</p>
          <p className="app-text-muted">Shares {formatShares(event.shares)}</p>
        </div>
      </div>

      <div className="mt-5 space-y-4">
        <div>
          <p className="app-title text-sm font-semibold">Signal values on trade date</p>
          {hasSignalRows ? (
            <div className="app-table-frame mt-3 overflow-auto rounded-xl">
              <table className="min-w-full divide-y text-sm app-divider">
                <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
                  <tr>
                    <th className="px-3 py-2">Signal</th>
                    <th className="px-3 py-2">Actual</th>
                    <th className="px-3 py-2">Rule</th>
                    <th className="px-3 py-2">Status</th>
                  </tr>
                </thead>
                <tbody className="app-table-body divide-y app-divider">
                  {ruleContext.length > 0
                    ? ruleContext.map((context) => (
                        <tr key={`${context.label}-${context.summary}`}>
                          <td className="px-3 py-2 font-medium app-title">{context.label}</td>
                          <td className="px-3 py-2">
                            {context.actual_value === null || context.actual_value === undefined
                              ? 'Missing'
                              : formatValue(context.actual_value)}
                          </td>
                          <td className="px-3 py-2">{formatRule(context)}</td>
                          <td className="px-3 py-2">{formatStatus(context)}</td>
                        </tr>
                      ))
                    : values.map(([label, value]) => (
                        <tr key={label}>
                          <td className="px-3 py-2 font-medium app-title">{label}</td>
                          <td className="px-3 py-2">{formatValue(value)}</td>
                          <td className="px-3 py-2">—</td>
                          <td className="px-3 py-2">available</td>
                        </tr>
                      ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="app-text-muted mt-2 text-sm">No signal values were found in artifacts for this trade date.</p>
          )}
        </div>
        <CapitalUsageSection event={event} />
      </div>
    </div>
  );
}

export function TradeEventInspector({ runId, variantId }: { runId: string; variantId?: string }) {
  const [data, setData] = useState<TradeEventContextResponse | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    async function loadTradeEvents() {
      setIsLoading(true);
      setErrorMessage(null);

      try {
        const response = variantId
          ? await fetchSweepVariantTradeEvents(runId, variantId)
          : await fetchRunTradeEvents(runId);
        if (ignore) return;

        setData(response);
        setSelectedEventId(response.events[0]?.id ?? null);
      } catch (error) {
        if (ignore) return;
        setData(null);
        setSelectedEventId(null);
        setErrorMessage(
          isArtifactUnavailableError(error)
            ? artifactUnavailableMessage(error)
            : error instanceof Error
              ? error.message
              : 'Failed to load trade events'
        );
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    void loadTradeEvents();

    return () => {
      ignore = true;
    };
  }, [runId, variantId]);

  const selectedEvent = useMemo(
    () => data?.events.find((event) => event.id === selectedEventId) ?? data?.events[0] ?? null,
    [data?.events, selectedEventId]
  );

  if (isLoading) {
    return (
      <SectionCard title="Trade Event Inspector" subtitle="Loading signal values for trade events.">
        <div className="app-text-muted text-sm">Loading trade events...</div>
      </SectionCard>
    );
  }

  if (errorMessage) {
    return (
      <SectionCard title="Trade Event Inspector" subtitle="Signal values from available run artifacts.">
        <div className="app-text-muted text-sm">{errorMessage}</div>
      </SectionCard>
    );
  }

  if (!data || data.events.length === 0) {
    return (
      <SectionCard title="Trade Event Inspector" subtitle="Signal values from available run artifacts.">
        <div className="app-text-muted text-sm">No trade events were available for this result.</div>
      </SectionCard>
    );
  }

  const countCopy =
    data.total_count > data.events.length
      ? `Showing ${data.events.length} of ${data.total_count} trade events.`
      : `${data.total_count} trade events.`;

  return (
    <SectionCard
      title="Trade Event Inspector"
      subtitle={`Click a trade to inspect signal values on that date. ${countCopy}`}
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <EventList
          events={data.events}
          selectedEventId={selectedEvent?.id ?? null}
          onSelectEvent={setSelectedEventId}
        />
        <EventPanel event={selectedEvent} />
      </div>
    </SectionCard>
  );
}
