import type { ChangeEvent } from 'react';

import type {
  RunArtifactStorageFilter,
  RunSortBy,
  RunSortOrder,
  StrategyListItem
} from '../../types/api';

interface RunFiltersProps {
  status: string;
  strategyId: string;
  artifactStorageType: RunArtifactStorageFilter;
  sortBy: RunSortBy;
  sortOrder: RunSortOrder;
  strategies: StrategyListItem[];
  onStatusChange: (value: string) => void;
  onStrategyChange: (value: string) => void;
  onArtifactStorageTypeChange: (value: RunArtifactStorageFilter) => void;
  onSortByChange: (value: RunSortBy) => void;
  onSortOrderChange: (value: RunSortOrder) => void;
}

export function RunFilters({
  status,
  strategyId,
  artifactStorageType,
  sortBy,
  sortOrder,
  strategies,
  onStatusChange,
  onStrategyChange,
  onArtifactStorageTypeChange,
  onSortByChange,
  onSortOrderChange
}: RunFiltersProps) {
  return (
    <div className="app-card rounded-3xl border p-5 lg:p-6">
      <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="app-title text-sm font-semibold">Refine results</p>
          <p className="app-text-muted mt-1 text-sm">Filter results by status, saved strategy, or artifact storage.</p>
        </div>
      </div>

      <div className="mb-5">
        <p className="app-text-soft mb-2 block text-xs font-semibold uppercase tracking-[0.18em]">Status</p>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Status filter">
          {STATUS_FILTERS.map((filter) => {
            const active = status === filter.value;
            return (
              <button
                key={filter.value || 'ALL'}
                type="button"
                aria-pressed={active}
                onClick={() => onStatusChange(filter.value)}
                className={`rounded-full border px-3 py-1.5 text-sm font-medium transition ${
                  active
                    ? 'border-cyan-400 bg-cyan-400/15 app-title'
                    : 'app-surface-soft app-text-muted hover:border-cyan-400/70 hover:text-cyan-400'
                }`}
              >
                {filter.label}
              </button>
            );
          })}
        </div>
        <p className="app-text-muted mt-2 text-xs">Active includes pending, queued, claimed, and running results.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-4">
        <FilterSelect label="Strategy" value={strategyId} onChange={(event) => onStrategyChange(event.target.value)}>
          <option value="">All strategies</option>
          {strategies.map((strategy) => (
            <option key={strategy.id} value={strategy.id}>
              {strategy.name}
            </option>
          ))}
        </FilterSelect>

        <FilterSelect
          label="Storage"
          value={artifactStorageType}
          onChange={(event) => onArtifactStorageTypeChange(event.target.value as RunArtifactStorageFilter)}
        >
          <option value="">Current storage</option>
          <option value="ALL">All</option>
          <option value="S3">S3</option>
          <option value="LOCAL">Local</option>
        </FilterSelect>

        <FilterSelect label="Sort by" value={sortBy} onChange={(event) => onSortByChange(event.target.value as RunSortBy)}>
          <option value="created_at">Created at</option>
          <option value="finished_at">Finished at</option>
          <option value="status">Status</option>
        </FilterSelect>

        <FilterSelect label="Sort order" value={sortOrder} onChange={(event) => onSortOrderChange(event.target.value as RunSortOrder)}>
          <option value="desc">Descending</option>
          <option value="asc">Ascending</option>
        </FilterSelect>
      </div>
    </div>
  );
}

const STATUS_FILTERS = [
  { label: 'All', value: '' },
  { label: 'Active', value: 'ACTIVE' },
  { label: 'Succeeded', value: 'SUCCEEDED' },
  { label: 'Failed', value: 'FAILED' },
  { label: 'Canceled', value: 'CANCELED' }
];

function FilterSelect({
  label,
  value,
  onChange,
  children
}: {
  label: string;
  value: string;
  onChange: (event: ChangeEvent<HTMLSelectElement>) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="app-text-soft mb-2 block text-xs font-semibold uppercase tracking-[0.18em]">{label}</span>
      <select value={value} onChange={onChange} className="app-input w-full rounded-2xl px-4 py-3 text-sm outline-none transition focus:border-cyan-500">
        {children}
      </select>
    </label>
  );
}
