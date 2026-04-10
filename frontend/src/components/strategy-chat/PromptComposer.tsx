export function PromptComposer({
  value,
  onChange,
  onSubmit,
  submitting,
  disabled,
  placeholder = 'Describe your strategy...'
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  return (
    <div className="rounded-[28px] border border-slate-800 bg-slate-900/90 p-3 shadow-2xl shadow-black/20">
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="min-h-[120px] w-full resize-none rounded-[22px] border border-transparent bg-transparent px-4 py-4 text-base text-slate-100 outline-none placeholder:text-slate-500"
      />

      <div className="flex items-center justify-between gap-3 border-t border-slate-800 px-2 pt-3">
        <p className="text-xs text-slate-500">
          Natural language in, validated Strategy V2 config out.
        </p>

        <button
          type="button"
          onClick={onSubmit}
          disabled={disabled || submitting || !value.trim()}
          className="rounded-2xl bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? 'Generating...' : 'Generate Strategy'}
        </button>
      </div>
    </div>
  );
}
