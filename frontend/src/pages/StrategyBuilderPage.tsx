import { useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { generateStrategyDraft } from '../lib/api';
import type { StrategyBuilderGenerateResponse } from '../types/api';

type SaveAsNewStrategyState = {
  builderDraft: {
    name: string;
    description: string;
    strategyType: string;
    configText: string;
  };
};

type SaveAsNewVersionState = {
  builderDraft: {
    configText: string;
    changeNote: string;
  };
};

type StrategyBuilderLocationState = {
  builderContext?: {
    strategyId?: string | null;
    baseVersionId?: string | null;
    currentConfig?: Record<string, unknown> | null;
  };
};

function normalizeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}

function prettifyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return '{}';
  }
}

function parseJsonObject(value: string): Record<string, unknown> {
  return JSON.parse(value) as Record<string, unknown>;
}

function Field({
  label,
  children
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-2">
      <span className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">
        {label}
      </span>
      {children}
    </label>
  );
}

function ListBlock({
  title,
  items,
  tone = 'default'
}: {
  title: string;
  items: string[];
  tone?: 'default' | 'warning';
}) {
  const borderClassName =
    tone === 'warning'
      ? 'border-amber-900/60 bg-amber-950/30'
      : 'border-slate-800 bg-slate-950/60';

  const bulletClassName = tone === 'warning' ? 'text-amber-300' : 'text-cyan-300';

  return (
    <section className={`rounded-2xl border px-4 py-4 ${borderClassName}`}>
      <h3 className="text-sm font-semibold text-white">{title}</h3>

      {items.length === 0 ? (
        <p className="mt-2 text-sm text-slate-400">None.</p>
      ) : (
        <ul className="mt-3 space-y-2 text-sm text-slate-200">
          {items.map((item, index) => (
            <li key={`${title}-${index}`} className="flex gap-2">
              <span className={bulletClassName}>•</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function StrategyBuilderPage() {
  const navigate = useNavigate();

  const location = useLocation();

  const builderContext = (location.state as StrategyBuilderLocationState | null)?.builderContext ?? null;

  const [prompt, setPrompt] = useState('');
  const [existingStrategyId, setExistingStrategyId] = useState( builderContext?.strategyId ?? '');
  const [draftResponse, setDraftResponse] = useState<StrategyBuilderGenerateResponse | null>(null);
  const [configText, setConfigText] = useState( builderContext?.currentConfig ? prettifyJson(builderContext.currentConfig) : '{}' );

  const [loadError, setLoadError] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const inputClassName =
    'w-full rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-cyan-500';
  const textareaClassName =
    'w-full rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-cyan-500';
  const jsonTextareaClassName =
    'min-h-[520px] w-full rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 font-mono text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-cyan-500';

  async function handleGenerate(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoadError(null);
    setJsonError(null);

    if (!prompt.trim()) {
      setLoadError('Prompt is required.');
      return;
    }

    setGenerating(true);

    try {
      const response = await generateStrategyDraft({
        prompt: prompt.trim(),
        context: existingStrategyId.trim()
          ? {
              strategy_id: existingStrategyId.trim(),
              base_version_id: builderContext?.baseVersionId ?? null,
              mode: 'NEW_VERSION',
              current_config: (() => {
                try {
                  return JSON.parse(configText);
                } catch {
                  return builderContext?.currentConfig ?? null;
                }
              })()
            }
          : {
              mode: 'NEW_STRATEGY'
            }
      });

      setDraftResponse(response);
      setConfigText(prettifyJson(response.config));
    } catch (error) {
      setLoadError(normalizeError(error));
      setDraftResponse(null);
      setConfigText('{}');
    } finally {
      setGenerating(false);
    }
  }

  function validateEditedJson(): Record<string, unknown> | null {
    setJsonError(null);

    try {
      return parseJsonObject(configText);
    } catch {
      setJsonError('Edited config must be valid JSON before handoff.');
      return null;
    }
  }

  function handleSaveAsNewStrategy() {
    const parsedConfig = validateEditedJson();
    if (!parsedConfig) return;

    const state: SaveAsNewStrategyState = {
      builderDraft: {
        name:
          typeof parsedConfig.name === 'string' && parsedConfig.name.trim()
            ? parsedConfig.name.trim()
            : 'generated-strategy',
        description: draftResponse?.summary ?? 'Generated from Strategy Builder.',
        strategyType: 'SIMULATION',
        configText: prettifyJson(parsedConfig)
      }
    };

    navigate('/strategies/new', { state });
  }

  function handleSaveAsNewVersion() {
    const parsedConfig = validateEditedJson();
    if (!parsedConfig) return;

    const strategyId = existingStrategyId.trim();
    if (!strategyId) {
      setJsonError('Existing Strategy ID is required to hand off as a new version.');
      return;
    }

    const state: SaveAsNewVersionState = {
      builderDraft: {
        configText: prettifyJson(parsedConfig),
        changeNote:
          draftResponse?.changes?.length
            ? draftResponse.changes.join(' ')
            : 'Generated from Strategy Builder'
      }
    };

    navigate(`/strategies/${strategyId}/versions/new`, { state });
  }

  const configStats = useMemo(() => {
    try {
      const parsed = parseJsonObject(configText);
      return {
        strategyName: typeof parsed.name === 'string' ? parsed.name : '—',
        tradableSymbol:
          typeof parsed.tradable_symbol === 'string' ? parsed.tradable_symbol : '—',
        benchmarkSymbol:
          typeof parsed.benchmark_symbol === 'string' ? parsed.benchmark_symbol : '—'
      };
    } catch {
      return {
        strategyName: 'Invalid JSON',
        tradableSymbol: '—',
        benchmarkSymbol: '—'
      };
    }
  }, [configText]);

  const isVersionAwareMode = Boolean(builderContext?.currentConfig);

  return (
    <div className="mx-auto max-w-7xl px-6 py-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.28em] text-cyan-400">
            LLM-Assisted Strategy Builder
          </div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">
            Strategy Builder
          </h1>
          <p className="mt-3 max-w-3xl text-sm text-slate-400">
            Describe a strategy in natural language, review the generated canonical JSON draft, and
            hand it off into the existing save flow.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link
            to="/runs"
            className="rounded-2xl border border-slate-800 px-4 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-700 hover:bg-slate-900"
          >
            Back to Runs
          </Link>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.9fr)]">
        <form
          onSubmit={handleGenerate}
          className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-black/20"
        >
          <div className="mb-6">
            <h2 className="text-xl font-semibold text-white">Prompt Drafting</h2>
            <p className="mt-2 text-sm text-slate-400">
              {isVersionAwareMode
                ? 'Version-aware mode: apply a natural-language edit to the current strategy config before saving a new version.'
                : 'MVP flow: generate a draft only. Saving still goes through the existing strategy and version endpoints.'}
            </p>
          </div>

          <div className="grid gap-5">
            <Field label="Natural Language Prompt">
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Example: Create a mean reversion strategy for QQQ using RSI with a 10% stop loss."
                className={`${textareaClassName} min-h-[180px]`}
              />
            </Field>

            <Field label="Existing Strategy ID for New Version (Optional)">
              <input
                type="text"
                value={existingStrategyId}
                onChange={(event) => setExistingStrategyId(event.target.value)}
                placeholder="Only needed when handing off as a new version"
                className={inputClassName}
              />
            </Field>

            {builderContext?.currentConfig && (
              <div className="rounded-2xl border border-cyan-900/60 bg-cyan-950/30 px-4 py-3 text-sm text-cyan-100">
                Using current strategy version as the base config. Your prompt will modify this draft instead of creating one from scratch.
              </div>
            )}
          </div>

          {loadError && (
            <div className="mt-6 rounded-2xl border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
              {loadError}
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={generating}
              className="rounded-2xl bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {generating
                ? isVersionAwareMode
                  ? 'Applying Prompt...'
                  : 'Generating Draft...'
                : isVersionAwareMode
                  ? 'Apply Prompt'
                  : 'Generate Draft'}
            </button>

            <button
              type="button"
              onClick={() => {
                setPrompt('');
                setExistingStrategyId('');
                setDraftResponse(null);
                setConfigText(
                  builderContext?.currentConfig
                    ? prettifyJson(builderContext.currentConfig)
                    : '{}'
                );
                setLoadError(null);
                setJsonError(null);
              }}
              className="rounded-2xl border border-slate-800 px-4 py-3 text-sm font-medium text-slate-200 transition hover:border-slate-700 hover:bg-slate-900"
            >
              Clear
            </button>
          </div>
        </form>

        <div className="space-y-6">
          <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-black/20">
            <h2 className="text-xl font-semibold text-white">Draft Preview</h2>
            <p className="mt-2 text-sm text-slate-400">
              Human-readable interpretation returned by the generation endpoint.
            </p>

            <div className="mt-5 space-y-3">
              <PreviewRow label="Strategy Name" value={configStats.strategyName} />
              <PreviewRow label="Tradable Symbol" value={configStats.tradableSymbol} />
              <PreviewRow label="Benchmark Symbol" value={configStats.benchmarkSymbol} />
            </div>

            <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                Summary
              </div>
              <div className="mt-2 whitespace-pre-wrap text-sm text-slate-100">
                {draftResponse?.summary ?? 'No draft generated yet.'}
              </div>
            </div>

            <div className="mt-5 space-y-4">
              <ListBlock title="Changes" items={draftResponse?.changes ?? []} />
              <ListBlock
                title="Warnings"
                items={draftResponse?.warnings ?? []}
                tone="warning"
              />
              <ListBlock title="Changes" items={draftResponse?.changes ?? []} />
            </div>
          </section>
        </div>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.9fr)]">
        <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-black/20">
          <div className="mb-6">
            <h2 className="text-xl font-semibold text-white">Editable Canonical JSON</h2>
            <p className="mt-2 text-sm text-slate-400">
              Review and refine the generated Strategy V2 config before handing it off.
            </p>
          </div>

          <textarea
            value={configText}
            onChange={(event) => setConfigText(event.target.value)}
            className={jsonTextareaClassName}
            spellCheck={false}
          />

          {jsonError && (
            <div className="mt-6 rounded-2xl border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
              {jsonError}
            </div>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleSaveAsNewStrategy}
              disabled={!draftResponse}
              className="rounded-2xl bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Save as New Strategy
            </button>

            <button
              type="button"
              onClick={handleSaveAsNewVersion}
              disabled={!draftResponse}
              className="rounded-2xl border border-slate-700 px-5 py-3 text-sm font-semibold text-slate-100 transition hover:border-cyan-500/50 hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Save as New Version
            </button>

            <button
              type="button"
              onClick={() => {
                if (draftResponse) {
                  setConfigText(prettifyJson(draftResponse.config));
                  setJsonError(null);
                }
              }}
              disabled={!draftResponse}
              className="rounded-2xl border border-slate-800 px-4 py-3 text-sm font-medium text-slate-200 transition hover:border-slate-700 hover:bg-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Reset to Generated Draft
            </button>
          </div>
        </section>

        <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 shadow-2xl shadow-black/20">
          <h2 className="text-xl font-semibold text-white">Handoff Notes</h2>
          <p className="mt-2 text-sm text-slate-400">
            Save actions reuse your existing create pages instead of calling persistence APIs
            directly from the builder.
          </p>

          <div className="mt-5 space-y-3">
            <PreviewRow label="New Strategy Handoff" value="/strategies/new" />
            <PreviewRow
              label="New Version Handoff"
              value={
                existingStrategyId.trim()
                  ? `/strategies/${existingStrategyId.trim()}/versions/new`
                  : 'Provide Existing Strategy ID first'
              }
            />
            <PreviewRow
              label="Current Mode"
              value={existingStrategyId.trim() ? 'Can hand off both new strategy and new version' : 'Can hand off new strategy immediately'}
            />
          </div>
        </section>
      </div>
    </div>
  );
}

function PreviewRow({
  label,
  value
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-4">
      <div className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
        {label}
      </div>
      <div className="mt-2 break-words text-sm text-slate-100">{value || '—'}</div>
    </div>
  );
}