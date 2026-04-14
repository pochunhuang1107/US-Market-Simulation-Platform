import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ChatMessageList } from '../components/strategy-chat/ChatMessageList';
import { ExamplePromptChips } from '../components/strategy-chat/ExamplePromptChips';
import { PromptComposer } from '../components/strategy-chat/PromptComposer';
import type { ChatMessage } from '../components/strategy-chat/types';
import {
  createRun,
  createStrategy,
  createStrategyVersion,
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

  return message;
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

  const { plan, usage } = entitlements;

  return (
    <div className="app-surface-soft flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-xs">
      <div>
        <span className="app-text-muted">Plan</span>{' '}
        <span className="font-semibold app-title">{plan.name}</span>
      </div>
      <div>
        <span className="app-text-muted">Runs left today</span>{' '}
        <span className="font-semibold app-title">{usage.daily_runs_remaining}</span>
      </div>
      <div>
        <span className="app-text-muted">Saved strategies left</span>{' '}
        <span className="font-semibold app-title">{usage.saved_strategies_remaining}</span>
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
      const draft = await generateStrategyDraft(
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

      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: currentConfig
          ? 'Updated your strategy draft based on the latest configuration.'
          : 'Here is your strategy draft.',
        draft
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

      const strategy = await createStrategy({
        name: 'chat-strategy',
        description: 'Generated from Strategy Chat',
        strategy_type: 'SINGLE_ASSET',
        config
      });

      const version = await createStrategyVersion(strategy.strategy_id, {
        config
      });

      const run = await createRun({
        strategy_id: strategy.strategy_id,
        strategy_version_id: version.version_id,
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
      const message = formatLimitError(error);

      console.error('Run simulation failed:', error);
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
                submitting={isGenerating}
                placeholder="Describe your strategy..."
                submitLabel="Generate Strategy"
                disabled={Boolean(entitlements && !entitlements.features.allow_ai_builder)}
              />
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-4xl px-4 py-6">
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
                  Updating your strategy...
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          </div>

          <div className="border-t app-header p-4 backdrop-blur">
            <div className="mx-auto w-full max-w-3xl">
              <PromptComposer
                value={input}
                onChange={setInput}
                onSubmit={() => {
                  void handleSubmit();
                }}
                submitting={isGenerating}
                placeholder="Refine the strategy or describe a new adjustment..."
                submitLabel="Update Strategy"
                disabled={Boolean(entitlements && !entitlements.features.allow_ai_builder)}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
