import { StrategyDraftCard } from './StrategyDraftCard';
import type { ChatMessage } from './types';

function parseSupportedSymbols(text: string): string[] {
  const match = text.match(/Supported ETF symbols right now are:\s*(.+)\./i);
  if (!match) return [];
  return match[1]
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseCoverageAnswer(
  text: string
): { startDate: string; endDate: string; maxYears: string } | null {
  const match = text.match(
    /Supported data coverage is\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2}),\s+and your current plan allows up to\s+(\d+)\s+years?/i
  );
  if (!match) return null;

  return {
    startDate: match[1],
    endDate: match[2],
    maxYears: match[3]
  };
}

function parsePlanLimitAnswer(text: string): { maxYears: string } | null {
  const match = text.match(/maximum backtest window of\s+(\d+)\s+years?/i);
  if (!match) return null;

  return {
    maxYears: match[1]
  };
}

function AssistantMessageCard({
  tone,
  title,
  text
}: {
  tone: 'default' | 'info' | 'warning';
  title: string;
  text: string;
}) {
  const toneClass =
    tone === 'warning'
      ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
      : tone === 'info'
        ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-100'
        : 'app-card app-shadow border';

  const eyebrowClass =
    tone === 'warning'
      ? 'text-amber-200'
      : tone === 'info'
        ? 'text-cyan-200'
        : 'app-label';

  const bodyClass =
    tone === 'warning'
      ? 'text-amber-100/90'
      : tone === 'info'
        ? 'text-cyan-100/90'
        : 'app-title';

  return (
    <div className={`w-full max-w-5xl rounded-[32px] p-4 ${toneClass}`}>
      <div className={`mb-3 text-xs font-semibold uppercase tracking-[0.22em] ${eyebrowClass}`}>
        {title}
      </div>
      <p className={`whitespace-pre-wrap text-sm leading-6 ${bodyClass}`}>{text}</p>
    </div>
  );
}

function InfoPill({
  label,
  value
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl border border-cyan-500/20 bg-slate-950/20 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-200">
        {label}
      </div>
      <div className="mt-1 text-sm text-cyan-50">{value}</div>
    </div>
  );
}

function StrategyAnswerCard({ text }: { text: string }) {
  const symbols = parseSupportedSymbols(text);
  const coverage = parseCoverageAnswer(text);
  const planLimits = parsePlanLimitAnswer(text);

  if (symbols.length > 0) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-cyan-500/30 bg-cyan-500/10 p-5 text-cyan-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
          Strategy Assistant
        </div>
        <h3 className="text-lg font-semibold text-cyan-50">Supported ETF symbols</h3>
        <p className="mt-2 text-sm leading-6 text-cyan-100/90">
          This platform is currently ETF-first. Here are the supported symbols available in the builder.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {symbols.map((symbol) => (
            <span
              key={symbol}
              className="rounded-full border border-cyan-400/30 bg-slate-950/20 px-3 py-1 text-xs font-semibold tracking-[0.14em] text-cyan-50"
            >
              {symbol}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (coverage) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-cyan-500/30 bg-cyan-500/10 p-5 text-cyan-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
          Strategy Assistant
        </div>
        <h3 className="text-lg font-semibold text-cyan-50">Coverage and plan window</h3>
        <p className="mt-2 text-sm leading-6 text-cyan-100/90">
          Here is the currently supported ETF data window and your plan’s maximum backtest range.
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <InfoPill label="Supported Start" value={coverage.startDate} />
          <InfoPill label="Supported End" value={coverage.endDate} />
          <InfoPill label="Plan Max Years" value={coverage.maxYears} />
        </div>
      </div>
    );
  }

  if (planLimits) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-cyan-500/30 bg-cyan-500/10 p-5 text-cyan-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
          Strategy Assistant
        </div>
        <h3 className="text-lg font-semibold text-cyan-50">Current plan limits</h3>
        <div className="mt-4 grid gap-3 md:grid-cols-1">
          <InfoPill label="Plan Max Years" value={planLimits.maxYears} />
        </div>
        <p className="mt-4 text-sm leading-6 text-cyan-100/90">{text}</p>
      </div>
    );
  }

  return <AssistantMessageCard tone="info" title="Strategy Assistant" text={text} />;
}

export function ChatMessageList({
  messages,
  onRunDraft
}: {
  messages: ChatMessage[];
  onRunDraft: (messageId: string) => void;
}) {
  return (
    <div className="space-y-6">
      {messages.map((message) => {
        if (message.role === 'user') {
          return (
            <div key={message.id} className="flex justify-end">
              <div className="app-button-primary max-w-3xl rounded-[28px] px-5 py-4 text-sm leading-6 shadow-lg shadow-cyan-950/20">
                {message.text}
              </div>
            </div>
          );
        }

        const hasDraftConfig =
          Boolean(message.draft) &&
          message.draft?.response_type !== 'ANSWER' &&
          message.draft?.response_type !== 'VALIDATION_ERROR' &&
          Boolean(message.draft?.config);

        if (hasDraftConfig && message.draft) {
          return (
            <div key={message.id} className="flex justify-start">
              <div className="w-full max-w-5xl">
                <StrategyDraftCard
                  draft={message.draft}
                  onRun={() => onRunDraft(message.id)}
                  isRunning={message.isRunning}
                  runError={message.runError}
                />
              </div>
            </div>
          );
        }

        const responseType = message.draft?.response_type;

        if (responseType === 'ANSWER') {
          return (
            <div key={message.id} className="flex justify-start">
              <StrategyAnswerCard text={message.text} />
            </div>
          );
        }

        const tone =
          responseType === 'VALIDATION_ERROR'
            ? 'warning'
            : 'default';

        const title =
          responseType === 'VALIDATION_ERROR'
            ? 'Validation guidance'
            : 'Strategy Assistant';

        return (
          <div key={message.id} className="flex justify-start">
            <AssistantMessageCard tone={tone} title={title} text={message.text} />
          </div>
        );
      })}
    </div>
  );
}