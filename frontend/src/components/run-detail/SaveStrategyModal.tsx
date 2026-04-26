import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

interface SaveStrategyModalProps {
  isOpen: boolean;
  initialName: string;
  isSaving?: boolean;
  errorMessage?: string | null;
  onClose: () => void;
  onSubmit: (payload: { name: string; description: string }) => void;
}

export function SaveStrategyModal({
  isOpen,
  initialName,
  isSaving = false,
  errorMessage = null,
  onClose,
  onSubmit
}: SaveStrategyModalProps) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setName(initialName);
    setDescription('');
  }, [initialName, isOpen]);

  if (!isOpen) return null;

  const trimmedName = name.trim();
  const canSubmit = trimmedName.length > 0 && !isSaving;
  const isSavedStrategyLimitError = errorMessage?.includes('Saved strategy limit reached') ?? false;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 px-4 backdrop-blur-sm">
      <div className="app-card app-shadow w-full max-w-xl rounded-3xl border p-6">
        <div className="space-y-2">
          <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.24em]">
            Save strategy
          </p>
          <h2 className="app-title text-2xl font-semibold tracking-tight">
            Save this run as a strategy
          </h2>
          <p className="app-text-muted text-sm leading-6">
            This creates a saved strategy from the unsaved draft that produced this run.
          </p>
        </div>

        {errorMessage ? (
          <div className="mt-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-700 dark:text-rose-200">
            <p>{errorMessage}</p>
            {isSavedStrategyLimitError ? (
              <Link
                to="/strategies"
                className="mt-3 inline-flex rounded-xl border border-rose-500/30 px-3 py-2 text-xs font-semibold transition hover:border-rose-500/60"
              >
                Open Strategy Library
              </Link>
            ) : null}
          </div>
        ) : null}

        <div className="mt-6 space-y-4">
          <label className="block">
            <div className="app-label mb-2 text-[11px] font-semibold uppercase tracking-[0.22em]">
              Strategy name
            </div>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="My strategy"
              className="app-input w-full rounded-2xl border px-4 py-3 text-sm outline-none"
              autoFocus
            />
          </label>

          <label className="block">
            <div className="app-label mb-2 text-[11px] font-semibold uppercase tracking-[0.22em]">
              Description
            </div>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Optional note about this strategy"
              rows={4}
              className="app-input w-full rounded-2xl border px-4 py-3 text-sm outline-none"
            />
          </label>
        </div>

        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60"
          >
            Cancel
          </button>

          <button
            type="button"
            disabled={!canSubmit}
            onClick={() =>
              onSubmit({
                name: trimmedName,
                description: description.trim()
              })
            }
            className="app-button-primary rounded-2xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSaving ? 'Saving...' : 'Save strategy'}
          </button>
        </div>
      </div>
    </div>
  );
}
