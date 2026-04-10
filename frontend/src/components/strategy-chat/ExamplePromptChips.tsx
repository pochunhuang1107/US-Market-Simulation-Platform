const EXAMPLES = [
  'Create a QQQ RSI mean reversion strategy with 10% stop loss.',
  'Build an SPY moving average crossover strategy using 10 day and 30 day SMA.',
  'Create a QQQ strategy with benchmark SPY, take profit at 15%, and cooldown 5 bars.',
  'Use SPY instead and reduce drawdown with a tighter stop loss.'
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
          className="rounded-full border border-slate-800 bg-slate-900/80 px-4 py-2 text-sm text-slate-200 transition hover:border-cyan-500/50 hover:text-cyan-300"
        >
          {example}
        </button>
      ))}
    </div>
  );
}
