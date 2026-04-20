import { StrategyDraftCard } from './StrategyDraftCard';
import type { ChatMessage } from './types';

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

function StrategyAnswerCard({
  text,
  answerData
}: {
  text: string;
  answerData?: ChatMessage extends infer _T
    ? {
        answer_type: string;
        supported_symbols?: string[];
        supported_data_start?: string | null;
        supported_data_end?: string | null;
        max_backtest_years?: number | null;
      } | null
    : never;
}) {
  if (answerData?.answer_type === 'SUPPORTED_SYMBOLS' && answerData.supported_symbols?.length) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-cyan-500/30 bg-cyan-500/10 p-5 text-cyan-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
          Strategy Assistant
        </div>
        <h3 className="text-lg font-semibold text-cyan-50">Supported ETF symbols</h3>
        <p className="mt-2 text-sm leading-6 text-cyan-100/90">{text}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {answerData.supported_symbols.map((symbol) => (
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

  if (
    answerData?.answer_type === 'DATA_COVERAGE' &&
    answerData.supported_data_start &&
    answerData.supported_data_end &&
    answerData.max_backtest_years
  ) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-cyan-500/30 bg-cyan-500/10 p-5 text-cyan-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
          Strategy Assistant
        </div>
        <h3 className="text-lg font-semibold text-cyan-50">Coverage and plan window</h3>
        <p className="mt-2 text-sm leading-6 text-cyan-100/90">{text}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <InfoPill label="Supported Start" value={answerData.supported_data_start} />
          <InfoPill label="Supported End" value={answerData.supported_data_end} />
          <InfoPill label="Plan Max Years" value={String(answerData.max_backtest_years)} />
        </div>
      </div>
    );
  }

  if (answerData?.answer_type === 'PLAN_LIMITS' && answerData.max_backtest_years) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-cyan-500/30 bg-cyan-500/10 p-5 text-cyan-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
          Strategy Assistant
        </div>
        <h3 className="text-lg font-semibold text-cyan-50">Current plan limits</h3>
        <div className="mt-4 grid gap-3 md:grid-cols-1">
          <InfoPill label="Plan Max Years" value={String(answerData.max_backtest_years)} />
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
              <StrategyAnswerCard
                text={message.text}
                answerData={message.draft?.answer_data ?? null}
              />
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