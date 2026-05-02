import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchMeEntitlements, fetchStrategies } from '../lib/api';
import { formatDateTime } from '../lib/formatters';
import type { MeEntitlementsResponse, StrategyListItem } from '../types/api';

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
  const [entitlements, setEntitlements] = useState<MeEntitlementsResponse | null>(null);

  useEffect(() => {
    let ignore = false;

    async function loadEntitlements() {
      try {
        const response = await fetchMeEntitlements();
        if (!ignore) {
          setEntitlements(response);
        }
      } catch {
        if (!ignore) {
          setEntitlements(null);
        }
      }
    }

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

    void loadEntitlements();
    void loadStrategies();
    return () => {
      ignore = true;
    };
  }, [showArchived]);

  const sortedStrategies = useMemo(() => {
    return [...strategies].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  }, [strategies]);

  const savedStrategyLimitReached = entitlements?.usage.saved_strategies_remaining === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Strategy Library"
        title="Saved Strategies"
        description="Keep promising strategies, review their history, and continue research from saved versions."
        actions={
          <Link
            to="/strategies/new"
            className="rounded-xl border px-4 py-2 text-sm font-medium app-text-muted transition hover:border-cyan-400/60 hover:text-cyan-500 dark:hover:text-cyan-300"
          >
            Manual strategy create
          </Link>
        }
      />

      {errorMessage ? <StateCard title="Failed to load strategy library" description={errorMessage} tone="error" /> : null}

      {entitlements ? (
        <section className="app-card-soft rounded-2xl border p-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] app-text-soft">Plan usage</p>
              <h3 className="mt-1 app-title text-base font-semibold">{entitlements.plan.name}</h3>
              <p className="mt-1 max-w-2xl text-sm leading-6 app-text-muted">
                Archived strategies are hidden from the main library and do not count toward your active saved strategy limit.
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-3 lg:min-w-[30rem]">
              <div className="app-surface-soft rounded-xl border px-3 py-2">
                <p className="flex min-h-8 items-start text-xs font-semibold uppercase tracking-[0.16em] app-text-soft">
                  Active saved
                </p>
                <p className="mt-1 app-title text-lg font-semibold">{entitlements.usage.saved_strategies}</p>
              </div>
              <div className="app-surface-soft rounded-xl border px-3 py-2">
                <p className="flex min-h-8 items-start text-xs font-semibold uppercase tracking-[0.16em] app-text-soft">
                  Max saved
                </p>
                <p className="mt-1 app-title text-lg font-semibold">{entitlements.limits.max_saved_strategies}</p>
              </div>
              <div className="app-surface-soft rounded-xl border px-3 py-2">
                <p className="flex min-h-8 items-start text-xs font-semibold uppercase tracking-[0.16em] app-text-soft">
                  Remaining slots
                </p>
                <p
                  className={`mt-1 text-lg font-semibold ${
                    savedStrategyLimitReached ? 'text-rose-500 dark:text-rose-300' : 'text-emerald-500 dark:text-emerald-300'
                  }`}
                >
                  {entitlements.usage.saved_strategies_remaining}
                </p>
              </div>
            </div>
          </div>
          {savedStrategyLimitReached ? (
            <div className="app-alert-warning mt-4 rounded-2xl px-4 py-3 text-sm">
              You have reached your saved strategy limit. Archive an older strategy or upgrade later to save more.
            </div>
          ) : null}
        </section>
      ) : null}

      <SectionCard
        title="Strategy Library"
        subtitle="Open a saved strategy to review versions, recent results, and next research actions."
        actions={
          <div className="space-y-1">
            <label className="inline-flex items-center gap-2 text-sm font-medium app-text-muted">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(event) => setShowArchived(event.target.checked)}
                className="h-4 w-4 rounded border app-surface-soft accent-cyan-500"
              />
              Show archived
            </label>
            <p className="max-w-xs text-xs leading-5 app-text-soft">
              Archived strategies are kept for history and can be restored.
            </p>
          </div>
        }
      >
        {loading ? (
          <p className="app-text-muted text-sm">Loading saved strategies...</p>
        ) : sortedStrategies.length === 0 ? (
          <div className="space-y-4">
            <div>
              <h4 className="app-title text-base font-semibold">No saved strategies yet</h4>
              <p className="mt-2 max-w-2xl text-sm leading-6 app-text-muted">
                Save a successful result to keep it here as a durable strategy.
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
                View results
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
                    <tr
                      key={strategy.id}
                      className={`app-row-hover transition duration-150 hover:shadow-[inset_3px_0_0_var(--accent)] focus-within:shadow-[inset_3px_0_0_var(--accent)] ${isArchived ? 'opacity-75' : ''}`}
                    >
                      <td className="px-4 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link
                            to={`/strategies/${strategy.id}`}
                            className="font-semibold app-title transition hover:text-cyan-400 focus-visible:text-cyan-400 focus-visible:outline-none"
                          >
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
                          className="text-sm font-semibold text-cyan-600 transition hover:text-cyan-500 focus-visible:text-cyan-500 focus-visible:outline-none dark:text-cyan-300 dark:hover:text-cyan-200 dark:focus-visible:text-cyan-200"
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
