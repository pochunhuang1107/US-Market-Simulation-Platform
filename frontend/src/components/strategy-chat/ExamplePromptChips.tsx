const EXAMPLES = [
  'Create a simple RSI strategy for QQQ.',
  'Create a QQQ RSI strategy with a 10% stop loss and 15% take profit.',
  'Create a QQQ core-overlay strategy with 60% core and 40% RSI overlay.',
  'Build an SPY moving average crossover strategy and compare it with QQQ.',
  'Create a QQQ strategy that enters when QQQ outperforms SPY over 20 days.'
];

export function ExamplePromptChips({
  onSelect
}: {
  onSelect: (value: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-3">
      {EXAMPLES.map((example) => (
        <button
          key={example}
          type="button"
          onClick={() => onSelect(example)}
          className="app-card rounded-full border px-4 py-2 text-sm transition hover:border-[color:var(--accent)] hover:text-[color:var(--accent)]"
        >
          {example}
        </button>
      ))}
    </div>
  );
}
