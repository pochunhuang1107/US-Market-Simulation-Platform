import { formatDateTime } from '../../lib/formatters';
import type { StrategyVersionSummary } from '../../types/api';

export function VersionsTable({ versions }: { versions: StrategyVersionSummary[] }) {
  return (
    <div className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-900/70 shadow-2xl shadow-slate-950/40">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-900 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
            <tr>
              <th className="px-5 py-4">Version</th>
              <th className="px-5 py-4">Created</th>
              <th className="px-5 py-4">Change note</th>
              <th className="px-5 py-4">Config hash</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {versions.map((version) => (
              <tr key={version.id} className="hover:bg-slate-800/50">
                <td className="px-5 py-4">
                  <div className="flex items-center gap-3">
                    <span className="font-semibold text-white">v{version.version_number}</span>
                    {version.is_current ? (
                      <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
                        Current
                      </span>
                    ) : null}
                  </div>
                </td>
                <td className="px-5 py-4 text-slate-300">{formatDateTime(version.created_at)}</td>
                <td className="px-5 py-4 text-slate-300">{version.change_note || '—'}</td>
                <td className="px-5 py-4 font-mono text-xs text-slate-400">{version.config_hash}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
