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
  value,
  tone = 'info'
}: {
  label: string;
  value: string;
  tone?: 'info' | 'warning';
}) {
  const borderClass =
    tone === 'warning'
      ? 'border-amber-500/20 bg-slate-950/20'
      : 'border-cyan-500/20 bg-slate-950/20';

  const labelClass =
    tone === 'warning'
      ? 'text-amber-200'
      : 'text-cyan-200';

  const valueClass =
    tone === 'warning'
      ? 'text-amber-50'
      : 'text-cyan-50';

  return (
    <div className={`rounded-2xl border px-4 py-3 ${borderClass}`}>
      <div className={`text-[11px] font-semibold uppercase tracking-[0.22em] ${labelClass}`}>
        {label}
      </div>
      <div className={`mt-1 text-sm ${valueClass}`}>{value}</div>
    </div>
  );
}

function ActionChip({
  text,
  onClick,
  tone = 'info'
}: {
  text: string;
  onClick: () => void;
  tone?: 'info' | 'warning';
}) {
  const className =
    tone === 'warning'
      ? 'rounded-2xl border border-amber-500/30 bg-slate-950/20 px-4 py-3 text-left text-sm text-amber-50 transition hover:border-amber-400/50 hover:bg-amber-500/10'
      : 'rounded-2xl border border-cyan-500/30 bg-slate-950/20 px-4 py-3 text-left text-sm text-cyan-50 transition hover:border-cyan-400/50 hover:bg-cyan-500/10';

  return (
    <button type="button" onClick={onClick} className={className}>
      {text}
    </button>
  );
}

function StrategyAnswerCard({
  text,
  answerData
}: {
  text: string;
  answerData?: {
    answer_type: string;
    supported_symbols?: string[];
    supported_data_start?: string | null;
    supported_data_end?: string | null;
    max_backtest_years?: number | null;
  } | null;
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

function StrategyValidationCard({
  text,
  validationData,
  onUsePrompt
}: {
  text: string;
  validationData?: {
    validation_type: string;
    unsupported_symbols?: string[];
    supported_data_start?: string | null;
    supported_data_end?: string | null;
    max_backtest_years?: number | null;
    suggested_action?: string | null;
  } | null;
  onUsePrompt?: (prompt: string) => void;
}) {
  const suggestionAction = validationData?.suggested_action?.trim() || null;

  if (
    validationData?.validation_type === 'UNSUPPORTED_SYMBOL' &&
    validationData.unsupported_symbols?.length
  ) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-amber-500/30 bg-amber-500/10 p-5 text-amber-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-amber-200">
          Validation guidance
        </div>
        <h3 className="text-lg font-semibold text-amber-50">Unsupported symbol</h3>
        <p className="mt-2 text-sm leading-6 text-amber-100/90">{text}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {validationData.unsupported_symbols.map((symbol) => (
            <span
              key={symbol}
              className="rounded-full border border-amber-400/30 bg-slate-950/20 px-3 py-1 text-xs font-semibold tracking-[0.14em] text-amber-50"
            >
              {symbol}
            </span>
          ))}
        </div>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionAction} tone="warning" />
            <ActionChip
              text={suggestionAction}
              tone="warning"
              onClick={() => onUsePrompt?.(suggestionAction)}
            />
          </div>
        ) : null}
      </div>
    );
  }

  if (
    validationData?.validation_type === 'DATA_COVERAGE' &&
    validationData.supported_data_start &&
    validationData.supported_data_end
  ) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-amber-500/30 bg-amber-500/10 p-5 text-amber-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-amber-200">
          Validation guidance
        </div>
        <h3 className="text-lg font-semibold text-amber-50">Date range outside coverage</h3>
        <p className="mt-2 text-sm leading-6 text-amber-100/90">{text}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <InfoPill label="Supported Start" value={validationData.supported_data_start} tone="warning" />
          <InfoPill label="Supported End" value={validationData.supported_data_end} tone="warning" />
        </div>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionAction} tone="warning" />
            <ActionChip
              text={suggestionAction}
              tone="warning"
              onClick={() => onUsePrompt?.(suggestionAction)}
            />
          </div>
        ) : null}
      </div>
    );
  }

  if (
    validationData?.validation_type === 'PLAN_LIMIT' &&
    validationData.max_backtest_years
  ) {
    const actionText = suggestionAction ?? 'Shorten the date range and try again.';

    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-amber-500/30 bg-amber-500/10 p-5 text-amber-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-amber-200">
          Validation guidance
        </div>
        <h3 className="text-lg font-semibold text-amber-50">Plan limit exceeded</h3>
        <p className="mt-2 text-sm leading-6 text-amber-100/90">{text}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <InfoPill label="Plan Max Years" value={String(validationData.max_backtest_years)} tone="warning" />
          <InfoPill label="Suggested action" value={actionText} tone="warning" />
        </div>
        <div className="mt-4">
          <ActionChip text={actionText} tone="warning" onClick={() => onUsePrompt?.(actionText)} />
        </div>
      </div>
    );
  }

  if (validationData?.validation_type === 'INVALID_DATE_FORMAT') {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-amber-500/30 bg-amber-500/10 p-5 text-amber-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-amber-200">
          Validation guidance
        </div>
        <h3 className="text-lg font-semibold text-amber-50">Invalid date format</h3>
        <p className="mt-2 text-sm leading-6 text-amber-100/90">{text}</p>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionAction} tone="warning" />
            <ActionChip
              text={suggestionAction}
              tone="warning"
              onClick={() => onUsePrompt?.(suggestionAction)}
            />
          </div>
        ) : null}
      </div>
    );
  }

  if (validationData?.validation_type === 'UNSUPPORTED_EDIT') {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-amber-500/30 bg-amber-500/10 p-5 text-amber-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-amber-200">
          Validation guidance
        </div>
        <h3 className="text-lg font-semibold text-amber-50">Unsupported edit type</h3>
        <p className="mt-2 text-sm leading-6 text-amber-100/90">{text}</p>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionAction} tone="warning" />
            <ActionChip
              text={suggestionAction}
              tone="warning"
              onClick={() => onUsePrompt?.(suggestionAction)}
            />
          </div>
        ) : null}
      </div>
    );
  }

  return <AssistantMessageCard tone="warning" title="Validation guidance" text={text} />;
}

function StrategyGuidanceCard({
  text,
  guidanceData,
  onUsePrompt
}: {
  text: string;
  guidanceData?: {
    guidance_type: string;
    suggested_actions?: string[];
  } | null;
  onUsePrompt?: (prompt: string) => void;
}) {
  if (guidanceData?.guidance_type && guidanceData.suggested_actions?.length) {
    return (
      <div className="w-full max-w-5xl rounded-[32px] border border-cyan-500/30 bg-cyan-500/10 p-5 text-cyan-100">
        <div className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-200">
          Strategy Assistant
        </div>
        <h3 className="text-lg font-semibold text-cyan-50">
          {guidanceData.guidance_type === 'NO_CHANGE' ? 'No draft changes made' : 'Draft guidance'}
        </h3>
        <p className="mt-2 text-sm leading-6 text-cyan-100/90">{text}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {guidanceData.suggested_actions.map((action) => (
            <ActionChip
              key={action}
              text={action}
              onClick={() => onUsePrompt?.(action)}
            />
          ))}
        </div>
      </div>
    );
  }

  return <AssistantMessageCard tone="info" title="Strategy Assistant" text={text} />;
}

export function ChatMessageList({
  messages,
  onRunDraft,
  onUsePrompt
}: {
  messages: ChatMessage[];
  onRunDraft: (messageId: string) => void;
  onUsePrompt: (prompt: string) => void;
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
          if (message.draft?.guidance_data) {
            return (
              <div key={message.id} className="flex justify-start">
                <StrategyGuidanceCard
                  text={message.text}
                  guidanceData={message.draft.guidance_data}
                  onUsePrompt={onUsePrompt}
                />
              </div>
            );
          }

          return (
            <div key={message.id} className="flex justify-start">
              <StrategyAnswerCard
                text={message.text}
                answerData={message.draft?.answer_data ?? null}
              />
            </div>
          );
        }

        if (responseType === 'VALIDATION_ERROR') {
          return (
            <div key={message.id} className="flex justify-start">
              <StrategyValidationCard
                text={message.text}
                validationData={message.draft?.validation_data ?? null}
                onUsePrompt={onUsePrompt}
              />
            </div>
          );
        }

        return (
          <div key={message.id} className="flex justify-start">
            <AssistantMessageCard tone="default" title="Strategy Assistant" text={message.text} />
          </div>
        );
      })}
    </div>
  );
}