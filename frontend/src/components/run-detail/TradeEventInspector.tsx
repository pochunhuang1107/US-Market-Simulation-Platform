import { useEffect, useMemo, useState } from 'react';

import { fetchRunTradeEvents } from '../../lib/api';
import { formatShortDate } from '../../lib/formatters';
import type { TradeEventContext, TradeEventContextResponse } from '../../types/api';
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

function formatValue(value: string | number | boolean): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return value;
}

function eventTitle(event: TradeEventContext): string {
  const date = event.date ? formatShortDate(event.date) : 'Unknown date';
  return `${event.action} · ${date}`;
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
          <p className="app-title text-sm font-semibold">Why this trade happened</p>
          <p className="app-text-muted mt-2 text-sm leading-6">{event.explanation}</p>
        </div>

        {event.rule_summary ? (
          <div>
            <p className="app-title text-sm font-semibold">Rule summary</p>
            <p className="app-text-muted mt-2 text-sm leading-6">{event.rule_summary}</p>
          </div>
        ) : null}

        <div>
          <p className="app-title text-sm font-semibold">Values on this date</p>
          {values.length > 0 ? (
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              {values.map(([label, value]) => (
                <div key={label} className="app-surface-soft rounded-xl px-3 py-2">
                  <dt className="app-text-muted text-xs">{label}</dt>
                  <dd className="app-title mt-1 text-sm font-semibold">{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="app-text-muted mt-2 text-sm">
              No indicator or reference values were available in artifacts for this date.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export function TradeEventInspector({ runId }: { runId: string }) {
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
        const response = await fetchRunTradeEvents(runId);
        if (ignore) return;

        setData(response);
        setSelectedEventId(response.events[0]?.id ?? null);
      } catch (error) {
        if (ignore) return;
        setData(null);
        setSelectedEventId(null);
        setErrorMessage(error instanceof Error ? error.message : 'Failed to load trade events');
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
  }, [runId]);

  const selectedEvent = useMemo(
    () => data?.events.find((event) => event.id === selectedEventId) ?? data?.events[0] ?? null,
    [data?.events, selectedEventId]
  );

  if (isLoading) {
    return (
      <SectionCard title="Trade Event Inspector" subtitle="Loading rule context for trade events.">
        <div className="app-text-muted text-sm">Loading trade events...</div>
      </SectionCard>
    );
  }

  if (errorMessage) {
    return (
      <SectionCard title="Trade Event Inspector" subtitle="Rule context from available run artifacts.">
        <div className="app-text-muted text-sm">{errorMessage}</div>
      </SectionCard>
    );
  }

  if (!data || data.events.length === 0) {
    return (
      <SectionCard title="Trade Event Inspector" subtitle="Rule context from available run artifacts.">
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
      subtitle={`Click a trade to inspect matched rule context and available values on that date. ${countCopy}`}
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
