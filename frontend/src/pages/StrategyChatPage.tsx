import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { ChatMessageList } from '../components/strategy-chat/ChatMessageList';
import { ExamplePromptChips } from '../components/strategy-chat/ExamplePromptChips';
import { PromptComposer } from '../components/strategy-chat/PromptComposer';
import type { ChatMessage } from '../components/strategy-chat/types';
import { useAppAuth } from '../auth/AppAuthProvider';
import {
  ApiRequestError,
  createRun,
  enqueueRun,
  fetchMeEntitlements,
  generateStrategyDraft
} from '../lib/api';
import {
  findStrategyGalleryTemplate,
  type StrategyGalleryTemplate
} from '../lib/strategyGalleryTemplates';
import type {
  MeEntitlementsResponse,
  StrategyBuilderGenerateResponse
} from '../types/api';

type StrategyChatLocationState = {
  homeResetKey?: number;
  prefillPrompt?: string;
  source?: string;
  sourceLabel?: string;
  sourceRunId?: string;
  sourceDraftConfig?: Record<string, unknown> | null;
} | null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function extractDraftConfig(draft: unknown): Record<string, unknown> | null {
  if (!draft || typeof draft !== 'object') return null;

  const record = draft as {
    strategy_config?: unknown;
    config?: unknown;
    sweep_draft?: unknown;
  };

  if (isRecord(record.strategy_config)) {
    return record.strategy_config;
  }

  if (isRecord(record.config)) {
    return record.config;
  }

  if (isRecord(record.sweep_draft)) {
    return record.sweep_draft;
  }

  return null;
}

function extractSweepDraft(draft: unknown): StrategyBuilderGenerateResponse['sweep_draft'] | null {
  if (!draft || typeof draft !== 'object') return null;

  const record = draft as {
    response_type?: unknown;
    sweep_draft?: unknown;
  };

  if (record.response_type !== 'PARAMETER_SWEEP_DRAFT') return null;
  if (!isRecord(record.sweep_draft)) return null;

  return record.sweep_draft as unknown as StrategyBuilderGenerateResponse['sweep_draft'];
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

function getLatestDraftHeadline(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (message.role !== 'assistant' || !message.draft) continue;

    const config = extractDraftConfig(message.draft);
    if (!config) continue;

    const baseConfig = isRecord(config.base_config) ? config.base_config : config;

    if (typeof config.name === 'string' && config.name.trim()) {
      return config.name;
    }

    if (typeof baseConfig.name === 'string' && baseConfig.name.trim()) {
      return `${baseConfig.name} sweep`;
    }

    if (typeof baseConfig.tradable_symbol === 'string' && baseConfig.tradable_symbol.trim()) {
      return `${baseConfig.tradable_symbol} draft`;
    }

    return 'Latest draft';
  }

  return null;
}

function buildSeededDraftMessage({
  config,
  sourceRunId,
  sourceLabel
}: {
  config: Record<string, unknown>;
  sourceRunId?: string;
  sourceLabel?: string;
}): ChatMessage {
  const strategyName =
    typeof config.name === 'string' && config.name.trim()
      ? config.name
      : typeof config.tradable_symbol === 'string' && config.tradable_symbol.trim()
      ? `${config.tradable_symbol} strategy`
      : 'Imported strategy';
  const importedFrom = sourceLabel?.trim() || 'Strategy Builder';

  return {
    id: crypto.randomUUID(),
    role: 'assistant',
    text: sourceRunId
      ? `Loaded ${strategyName} from result ${sourceRunId}.`
      : `Loaded ${strategyName} from ${importedFrom}.`,
    draft: {
      response_type: 'UPDATE_DRAFT',
      message: sourceRunId
        ? `Loaded ${strategyName} from result ${sourceRunId}.`
        : `Loaded ${strategyName} from ${importedFrom}.`,
      config,
      summary: `Loaded ${strategyName} as the current editing context.`,
      warnings: [],
      assumptions: [
        sourceRunId
          ? 'Imported the previous result configuration as the current builder context.'
          : `Imported the ${importedFrom} configuration as the current builder context.`
      ],
      changes: [],
      answer_data: null,
      validation_data: null,
      guidance_data: null,
      sweep_draft: null
    }
  };
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
    return 'Saved strategy limit reached. Go to Strategy Library and archive an older strategy, then try saving again.';
  }

  if (message.includes('strategy builder access')) {
    return 'Your current plan does not include Strategy Builder access.';
  }

  if (message.includes('version history')) {
    return 'Your current plan does not include strategy version history.';
  }

  if (message.includes('Custom rotation strategies require Research access')) {
    return message;
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
    return 'This result is already active. Redirecting you to the existing result.';
  }
  return formatLimitError(error);
}

function extractStructuredBuilderError(
  error: unknown
): StrategyBuilderGenerateResponse | null {
  if (!(error instanceof ApiRequestError)) return null;
  if (!error.body || typeof error.body !== 'object') return null;

  const record = error.body as Partial<StrategyBuilderGenerateResponse> & {
    message?: unknown;
    response_type?: unknown;
    validation_data?: unknown;
    guidance_data?: unknown;
  };

  const responseType =
    typeof record.response_type === 'string' ? record.response_type : null;

  if (
    responseType !== 'VALIDATION_ERROR' &&
    responseType !== 'ANSWER' &&
    !record.validation_data &&
    !record.guidance_data
  ) {
    return null;
  }

  return {
    response_type: (responseType ?? 'VALIDATION_ERROR') as StrategyBuilderGenerateResponse['response_type'],
    message:
      typeof record.message === 'string' ? record.message : formatUnknownError(error),
    config: (record.config as StrategyBuilderGenerateResponse['config']) ?? null,
    summary: (record.summary as StrategyBuilderGenerateResponse['summary']) ?? null,
    warnings: Array.isArray(record.warnings) ? record.warnings : [],
    assumptions: Array.isArray(record.assumptions) ? record.assumptions : [],
    changes: Array.isArray(record.changes) ? record.changes : [],
    answer_data: (record.answer_data as StrategyBuilderGenerateResponse['answer_data']) ?? null,
    validation_data:
      (record.validation_data as StrategyBuilderGenerateResponse['validation_data']) ?? null,
    guidance_data:
      (record.guidance_data as StrategyBuilderGenerateResponse['guidance_data']) ?? null,
    sweep_draft: (record.sweep_draft as StrategyBuilderGenerateResponse['sweep_draft']) ?? null
  };
}

function decrementBuilderPromptQuota(
  entitlements: MeEntitlementsResponse
): MeEntitlementsResponse {
  const remaining = entitlements.usage.builder_prompts_remaining_today;
  const usedToday = entitlements.usage.builder_prompts_used_today;
  const shouldIncrementUsed = remaining > 0;

  return {
    ...entitlements,
    usage: {
      ...entitlements.usage,
      builder_prompts_remaining_today: Math.max(0, remaining - 1),
      builder_prompts_used_today: shouldIncrementUsed ? usedToday + 1 : usedToday
    }
  };
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
  if (entitlements) {
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
          <span className="app-text-muted">Results left today</span>{' '}
          <span className="font-semibold app-title">{usage.daily_runs_remaining}</span>
        </div>
        <div>
          <span className="app-text-muted">Max chars</span>{' '}
          <span className="font-semibold app-title">{limits.builder_prompt_max_chars}</span>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="app-surface-soft rounded-2xl border px-4 py-3 text-xs app-text-muted">
        Loading plan limits...
      </div>
    );
  }

  if (error) {
    return (
      <div className="app-alert-warning rounded-2xl border px-4 py-3 text-xs">
        {error}
      </div>
    );
  }

  return null;
}

function FeaturedStrategyIdeas({
  onUseTemplate
}: {
  onUseTemplate: (template: StrategyGalleryTemplate) => void;
}) {
  const featuredTemplates = [
    findStrategyGalleryTemplate('xle-rsi-defensive-pullback'),
    findStrategyGalleryTemplate('iwm-rsi-defensive-pullback'),
    findStrategyGalleryTemplate('qqq-core-vix-trend-overlay')
  ].filter((template): template is StrategyGalleryTemplate => Boolean(template));

  return (
    <section className="w-full">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="app-label text-[11px] font-semibold uppercase tracking-[0.22em]">
            Featured strategy ideas
          </div>
          <p className="mt-1 text-sm app-text-muted">Start from a validated template instead of a blank prompt.</p>
        </div>
        <Link to="/gallery" className="app-button-secondary rounded-xl px-3 py-1.5 text-xs font-semibold transition">
          Open gallery
        </Link>
      </div>

      <div className="grid items-stretch gap-3 md:auto-rows-fr md:grid-cols-3">
        {featuredTemplates.map((template) => (
          <article key={template.id} className="app-example-prompt flex h-full min-h-[190px] flex-col rounded-xl border p-3.5 text-left">
            <div className="flex min-h-[58px] items-start justify-between gap-2">
              <p className="min-w-0 text-sm font-semibold leading-5 app-title">{template.title}</p>
              <span className="app-pill shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-semibold">
                {template.style}
              </span>
            </div>
            <p className="mt-2 flex-1 text-xs leading-5 app-text-muted">{template.expectedBehavior}</p>
            <div className="mt-auto flex flex-wrap gap-2 pt-3">
              <button
                type="button"
                onClick={() => onUseTemplate(template)}
                className="app-button-primary whitespace-nowrap rounded-xl px-3 py-1.5 text-xs font-semibold transition"
              >
                Use in builder
              </button>
              <Link
                to={`/gallery?template=${template.id}`}
                className="app-button-secondary whitespace-nowrap rounded-xl px-3 py-1.5 text-xs font-semibold transition"
              >
                Preview
              </Link>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function StrategyChatPage() {
  const auth = useAppAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [entitlements, setEntitlements] = useState<MeEntitlementsResponse | null>(null);
  const [isLoadingEntitlements, setIsLoadingEntitlements] = useState(true);
  const [entitlementError, setEntitlementError] = useState<string | null>(null);
  const [composerFocusKey, setComposerFocusKey] = useState(0);
  const [sourceRunId, setSourceRunId] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const consumedPrefillRef = useRef<string | null>(null);
  const builderRequestIdRef = useRef(0);

  const hasMessages = messages.length > 0;

  const latestDraftConfig = getLatestDraftConfig(messages);
  const latestDraftHeadline = getLatestDraftHeadline(messages);

  const promptMaxChars = entitlements?.limits.builder_prompt_max_chars ?? 1000;
  const promptChars = input.length;
  const isPromptTooLong = promptChars > promptMaxChars;

  useEffect(() => {
    let isMounted = true;

    async function loadEntitlements() {
      if (auth.isAuth0Mode && (auth.isLoading || !auth.isAuthenticated)) {
        setIsLoadingEntitlements(auth.isLoading);
        setEntitlementError(null);
        return;
      }

      setIsLoadingEntitlements(true);
      setEntitlementError(null);

      try {
        const data = await fetchMeEntitlements();

        if (!isMounted) return;
        setEntitlements(data);
        setEntitlementError(null);
      } catch (error) {
        if (!isMounted) return;
        setEntitlements(null);
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
  }, [auth.isAuthenticated, auth.isAuth0Mode, auth.isLoading]);

  useEffect(() => {
    if (!hasMessages) return;
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, hasMessages]);

  useEffect(() => {
    const state = location.state as StrategyChatLocationState;
    const prefillPrompt = state?.prefillPrompt?.trim();
    const sourceDraftConfig = isRecord(state?.sourceDraftConfig)
      ? state.sourceDraftConfig
      : null;

    if (!prefillPrompt && !sourceDraftConfig) return;

    const sourceConfigName =
      sourceDraftConfig && typeof sourceDraftConfig.name === 'string'
        ? sourceDraftConfig.name
        : '';
    const consumptionKey = `${prefillPrompt ?? ''}:${state?.source ?? ''}:${state?.sourceRunId ?? ''}:${sourceConfigName}`;
    if (consumedPrefillRef.current === consumptionKey) return;

    consumedPrefillRef.current = consumptionKey;

    if (sourceDraftConfig) {
      setSourceRunId(typeof state?.sourceRunId === 'string' ? state.sourceRunId : null);

      setMessages((prev) => {
        const existingConfig = getLatestDraftConfig(prev);

        if (existingConfig) {
          return prev;
        }

        return [
          buildSeededDraftMessage({
            config: sourceDraftConfig,
            sourceRunId: state?.sourceRunId,
            sourceLabel: state?.sourceLabel
          })
        ];
      });
    }

    if (prefillPrompt) {
      setInput(prefillPrompt);
      setComposerFocusKey((value) => value + 1);
    }

    navigate(location.pathname, {
      replace: true,
      state: null
    });
  }, [location.pathname, location.state, navigate]);

  useEffect(() => {
    const homeResetKey = (location.state as StrategyChatLocationState)?.homeResetKey;
    if (!homeResetKey) return;

    clearChatWorkspace();
    navigate('/workspace', {
      replace: true,
      state: null
    });
  }, [location.state, navigate]);

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
    const currentConfig = latestDraftConfig;
    const entitlementsBeforeSubmit = entitlements;

    setMessages(nextMessages);
    setInput('');
    if (entitlementsBeforeSubmit) {
      setEntitlements((current) =>
        current ? decrementBuilderPromptQuota(current) : current
      );
    }
    setIsGenerating(true);

    const requestId = ++builderRequestIdRef.current;
    let requestFailed = false;

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

      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: response.message,
        draft: response
      };

      if (requestId !== builderRequestIdRef.current) return;
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      if (requestId !== builderRequestIdRef.current) return;
      requestFailed = true;
      const structuredError = extractStructuredBuilderError(error);

      const assistantError: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: structuredError?.message ?? formatUnknownError(error),
        draft: structuredError ?? undefined
      };

      setMessages((prev) => [...prev, assistantError]);
    } finally {
      if (requestId !== builderRequestIdRef.current) return;

      setIsGenerating(false);

      try {
        const refreshedEntitlements = await fetchMeEntitlements();
        setEntitlements(refreshedEntitlements);
      } catch {
        if (requestFailed && entitlementsBeforeSubmit) {
          setEntitlements(entitlementsBeforeSubmit);
        }
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
      const sweepDraft = extractSweepDraft(msg.draft);

      if (sweepDraft) {
        const run = await createRun({
          run_type: 'PARAMETER_SWEEP',
          executor_type: 'SWEEP_EXECUTOR',
          request_payload: {
            base_config: sweepDraft.base_config,
            grid: sweepDraft.grid,
            ranking_metric: sweepDraft.ranking_metric,
            max_variants: sweepDraft.max_variants
          },
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
        return;
      }

      const config = extractDraftConfig(msg.draft);

      if (!config) {
        throw new Error('No strategy config returned from strategy builder.');
      }

      const run = await createRun({
        draft_config: config,
        parent_run_id: sourceRunId,
        run_type: 'SIMULATION',
        executor_type: 'SIMULATION_EXECUTOR',
        request_payload: sourceRunId
          ? {
              source: 'builder_variant',
              parent_run_id: sourceRunId
            }
          : {},
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

      console.error('Run failed:', error);

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

        navigate(`/runs/${duplicateRunId}`, {
          state: {
            notice: {
              tone: 'info',
              message: 'This run was already active, so we opened the existing run for you.'
            }
          }
        });
        return;
      }

      const message = formatLimitError(error);

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
    setComposerFocusKey((value) => value + 1);
  }

  function handleAssistantSuggestion(prompt: string) {
    setInput(prompt);
    setComposerFocusKey((value) => value + 1);

    requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    });
  }

  function clearChatWorkspace() {
    builderRequestIdRef.current += 1;
    setMessages([]);
    setInput('');
    setIsGenerating(false);
    setSourceRunId(null);
    setComposerFocusKey((value) => value + 1);
  }

  function handleStartNewDraft() {
    clearChatWorkspace();
    requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  function handleUseGalleryTemplate(template: StrategyGalleryTemplate) {
    navigate('/workspace', {
      state: {
        source: 'strategy_gallery',
        sourceLabel: 'Strategy Gallery',
        sourceDraftConfig: JSON.parse(JSON.stringify(template.config)) as Record<string, unknown>
      }
    });
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {!hasMessages ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-4xl flex-col items-center px-4 pt-12 pb-44 md:pt-16">
              <div className="space-y-3 text-center">
                <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.35em]">
                  US Market Strategy Platform
                </p>
                <h1 className="text-3xl font-semibold tracking-tight app-title md:text-5xl">
                  Research ETF strategies in plain English
                </h1>
                <p className="mx-auto max-w-2xl text-sm app-text-muted md:text-base">
                  Describe an idea, review the structured Strategy V2 draft, run a
                  backtest, then compare results and keep refining.
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
                <FeaturedStrategyIdeas onUseTemplate={handleUseGalleryTemplate} />
              </div>

              <div className="mt-6 w-full max-w-3xl">
                <div className="app-label mb-3 text-[11px] font-semibold uppercase tracking-[0.22em]">
                  Example starting points
                </div>
                <ExamplePromptChips onSelect={handlePromptChipClick} />
              </div>
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
                focusKey={composerFocusKey}
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
            <div className="mx-auto w-full max-w-4xl px-4 py-6 pb-48">
              {latestDraftConfig ? (
                <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 app-surface-soft">
                  <div className="min-w-0">
                    <div className="app-text-muted text-[11px] font-semibold uppercase tracking-[0.22em]">
                      Current editing context
                    </div>
                    <div className="app-title truncate text-sm font-semibold">
                      {latestDraftHeadline ?? 'Latest draft'}
                    </div>
                    <div className="app-text-muted mt-1 text-xs">
                      {sourceRunId
                        ? 'Imported from a previous result. New prompts will create variants from that result config.'
                        : 'New prompts will continue editing this draft until you start a new one.'}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {sourceRunId ? (
                      <Link
                        to={`/runs/${sourceRunId}`}
                        className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-medium transition"
                      >
                        Back to source result
                      </Link>
                    ) : null}

                    <button
                      type="button"
                      onClick={handleStartNewDraft}
                      className="app-button-secondary rounded-2xl px-4 py-2 text-sm font-medium transition"
                    >
                      Start New Draft
                    </button>
                  </div>
                </div>
              ) : null}

              <div className="mb-5">
                <EntitlementSummary
                  entitlements={entitlements}
                  loading={isLoadingEntitlements}
                  error={entitlementError}
                />
              </div>

              <ChatMessageList
                messages={messages}
                onRunDraft={handleRun}
                onUsePrompt={handleAssistantSuggestion}
              />

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
                focusKey={composerFocusKey}
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
