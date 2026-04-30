import { formatDateTime } from '../../lib/formatters';
import type { StrategyVersionSummary } from '../../types/api';

interface VersionsTableProps {
  versions: StrategyVersionSummary[];
  selectedVersionId: string | null;
  onSelectVersion: (version: StrategyVersionSummary) => void;
}

export function VersionsTable({ versions, selectedVersionId, onSelectVersion }: VersionsTableProps) {
  return (
    <div className="app-table app-shadow overflow-hidden rounded-3xl border">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y app-divider text-sm">
          <thead className="app-table-head text-left text-xs font-semibold uppercase tracking-[0.18em]">
            <tr>
              <th className="px-5 py-4">Version</th>
              <th className="px-5 py-4">Created</th>
              <th className="px-5 py-4">Reference result</th>
              <th className="px-5 py-4">Change note</th>
            </tr>
          </thead>
          <tbody className="app-table-body divide-y app-divider">
            {versions.map((version) => {
              const isSelected = version.id === selectedVersionId;

              return (
                <tr
                  key={version.id}
                  className={`app-row-hover cursor-pointer transition ${isSelected ? 'bg-cyan-500/10 ring-1 ring-inset ring-cyan-400/40' : ''}`}
                  tabIndex={0}
                  aria-selected={isSelected}
                  onClick={() => onSelectVersion(version)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelectVersion(version);
                    }
                  }}
                >
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <span className="app-title font-semibold">v{version.version_number}</span>
                      {isSelected ? (
                        <span className="app-chip-success rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.16em]">
                          Selected
                        </span>
                      ) : null}
                      {version.is_current ? (
                        <span className="app-chip-info rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.16em]">
                          Current
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className="app-text-muted px-5 py-4">{formatDateTime(version.created_at)}</td>
                  <td className="app-text-muted px-5 py-4">
                    {version.reference_run_id ? (
                      <span className="font-mono text-xs">{version.reference_run_id.split('-')[0]}</span>
                    ) : (
                      'No reference result yet'
                    )}
                  </td>
                  <td className="app-text-muted px-5 py-4">{version.change_note || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
