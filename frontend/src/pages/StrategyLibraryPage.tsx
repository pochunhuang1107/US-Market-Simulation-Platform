import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { MetricCard } from '../components/shared/MetricCard';
import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchStrategies } from '../lib/api';
import { formatDateTime } from '../lib/formatters';
import type { StrategyListItem } from '../types/api';

const strategyTypeLabels: Record<string, string> = {
  SINGLE_ASSET: 'Single ETF',
  SIMULATION: 'Single ETF',
  PORTFOLIO: 'Portfolio',
  COMPARISON: 'Comparison',
  PARAMETER_SWEEP: 'Parameter Sweep'
};

function formatStrategyType(strategyType: string): string {
  return (
    strategyTypeLabels[strategyType] ??
    strategyType
      .toLowerCase()
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  );
}

export function StrategyLibraryPage() {
  const [strategies, setStrategies] = useState<StrategyListItem[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    async function loadStrategies() {
      setLoading(true);
      setErrorMessage(null);

      try {
        const response = await fetchStrategies({ includeArchived: showArchived });
        if (!ignore) {
          setStrategies(response);
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error instanceof Error ? error.message : 'Failed to load strategy library');
          setStrategies([]);
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    void loadStrategies();
    return () => {
      ignore = true;
    };
  }, [showArchived]);

  const sortedStrategies = useMemo(() => {
    return [...strategies].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  }, [strategies]);

  const activeStrategyCount = useMemo(() => {
    return strategies.filter((strategy) => strategy.status?.toLowerCase() === 'active').length;
  }, [strategies]);

  const mostRecentlyUpdatedStrategy = sortedStrategies[0];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Strategy Library"
        title="Saved Strategies"
        description="Review saved strategies, open their version history, and continue from a strategy into builder, run, or comparison workflows."
        actions={
          <Link
            to="/strategies/new"
            className="rounded-xl border px-4 py-2 text-sm font-medium app-text-muted transition hover:border-cyan-400/60 hover:text-cyan-500 dark:hover:text-cyan-300"
          >
            Advanced manual create
          </Link>
        }
      />

      {errorMessage ? <StateCard title="Failed to load strategy library" description={errorMessage} tone="error" /> : null}

      {!loading && sortedStrategies.length > 0 ? (
        <section className="grid gap-4 md:grid-cols-3">
          <MetricCard label={showArchived ? 'Visible strategies' : 'Saved strategies'} value={String(sortedStrategies.length)} />
          <MetricCard label="Active strategies" value={String(activeStrategyCount)} />
          <div className="app-card-soft rounded-2xl border p-4">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] app-text-soft">Most recently updated</p>
            <p className="mt-3 truncate text-lg font-semibold app-title">{mostRecentlyUpdatedStrategy.name}</p>
            <p className="mt-1 text-sm app-text-muted">{formatDateTime(mostRecentlyUpdatedStrategy.updated_at)}</p>
          </div>
        </section>
      ) : null}

      <SectionCard
        title="Strategy Library"
        subtitle="Saved strategies available from the existing strategy records."
        actions={
          <label className="inline-flex items-center gap-2 text-sm font-medium app-text-muted">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => setShowArchived(event.target.checked)}
              className="h-4 w-4 rounded border app-surface-soft accent-cyan-500"
            />
            Show archived
          </label>
        }
      >
        {loading ? (
          <p className="app-text-muted text-sm">Loading saved strategies...</p>
        ) : sortedStrategies.length === 0 ? (
          <div className="space-y-4">
            <div>
              <h4 className="app-title text-base font-semibold">No saved strategies yet</h4>
              <p className="mt-2 max-w-2xl text-sm leading-6 app-text-muted">
                Saved strategies are created from successful draft runs. Start with the chat-first builder,
                run a simulation, then save the result once it is worth keeping.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Link
                to="/"
                className="app-button-primary inline-flex rounded-xl px-4 py-2 text-sm font-semibold transition"
              >
                Build a strategy
              </Link>
              <Link
                to="/runs"
                className="app-button-secondary inline-flex rounded-xl px-4 py-2 text-sm font-medium transition"
              >
                View runs
              </Link>
            </div>
          </div>
        ) : (
          <div className="app-table overflow-hidden rounded-2xl border">
            <table className="min-w-full divide-y app-divider text-left text-sm">
              <thead className="app-table-head">
                <tr>
                  <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">Name</th>
                  <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">Type</th>
                  <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">Updated</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y app-divider">
                {sortedStrategies.map((strategy) => {
                  const isArchived = strategy.status?.toLowerCase() === 'archived';

                  return (
                    <tr key={strategy.id} className={`app-row-hover transition ${isArchived ? 'opacity-75' : ''}`}>
                      <td className="px-4 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link to={`/strategies/${strategy.id}`} className="font-semibold app-title transition hover:text-cyan-400">
                            {strategy.name}
                          </Link>
                          {isArchived ? (
                            <span className="app-surface-soft app-text-muted rounded-full border px-2 py-0.5 text-xs font-medium">
                              Archived
                            </span>
                          ) : null}
                        </div>
                        {strategy.description ? (
                          <p className="mt-1 max-w-xl text-xs app-text-muted">{strategy.description}</p>
                        ) : null}
                      </td>
                      <td className="px-4 py-4 app-text-muted">{formatStrategyType(strategy.strategy_type)}</td>
                      <td className="px-4 py-4 app-text-muted">{formatDateTime(strategy.updated_at)}</td>
                      <td className="px-4 py-4 text-right">
                        <Link
                          to={`/strategies/${strategy.id}`}
                          className="text-sm font-semibold text-cyan-600 transition hover:text-cyan-500 dark:text-cyan-300 dark:hover:text-cyan-200"
                        >
                          Open →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
