import type { ChangeEvent } from 'react';

import type { RunSortBy, RunSortOrder, StrategyListItem } from '../../types/api';

interface RunFiltersProps {
  status: string;
  strategyId: string;
  sortBy: RunSortBy;
  sortOrder: RunSortOrder;
  strategies: StrategyListItem[];
  onStatusChange: (value: string) => void;
  onStrategyChange: (value: string) => void;
  onSortByChange: (value: RunSortBy) => void;
  onSortOrderChange: (value: RunSortOrder) => void;
}

export function RunFilters({
  status,
  strategyId,
  sortBy,
  sortOrder,
  strategies,
  onStatusChange,
  onStrategyChange,
  onSortByChange,
  onSortOrderChange
}: RunFiltersProps) {
  return (
    <div className="app-card app-shadow grid gap-4 rounded-3xl border p-5 lg:grid-cols-4 lg:p-6">
      <FilterSelect label="Status" value={status} onChange={(event) => onStatusChange(event.target.value)}>
        <option value="">All statuses</option>
        <option value="PENDING">Pending</option>
        <option value="QUEUED">Queued</option>
        <option value="RUNNING">Running</option>
        <option value="LEASED">Leased</option>
        <option value="SUCCEEDED">Succeeded</option>
        <option value="FAILED">Failed</option>
        <option value="CANCELED">Canceled</option>
      </FilterSelect>

      <FilterSelect label="Strategy" value={strategyId} onChange={(event) => onStrategyChange(event.target.value)}>
        <option value="">All strategies</option>
        {strategies.map((strategy) => (
          <option key={strategy.id} value={strategy.id}>
            {strategy.name}
          </option>
        ))}
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
  );
}

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
