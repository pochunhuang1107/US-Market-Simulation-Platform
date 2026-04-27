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
    label: 'Benchmark-aware',
    prompt: 'Build an SPY moving average crossover strategy and compare it with QQQ.'
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
          className="app-card group rounded-2xl border px-4 py-3 text-left transition hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
        >
          <span className="app-label block text-[11px] font-semibold uppercase tracking-[0.18em] group-hover:text-[color:var(--accent)]">
            {example.label}
          </span>
          <span className="mt-1 block text-sm leading-5">
            {example.prompt}
          </span>
        </button>
      ))}
    </div>
  );
}
