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
  generateStrategyDraft
} from '../lib/api';

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

export function StrategyChatPage() {
  const navigate = useNavigate();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);

  const hasMessages = messages.length > 0;

  useEffect(() => {
    if (!hasMessages) return;
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, hasMessages]);

  async function handleSubmit(promptText?: string) {
    const prompt = (promptText ?? input).trim();
    if (!prompt || isGenerating) return;

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

      navigate(`/runs/${run.id}`);
    } catch (error) {
      const message = formatUnknownError(error);

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
          <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center px-4 pt-16">
            <div className="space-y-3 text-center">
              <p className="text-xs font-semibold uppercase tracking-[0.35em] text-cyan-300/80">
                US Market Strategy Platform
              </p>
              <h1 className="text-3xl font-semibold tracking-tight text-white md:text-5xl">
                Build a strategy in plain English
              </h1>
              <p className="mx-auto max-w-2xl text-sm text-slate-400 md:text-base">
                Describe a trading idea, review the structured strategy draft, and
                launch a simulation in one flow.
              </p>
            </div>

            <div className="mt-10 w-full max-w-3xl">
              <ExamplePromptChips onSelect={handlePromptChipClick} />
            </div>
          </div>

          <div className="border-t border-white/10 bg-slate-950/80 p-4 backdrop-blur">
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
              />
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-4xl px-4 py-6">
              <ChatMessageList messages={messages} onRunDraft={handleRun} />

              {isGenerating && (
                <div className="mx-auto mt-4 max-w-3xl rounded-3xl border border-white/10 bg-white/[0.03] px-5 py-4 text-sm text-slate-300">
                  Updating your strategy...
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          </div>

          <div className="border-t border-white/10 bg-slate-950/80 p-4 backdrop-blur">
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
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}