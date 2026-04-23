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
      ? 'app-alert-warning'
      : tone === 'info'
        ? 'app-note'
        : 'app-card app-shadow border';

  const eyebrowClass = 'app-label';

  const bodyClass =
    tone === 'default'
      ? 'app-title'
      : 'app-text-muted';

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
      ? 'app-alert-warning'
      : 'app-note';

  const labelClass = 'app-label';

  const valueClass = 'app-title';

  return (
    <div className={`rounded-2xl border px-4 py-3 ${borderClass}`}>
      <div className={`text-[11px] font-semibold uppercase tracking-[0.22em] ${labelClass}`}>
        {label}
      </div>
      <div className={`mt-1 text-sm ${valueClass}`}>{value}</div>
    </div>
  );
}

function AnswerSection({
  title,
  items
}: {
  title: string;
  items: string[];
}) {
  return (
    <div className="app-surface-soft rounded-2xl border px-4 py-4">
      <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
        {title}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {items.map((item) => (
          <span
            key={item}
            className="app-chip-info rounded-full px-3 py-1 text-xs font-semibold tracking-[0.14em]"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function ActionChip({
  text,
  onClick,
  tone = 'info',
  buttonLabel,
  promptText
}: {
  text: string;
  onClick: (prompt: string) => void;
  tone?: 'info' | 'warning';
  buttonLabel?: string;
  promptText?: string;
}) {
  const className =
    tone === 'warning'
      ? 'app-alert-warning inline-flex items-center gap-2 rounded-2xl px-4 py-3 text-left text-sm font-semibold transition hover:opacity-90 cursor-pointer shadow-sm'
      : 'app-note inline-flex items-center gap-2 rounded-2xl px-4 py-3 text-left text-sm font-semibold transition hover:opacity-90 cursor-pointer shadow-sm';

  return (
    <button
      type="button"
      onClick={() => onClick(promptText ?? text)}
      className={className}
    >
      <span>{buttonLabel ?? text}</span>
      <span aria-hidden="true">↗</span>
    </button>
  );
}

function StrategyAnswerCard({
  text,
  answerData,
  onUsePrompt
}: {
  text: string;
  answerData?: {
    answer_type: string;
    supported_symbols?: string[];
    supported_data_start?: string | null;
    supported_data_end?: string | null;
    max_backtest_years?: number | null;
  } | null;
  onUsePrompt?: (prompt: string) => void;
}) {
  if (answerData?.answer_type === 'SUPPORTED_SYMBOLS' && answerData.supported_symbols?.length) {
    return (
      <div className="app-note w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Strategy Assistant
        </div>
        <h3 className="app-title text-lg font-semibold">Supported ETF symbols</h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {answerData.supported_symbols.map((symbol) => (
            <span
              key={symbol}
              className="app-chip-info rounded-full px-3 py-1 text-xs font-semibold tracking-[0.14em]"
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
      <div className="app-note w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Strategy Assistant
        </div>
        <h3 className="app-title text-lg font-semibold">Coverage and plan window</h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <InfoPill label="Supported Start" value={answerData.supported_data_start} />
          <InfoPill label="Supported End" value={answerData.supported_data_end} />
          <InfoPill label="Plan Max Years" value={String(answerData.max_backtest_years)} />
        </div>
      </div>
    );
  }

  if (answerData?.answer_type === 'SUPPORTED_STRATEGY_TYPES') {
    return (
      <div className="app-note w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Strategy Assistant
        </div>
        <h3 className="app-title text-lg font-semibold">Supported strategy types and indicators</h3>
        <p className="app-text-muted mt-2 text-sm leading-6">
          {text}
        </p>

        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <AnswerSection
            title="Core indicators"
            items={[
              'RSI mean reversion',
              'SMA crossover',
              'SMA above state',
              'MACD',
              'KD / stochastic',
              'Seasonality by month',
              'Relative strength'
            ]}
          />
          <AnswerSection
            title="Risk and portfolio controls"
            items={[
              'Stop loss',
              'Take profit',
              'Partial take profit',
              'Cooldown',
              'Allocation',
              'Max position',
              'Core / overlay',
              'Position management'
            ]}
          />
          <AnswerSection
            title="Composite rule editing"
            items={[
              'AND / OR groups',
              'Window rules',
              'Sequence rules',
              'NOT wrapper edits',
              'Group condition edits',
              'Window inner-rule edits',
              'Sequence step edits',
              'Confirmation filters'
            ]}
          />
          <AnswerSection
            title="Other supported edits"
            items={[
              'Tradable symbol',
              'Benchmark symbol',
              'Reference symbols',
              'Transaction cost',
              'Capital',
              'Date range',
              'Seasonality month edits',
              'Relative strength nested edits'
            ]}
          />
        </div>

        <div className="mt-5">
          <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
            Try one of these next
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <ActionChip
              text="Create a QQQ RSI mean reversion strategy"
              onClick={(prompt) => onUsePrompt?.(prompt)}
            />
            <ActionChip
              text="Create an SPY moving average crossover strategy using 10 day and 30 day SMA"
              onClick={(prompt) => onUsePrompt?.(prompt)}
            />
            <ActionChip
              text="Change this strategy to MACD"
              onClick={(prompt) => onUsePrompt?.(prompt)}
            />
            <ActionChip
              text="Add 10% stop loss"
              onClick={(prompt) => onUsePrompt?.(prompt)}
            />
            <ActionChip
              text="Add KD confirmation"
              onClick={(prompt) => onUsePrompt?.(prompt)}
            />
          </div>
        </div>
      </div>
    );
  }

  if (answerData?.answer_type === 'PLAN_LIMITS' && answerData.max_backtest_years) {
    return (
      <div className="app-note w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Strategy Assistant
        </div>
        <h3 className="app-title text-lg font-semibold">Current plan limits</h3>
        <div className="mt-4 grid gap-3 md:grid-cols-1">
          <InfoPill label="Plan Max Years" value={String(answerData.max_backtest_years)} />
        </div>
        <p className="app-text-muted mt-4 text-sm leading-6">{text}</p>
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
      <div className="app-alert-warning w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Validation guidance
        </div>
        <h3 className="app-title text-lg font-semibold">Unsupported symbol</h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>
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
              buttonLabel="Use suggestion"
              promptText="Show me supported ETF symbols"
              tone="warning"
              onClick={(prompt) => onUsePrompt?.(prompt)}
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
      <div className="app-alert-warning w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Validation guidance
        </div>
        <h3 className="app-title text-lg font-semibold">Date range outside coverage</h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <InfoPill label="Supported Start" value={validationData.supported_data_start} tone="warning" />
          <InfoPill label="Supported End" value={validationData.supported_data_end} tone="warning" />
        </div>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionAction} tone="warning" />
            <ActionChip
              text={suggestionAction}
              buttonLabel="Use suggestion"
              promptText="What date range is supported for ETF backtests?"
              tone="warning"
              onClick={(prompt) => onUsePrompt?.(prompt)}
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
      <div className="app-alert-warning w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Validation guidance
        </div>
        <h3 className="app-title text-lg font-semibold">Plan limit exceeded</h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <InfoPill label="Plan Max Years" value={String(validationData.max_backtest_years)} tone="warning" />
          <InfoPill label="Suggested action" value={actionText} tone="warning" />
        </div>
        <div className="mt-4">
          <ActionChip
            text={actionText}
            buttonLabel="Use suggestion"
            promptText="Shorten this strategy to fit my current plan limit"
            tone="warning"
            onClick={(prompt) => onUsePrompt?.(prompt)}
          />
        </div>
      </div>
    );
  }

  if (validationData?.validation_type === 'INVALID_DATE_FORMAT') {
    return (
      <div className="app-alert-warning w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Validation guidance
        </div>
        <h3 className="app-title text-lg font-semibold">Invalid date format</h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionAction} tone="warning" />
            <ActionChip
              text={suggestionAction}
              buttonLabel="Use suggestion"
              promptText="Use ISO format like 2021-04-14"
              tone="warning"
              onClick={(prompt) => onUsePrompt?.(prompt)}
            />
          </div>
        ) : null}
      </div>
    );
  }

  if (validationData?.validation_type === 'UNSUPPORTED_EDIT') {
    return (
      <div className="app-alert-warning w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Validation guidance
        </div>
        <h3 className="app-title text-lg font-semibold">Unsupported edit type</h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionAction} tone="warning" />
            <ActionChip
              text={suggestionAction}
              buttonLabel="Use suggestion"
              promptText="What strategy types or indicators are supported?"
              tone="warning"
              onClick={(prompt) => onUsePrompt?.(prompt)}
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
      <div className="app-note w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Strategy Assistant
        </div>
        <h3 className="app-title text-lg font-semibold">
          {guidanceData.guidance_type === 'NO_CHANGE' ? 'No draft changes made' : 'Draft guidance'}
        </h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {guidanceData.suggested_actions.map((action) => (
            <ActionChip
              key={action}
              text={action}
              onClick={(prompt) => onUsePrompt?.(prompt)}
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
                onUsePrompt={onUsePrompt}
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