import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import { fetchStrategies } from '../lib/api';
import { formatDateTime } from '../lib/formatters';
import type { StrategyListItem } from '../types/api';

export function StrategyLibraryPage() {
  const [strategies, setStrategies] = useState<StrategyListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;

    async function loadStrategies() {
      setLoading(true);
      setErrorMessage(null);

      try {
        const response = await fetchStrategies();
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
  }, []);

  const sortedStrategies = useMemo(() => {
    return [...strategies].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
  }, [strategies]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Strategy Library"
        title="Saved Strategies"
        description="Review saved strategies, open their version history, and continue from a strategy into builder, run, or comparison workflows."
        actions={
          <Link
            to="/strategies/new"
            className="app-button-secondary rounded-xl px-4 py-2 text-sm transition"
          >
            Create manually
          </Link>
        }
      />

      {errorMessage ? <StateCard title="Failed to load strategy library" description={errorMessage} tone="error" /> : null}

      <SectionCard title="Strategy Library" subtitle="Saved strategies available from the existing strategy records.">
        {loading ? (
          <p className="app-text-muted text-sm">Loading saved strategies...</p>
        ) : sortedStrategies.length === 0 ? (
          <div className="space-y-4">
            <p className="app-text-muted text-sm">No saved strategies yet.</p>
            <Link
              to="/"
              className="app-button-primary inline-flex rounded-xl px-4 py-2 text-sm font-semibold transition"
            >
              Start from Home
            </Link>
          </div>
        ) : (
          <div className="app-table overflow-hidden rounded-2xl border">
            <table className="min-w-full divide-y app-divider text-left text-sm">
              <thead className="app-table-head">
                <tr>
                  <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">Name</th>
                  <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">Type</th>
                  <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">Status</th>
                  <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] app-text-muted">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y app-divider">
                {sortedStrategies.map((strategy) => (
                  <tr key={strategy.id} className="app-row-hover transition">
                    <td className="px-4 py-4">
                      <Link to={`/strategies/${strategy.id}`} className="font-semibold app-title transition hover:text-cyan-400">
                        {strategy.name}
                      </Link>
                      {strategy.description ? (
                        <p className="mt-1 max-w-xl text-xs app-text-muted">{strategy.description}</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-4 app-text-muted">{strategy.strategy_type}</td>
                    <td className="px-4 py-4 app-text-muted">{strategy.status}</td>
                    <td className="px-4 py-4 app-text-muted">{formatDateTime(strategy.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </div>
  );
}
