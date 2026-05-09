const EXAMPLES = [
  {
    label: 'Beginner RSI',
    prompt: 'Create an XLE RSI pullback strategy with RSI below 45, exit above 60, 12% stop loss, 5-bar cooldown, and max position 75%.'
  },
  {
    label: 'Small-cap RSI',
    prompt: 'Create an IWM RSI strategy that enters below 45, exits above 70, uses an 8% stop loss, and waits 3 bars after exits.'
  },
  {
    label: 'QQQ VIX filter',
    prompt: 'Create a QQQ strategy with entry when VIX below 30 and RSI below 40, exit when VIX above 40 or RSI above 70.'
  },
  {
    label: 'SPY defensive trend',
    prompt: 'Create a SPY strategy with entry when VIX below 30 and SPY is above its 100-day SMA, exit when SPY crosses below its 100-day SMA.'
  },
  {
    label: 'Healthcare risk-control',
    prompt: 'Create an XLV RSI risk-control strategy that enters below 35, exits above 70, and uses an 8% stop loss.'
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
