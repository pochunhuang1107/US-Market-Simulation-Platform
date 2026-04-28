import { useState } from 'react';
import { StrategyDraftCard } from './StrategyDraftCard';
import type { ChatMessage } from './types';

type PromptTemplate = {
  id: string;
  label: string;
  buildPrompt: (symbol: string) => string;
};

const DEFAULT_PROMPT_TEMPLATE: PromptTemplate = {
  id: 'rsi',
  label: 'Create a QQQ RSI mean reversion strategy',
  buildPrompt: (symbol) => `Create a ${symbol} RSI mean reversion strategy`
};

const SYMBOL_PROMPT_TEMPLATES: PromptTemplate[] = [
  DEFAULT_PROMPT_TEMPLATE,
  {
    id: 'moving-average',
    label: 'Create an SPY moving average crossover strategy using 10 day and 30 day SMA',
    buildPrompt: (symbol) =>
      `Create a ${symbol} moving average crossover strategy using 10 day and 30 day SMA`
  },
  {
    id: 'seasonality',
    label: 'Create a GLD seasonality strategy',
    buildPrompt: (symbol) => `Create a ${symbol} seasonality strategy`
  }
];

const CAPABILITY_PROMPT_TEMPLATES: PromptTemplate[] = [
  DEFAULT_PROMPT_TEMPLATE,
  SYMBOL_PROMPT_TEMPLATES[1],
  {
    id: 'core-overlay',
    label: 'Create a QQQ core-overlay strategy with 60% core and 40% RSI overlay',
    buildPrompt: (symbol) =>
      `Create a ${symbol} core-overlay strategy with 60% core and 40% RSI overlay`
  },
  {
    id: 'relative-strength',
    label: 'Create a QQQ strategy that enters when QQQ outperforms SPY over 20 days',
    buildPrompt: (symbol) =>
      `Create a ${symbol} strategy that enters when ${symbol} outperforms SPY over 20 days`
  }
];

function isRunnableDraftMessage(message: ChatMessage): boolean {
  return (
    message.role === 'assistant' &&
    Boolean(message.draft) &&
    message.draft?.response_type !== 'ANSWER' &&
    message.draft?.response_type !== 'VALIDATION_ERROR' &&
    Boolean(message.draft?.config)
  );
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

function SymbolChipButton({
  symbol,
  template,
  onClick
}: {
  symbol: string;
  template: PromptTemplate;
  onClick: (prompt: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onClick(template.buildPrompt(symbol))}
      className="app-chip-info rounded-full px-3 py-1 text-xs font-semibold tracking-[0.14em] transition hover:opacity-90 cursor-pointer shadow-sm"
    >
      {symbol}
    </button>
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
  const [selectedSymbolTemplate, setSelectedSymbolTemplate] = useState<PromptTemplate>(
    DEFAULT_PROMPT_TEMPLATE
  );

  if (answerData?.answer_type === 'SUPPORTED_SYMBOLS' && answerData.supported_symbols?.length) {
    const unsupportedTitle = text.match(/^([A-Z][A-Z0-9, ]*) (?:is|are) not currently available\./);
    const unsupportedSymbolTitle = unsupportedTitle
      ? `${unsupportedTitle[1]} ${unsupportedTitle[1].includes(',') ? 'are' : 'is'} not supported yet`
      : 'Supported ETF symbols';

    return (
      <div className="app-note w-full max-w-5xl rounded-[32px] p-5">
        <div className="app-label mb-3 text-xs font-semibold uppercase tracking-[0.22em]">
          Strategy Assistant
        </div>
        <h3 className="app-title text-lg font-semibold">
          {unsupportedSymbolTitle}
        </h3>
        <p className="app-text-muted mt-2 text-sm leading-6">{text}</p>

        <div className="mt-5">
          <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
            Click a symbol to use the selected template
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {answerData.supported_symbols.map((symbol) => (
              <SymbolChipButton
                key={symbol}
                symbol={symbol}
                template={selectedSymbolTemplate}
                onClick={(prompt) => onUsePrompt?.(prompt)}
              />
            ))}
          </div>
        </div>

        <div className="mt-5">
          <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
            Or try one of these templates
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {SYMBOL_PROMPT_TEMPLATES.map((template) => (
              <ActionChip
                key={template.id}
                text={template.label}
                onClick={() => {
                  setSelectedSymbolTemplate(template);
                  onUsePrompt?.(template.label);
                }}
              />
            ))}
          </div>
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
            title="Indicators and strategy styles"
            items={[
              'RSI mean reversion',
              'SMA / moving-average crossover',
              'SMA trend-state rules',
              'MACD',
              'KD / stochastic',
              'Relative strength',
              'Seasonality'
            ]}
          />
          <AnswerSection
            title="Risk, comparison, and allocation"
            items={[
              'Stop loss',
              'Take profit',
              'Cooldown',
              'Benchmark comparison',
              'Core-overlay allocation'
            ]}
          />
        </div>

        <div className="mt-5">
          <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
            Try one of these next
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {CAPABILITY_PROMPT_TEMPLATES.map((template) => (
              <ActionChip
                key={template.id}
                text={template.label}
                onClick={(prompt) => onUsePrompt?.(prompt)}
              />
            ))}
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

function getValidationBodyText({
  validationType,
  fallbackText
}: {
  validationType?: string;
  fallbackText: string;
}) {
  switch (validationType) {
    case 'UNSUPPORTED_SYMBOL':
      return 'This platform is currently ETF-first. Choose one of the supported ETF symbols to create a valid strategy draft.';

    case 'DATA_COVERAGE':
      return 'The requested date range is outside the available ETF data window. Use the supported coverage range below.';

    case 'PLAN_LIMIT':
      return 'The requested backtest is longer than your current plan allows. Shorten the date range and try again.';

    case 'INVALID_DATE_FORMAT':
      return 'The date could not be parsed. Use ISO date format so the builder can apply the change safely.';

    case 'UNSUPPORTED_EDIT':
      return 'That edit is not supported by the deterministic builder yet. You can review the supported indicators and edit types.';

    default:
      return fallbackText;
  }
}

function getValidationSuggestionText({
  validationType,
  fallbackSuggestion
}: {
  validationType?: string;
  fallbackSuggestion: string | null;
}) {
  switch (validationType) {
    case 'UNSUPPORTED_SYMBOL':
      return 'View supported ETF symbols.';

    case 'DATA_COVERAGE':
      return 'Check supported ETF date coverage.';

    case 'PLAN_LIMIT':
      return 'Shorten this strategy to fit the current plan.';

    case 'INVALID_DATE_FORMAT':
      return 'Use ISO format like 2021-04-14.';

    case 'UNSUPPORTED_EDIT':
      return 'Review supported strategy types and indicators.';

    default:
      return fallbackSuggestion;
  }
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
  const validationType = validationData?.validation_type;
  const suggestionAction = validationData?.suggested_action?.trim() || null;
  const bodyText = getValidationBodyText({
    validationType,
    fallbackText: text
  });
  const suggestionText = getValidationSuggestionText({
    validationType,
    fallbackSuggestion: suggestionAction
  });

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
        <p className="app-text-muted mt-2 text-sm leading-6">{bodyText}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {validationData.unsupported_symbols.map((symbol) => (
            <span
              key={symbol}
              className="app-chip-warning rounded-full px-3 py-1 text-xs font-semibold tracking-[0.14em]"
            >
              {symbol}
            </span>
          ))}
        </div>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionText ?? suggestionAction ?? 'Review the suggested next step.'} tone="warning" />
            <ActionChip
              text={suggestionAction}
              buttonLabel="Use as next prompt"
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
        <p className="app-text-muted mt-2 text-sm leading-6">{bodyText}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <InfoPill label="Supported Start" value={validationData.supported_data_start} tone="warning" />
          <InfoPill label="Supported End" value={validationData.supported_data_end} tone="warning" />
        </div>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionText ?? suggestionAction ?? 'Review the suggested next step.'} tone="warning" />
            <ActionChip
              text={suggestionAction}
              buttonLabel="Use as next prompt"
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
        <p className="app-text-muted mt-2 text-sm leading-6">{bodyText}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <InfoPill label="Plan Max Years" value={String(validationData.max_backtest_years)} tone="warning" />
          <InfoPill label="Suggested action" value={suggestionText ?? actionText} tone="warning" />
        </div>
        <div className="mt-4">
          <ActionChip
            text={actionText}
            buttonLabel="Use as next prompt"
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
        <p className="app-text-muted mt-2 text-sm leading-6">{bodyText}</p>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionText ?? suggestionAction ?? 'Review the suggested next step.'} tone="warning" />
            <ActionChip
              text={suggestionAction}
              buttonLabel="Use as next prompt"
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
        <p className="app-text-muted mt-2 text-sm leading-6">{bodyText}</p>
        {suggestionAction ? (
          <div className="mt-4 space-y-3">
            <InfoPill label="Suggested action" value={suggestionText ?? suggestionAction ?? 'Review the suggested next step.'} tone="warning" />
            <ActionChip
              text={suggestionAction}
              buttonLabel="Use as next prompt"
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
        <p className="app-text-muted mt-2 text-sm leading-6">
          {guidanceData.guidance_type === 'NO_CHANGE'
            ? 'No draft settings changed. Try one of these supported edits to keep iterating.'
            : text}
        </p>
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
  const latestDraftMessageId = [...messages]
    .reverse()
    .find(isRunnableDraftMessage)?.id;

  return (
    <div className="space-y-6">
      {messages.map((message) => {
        if (message.role === 'user') {
          return (
            <div key={message.id} className="flex justify-end">
              <div className="app-button-primary max-w-3xl whitespace-pre-wrap break-words rounded-[28px] px-5 py-4 text-sm leading-6 shadow-lg shadow-cyan-950/20">
                {message.text}
              </div>
            </div>
          );
        }

        const hasDraftConfig = isRunnableDraftMessage(message);

        if (hasDraftConfig && message.draft) {
          return (
            <div key={message.id} className="flex justify-start">
              <div className="w-full max-w-5xl">
                <StrategyDraftCard
                  draft={message.draft}
                  onRun={() => onRunDraft(message.id)}
                  onUsePrompt={onUsePrompt}
                  isLatestDraft={message.id === latestDraftMessageId}
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
