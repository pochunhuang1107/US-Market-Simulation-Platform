import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ChatMessageList } from '../components/strategy-chat/ChatMessageList';
import { ExamplePromptChips } from '../components/strategy-chat/ExamplePromptChips';
import { PromptComposer } from '../components/strategy-chat/PromptComposer';
import type { ChatMessage } from '../components/strategy-chat/types';
import {
  ApiRequestError,
  createRun,
  enqueueRun,
  fetchMeEntitlements,
  generateStrategyDraft
} from '../lib/api';
import type { MeEntitlementsResponse } from '../types/api';

function extractDraftConfig(draft: unknown): Record<string, unknown> | null {
  if (!draft || typeof draft !== 'object') return null;

  const record = draft as {
    strategy_config?: unknown;
    config?: unknown;
  };

  if (record.strategy_config && typeof record.strategy_config === 'object') {
    return record.strategy_config as Record<string, unknown>;
  }

  if (record.config && typeof record.config === 'object') {
    return record.config as Record<string, unknown>;
  }

  return null;
}

function getLatestDraftConfig(messages: ChatMessage[]): Record<string, unknown> | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message.role !== 'assistant' || !message.draft) continue;

    const config = extractDraftConfig(message.draft);
    if (config) return config;
  }

  return null;
}

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  if (typeof error === 'string') {
    return error;
  }

  if (error && typeof error === 'object') {
    const record = error as {
      detail?: unknown;
      message?: unknown;
      error?: unknown;
    };

    if (typeof record.detail === 'string') return record.detail;
    if (typeof record.message === 'string') return record.message;
    if (typeof record.error === 'string') return record.error;

    try {
      return JSON.stringify(error, null, 2);
    } catch {
      return 'Request failed.';
    }
  }

  return 'Request failed.';
}

function formatLimitError(error: unknown): string {
  const message = formatUnknownError(error);

  if (message.includes('Daily run limit reached')) {
    return 'You have reached your daily simulation limit. You can still edit your strategy draft, but running a new simulation is locked for now.';
  }

  if (message.includes('Saved strategy limit reached')) {
    return 'You have reached your saved strategy limit. Remove an older saved strategy or upgrade your plan to save and run another one.';
  }

  if (message.includes('strategy builder access')) {
    return 'Your current plan does not include Strategy Builder access.';
  }

  if (message.includes('version history')) {
    return 'Your current plan does not include strategy version history.';
  }

  if (message.includes('Daily builder prompt limit reached')) {
    return 'You have reached your daily Strategy Builder prompt limit for today.';
  }

  if (message.includes('Prompt exceeds your plan limit')) {
    return message;
  }

  if (message.includes('Unsupported symbol')) {
    return message;
  }

  if (message.includes('outside supported data coverage')) {
    return message;
  }

  if (message.includes('backtest window exceeds your plan limit')) {
    return message;
  }

  return message;
}

function extractDuplicateRunId(error: unknown): string | null {
  if (error instanceof ApiRequestError && error.status === 409 && error.body && typeof error.body === 'object') {
    const record = error.body as {
      detail?: {
        code?: unknown;
        existing_run_id?: unknown;
      };
    };

    if (
      record.detail &&
      typeof record.detail === 'object' &&
      record.detail.code === 'DUPLICATE_ACTIVE_RUN' &&
      typeof record.detail.existing_run_id === 'string'
    ) {
      return record.detail.existing_run_id;
    }
  }

  const message = formatUnknownError(error);
  const match = message.match(/already active:\s*([0-9a-f-]{36})/i);
  return match ? match[1] : null;
}

function formatDuplicateRunMessage(error: unknown): string {
  const existingRunId = extractDuplicateRunId(error);
  if (existingRunId) {
    return 'This simulation is already running. Opening the existing run instead.';
  }
  return formatLimitError(error);
}

function EntitlementSummary({
  entitlements,
  loading,
  error
}: {
  entitlements: MeEntitlementsResponse | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="app-surface-soft rounded-2xl border px-4 py-3 text-xs app-text-muted">
        Loading plan limits...
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
        {error}
      </div>
    );
  }

  if (!entitlements) return null;

  const { plan, usage, limits } = entitlements;

  return (
    <div className="app-surface-soft flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-xs">
      <div>
        <span className="app-text-muted">Plan</span>{' '}
        <span className="font-semibold app-title">{plan.name}</span>
      </div>
      <div>
        <span className="app-text-muted">Prompts left today</span>{' '}
        <span className="font-semibold app-title">{usage.builder_prompts_remaining_today}</span>
      </div>
      <div>
        <span className="app-text-muted">Runs left today</span>{' '}
        <span className="font-semibold app-title">{usage.daily_runs_remaining}</span>
      </div>
      <div>
        <span className="app-text-muted">Max chars</span>{' '}
        <span className="font-semibold app-title">{limits.builder_prompt_max_chars}</span>
      </div>
    </div>
  );
}

export function StrategyChatPage() {
  const navigate = useNavigate();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [entitlements, setEntitlements] = useState<MeEntitlementsResponse | null>(null);
  const [isLoadingEntitlements, setIsLoadingEntitlements] = useState(true);
  const [entitlementError, setEntitlementError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement | null>(null);

  const hasMessages = messages.length > 0;

  const promptMaxChars = entitlements?.limits.builder_prompt_max_chars ?? 1000;
  const promptChars = input.length;
  const isPromptTooLong = promptChars > promptMaxChars;

  useEffect(() => {
    let isMounted = true;

    async function loadEntitlements() {
      setIsLoadingEntitlements(true);
      setEntitlementError(null);

      try {
        const data = await fetchMeEntitlements();

        if (!isMounted) return;
        setEntitlements(data);
      } catch (error) {
        if (!isMounted) return;
        setEntitlementError(formatLimitError(error));
      } finally {
        if (isMounted) {
          setIsLoadingEntitlements(false);
        }
      }
    }

    void loadEntitlements();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!hasMessages) return;
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, hasMessages]);

  async function handleSubmit(promptText?: string) {
    const prompt = (promptText ?? input).trim();
    if (!prompt || isGenerating) return;
    if (isPromptTooLong) return;

    if (entitlements && !entitlements.features.allow_ai_builder) {
      const assistantError: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: 'Your current plan does not include Strategy Builder access.'
      };

      setMessages((prev) => [...prev, assistantError]);
      return;
    }

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      text: prompt
    };

    const nextMessages = [...messages, userMessage];
    const currentConfig = getLatestDraftConfig(messages);

    setMessages(nextMessages);
    setInput('');
    setIsGenerating(true);

    try {
      const response = await generateStrategyDraft(
        currentConfig
          ? {
              prompt,
              context: {
                current_config: currentConfig
              }
            }
          : {
              prompt
            }
      );

      const hasDraftConfig =
        (response.response_type === 'CREATE_DRAFT' ||
          response.response_type === 'UPDATE_DRAFT') &&
        Boolean(extractDraftConfig(response));

      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: response.message,
        draft: hasDraftConfig ? response : undefined
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      const assistantError: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: formatUnknownError(error)
      };

      setMessages((prev) => [...prev, assistantError]);
    } finally {
      setIsGenerating(false);

      try {
        const refreshedEntitlements = await fetchMeEntitlements();
        setEntitlements(refreshedEntitlements);
      } catch {
        // keep existing entitlement state if refresh fails
      }
    }
  }

  async function handleRun(messageId: string) {
    const msg = messages.find((m) => m.id === messageId);
    if (!msg || msg.role !== 'assistant' || !msg.draft) return;

    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId ? { ...m, isRunning: true, runError: null } : m
      )
    );

    try {
      const config = extractDraftConfig(msg.draft);

      if (!config) {
        throw new Error('No strategy config returned from strategy builder.');
      }

      const run = await createRun({
        draft_config: config,
        run_type: 'SIMULATION',
        executor_type: 'SIMULATION_EXECUTOR',
        request_payload: {},
        max_attempts: 1
      });

      await enqueueRun(run.id);

      try {
        const refreshedEntitlements = await fetchMeEntitlements();
        setEntitlements(refreshedEntitlements);
      } catch {
        // Do not block navigation if entitlement refresh fails.
      }

      navigate(`/runs/${run.id}`);
    } catch (error) {
      const duplicateRunId = extractDuplicateRunId(error);

      console.error('Run simulation failed:', error);

      if (duplicateRunId) {
        const message = formatDuplicateRunMessage(error);

        setMessages((prev) =>
          prev.map((m) =>
            m.id === messageId
              ? {
                  ...m,
                  isRunning: false,
                  runError: message
                }
              : m
          )
        );

        try {
          const refreshedEntitlements = await fetchMeEntitlements();
          setEntitlements(refreshedEntitlements);
        } catch {
          // keep current entitlement state if refresh fails
        }

        navigate(`/runs/${duplicateRunId}`);
        return;
      }

      const message = formatLimitError(error);
      window.alert(message);

      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId
            ? {
                ...m,
                isRunning: false,
                runError: message
              }
            : m
        )
      );
    }
  }

  function handlePromptChipClick(prompt: string) {
    setInput(prompt);
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {!hasMessages ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center px-4 pt-16 pb-28">
            <div className="space-y-3 text-center">
              <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.35em]">
                US Market Strategy Platform
              </p>
              <h1 className="text-3xl font-semibold tracking-tight app-title md:text-5xl">
                Build a strategy in plain English
              </h1>
              <p className="mx-auto max-w-2xl text-sm app-text-muted md:text-base">
                Describe a trading idea, review the structured strategy draft, and
                launch a simulation in one flow.
              </p>
            </div>

            <div className="mt-8 w-full max-w-3xl">
              <EntitlementSummary
                entitlements={entitlements}
                loading={isLoadingEntitlements}
                error={entitlementError}
              />
            </div>

            <div className="mt-6 w-full max-w-3xl">
              <ExamplePromptChips onSelect={handlePromptChipClick} />
            </div>
          </div>

          <div className="fixed bottom-0 left-0 right-0 border-t app-header p-4 backdrop-blur">
            <div className="mx-auto w-full max-w-3xl">
              <PromptComposer
                value={input}
                onChange={setInput}
                onSubmit={() => {
                  void handleSubmit();
                }}
                submitting={isGenerating || isPromptTooLong}
                placeholder="Describe your strategy..."
                submitLabel="Generate Strategy"
                disabled={Boolean(entitlements && !entitlements.features.allow_ai_builder)}
              />
              <div className="mt-2 flex items-center justify-between px-2 text-xs">
                <span className={isPromptTooLong ? 'text-amber-300' : 'app-text-muted'}>
                  {isPromptTooLong
                    ? `Prompt is too long for your plan (${promptMaxChars} max).`
                    : `ETF-only coverage. Your current plan allows up to ${entitlements?.limits.max_backtest_years ?? 5} years per backtest.`}
                </span>
                <span className={isPromptTooLong ? 'text-amber-300' : 'app-text-muted'}>
                  {promptChars} / {promptMaxChars}
                </span>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-4xl px-4 py-6 pb-40">
              <div className="mb-5">
                <EntitlementSummary
                  entitlements={entitlements}
                  loading={isLoadingEntitlements}
                  error={entitlementError}
                />
              </div>

              <ChatMessageList messages={messages} onRunDraft={handleRun} />

              {isGenerating && (
                <div className="app-card mx-auto mt-4 max-w-3xl rounded-3xl border px-5 py-4 text-sm app-text-muted">
                  Thinking through your request...
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          </div>

          <div className="fixed bottom-0 left-0 right-0 z-20 border-t app-header p-4 backdrop-blur">
            <div className="mx-auto w-full max-w-3xl">
              <PromptComposer
                value={input}
                onChange={setInput}
                onSubmit={() => {
                  void handleSubmit();
                }}
                submitting={isGenerating || isPromptTooLong}
                placeholder="Refine the strategy or describe a new adjustment..."
                submitLabel="Update Strategy"
                disabled={Boolean(entitlements && !entitlements.features.allow_ai_builder)}
              />
              <div className="mt-2 flex items-center justify-between px-2 text-xs">
                <span className={isPromptTooLong ? 'text-amber-300' : 'app-text-muted'}>
                  {isPromptTooLong
                    ? `Prompt is too long for your plan (${promptMaxChars} max).`
                    : `Builder prompts left today: ${entitlements?.usage.builder_prompts_remaining_today ?? '—'}`}
                </span>
                <span className={isPromptTooLong ? 'text-amber-300' : 'app-text-muted'}>
                  {promptChars} / {promptMaxChars}
                </span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
