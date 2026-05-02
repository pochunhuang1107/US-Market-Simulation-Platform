const EXAMPLES = [
  {
    label: 'Beginner RSI',
    prompt: 'Create a simple RSI strategy for QQQ.'
  },
  {
    label: 'Risk-managed',
    prompt: 'Create a QQQ RSI strategy with a 10% stop loss and 15% take profit.'
  },
  {
    label: 'Core-overlay',
    prompt: 'Create a QQQ core-overlay strategy with 60% core and 40% RSI overlay.'
  },
  {
    label: 'VIX filter',
    prompt: 'Only trade QQQ when VIX is below 25 and RSI is below 35.'
  },
  {
    label: 'Relative strength',
    prompt: 'Create a QQQ strategy that enters when QQQ outperforms SPY over 20 days.'
  }
];

export function ExamplePromptChips({
  onSelect
}: {
  onSelect: (value: string) => void;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {EXAMPLES.map((example) => (
        <button
          key={example.prompt}
          type="button"
          onClick={() => onSelect(example.prompt)}
          className="app-example-prompt group rounded-xl border px-3.5 py-2.5 text-left transition hover:border-[color:var(--accent)] hover:text-[color:var(--accent)] focus-visible:border-[color:var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:color-mix(in_srgb,var(--accent)_18%,transparent)]"
        >
          <span className="app-label block text-[11px] font-semibold uppercase tracking-[0.16em] group-hover:text-[color:var(--accent)]">
            {example.label}
          </span>
          <span className="mt-1 block text-sm leading-5 app-title">
            {example.prompt}
          </span>
        </button>
      ))}
    </div>
  );
}
