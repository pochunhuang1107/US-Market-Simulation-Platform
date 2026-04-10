import { useCallback } from 'react';

type PromptComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  disabled?: boolean;
  placeholder?: string;
  submitLabel?: string;
};

export function PromptComposer({
  value,
  onChange,
  onSubmit,
  submitting,
  disabled = false,
  placeholder = 'Describe your strategy...',
  submitLabel = 'Generate Strategy'
}: PromptComposerProps) {
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        if (!submitting && !disabled && value.trim()) {
          onSubmit();
        }
      }
    },
    [disabled, onSubmit, submitting, value]
  );

  const isButtonDisabled = disabled || submitting || !value.trim();

  return (
    <div className="rounded-[28px] border border-white/10 bg-slate-900/90 shadow-[0_0_0_1px_rgba(255,255,255,0.02)]">
      <div className="p-4">
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={5}
          disabled={disabled || submitting}
          className="w-full resize-none border-0 bg-transparent text-base text-white outline-none placeholder:text-slate-500"
        />
      </div>

      <div className="flex items-center justify-between border-t border-white/10 px-4 py-3">
        <p className="text-xs text-slate-500">
          Natural language in, validated Strategy V2 config out.
        </p>

        <button
          type="button"
          onClick={onSubmit}
          disabled={isButtonDisabled}
          className="rounded-full bg-cyan-500 px-5 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? 'Working...' : submitLabel}
        </button>
      </div>
    </div>
  );
}