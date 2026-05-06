import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { PageHeader } from '../components/shared/PageHeader';
import { SectionCard } from '../components/shared/SectionCard';
import { StateCard } from '../components/shared/StateCard';
import {
  EMPTY_STRATEGY_GALLERY_FILTERS,
  STRATEGY_GALLERY_TEMPLATES,
  filterStrategyGalleryTemplates,
  findStrategyGalleryTemplate,
  getStrategyGalleryDisplayChips,
  getStrategyGalleryFilterOptions,
  hasActiveStrategyGalleryFilters,
  type StrategyGalleryFilters,
  type StrategyGalleryTemplate,
  type StrategyV2TemplateConfig
} from '../lib/strategyGalleryTemplates';
import { ApiRequestError, createRun, enqueueRun } from '../lib/api';
import { explainRule } from '../lib/ruleSummaries';
import { getStrategyBehaviorFields } from '../lib/strategyBehaviorSummary';

function cloneConfig(config: StrategyV2TemplateConfig): Record<string, unknown> {
  return JSON.parse(JSON.stringify(config)) as Record<string, unknown>;
}

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;

  try {
    return JSON.stringify(error, null, 2);
  } catch {
    return 'Request failed.';
  }
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

  return null;
}

export function StrategyGalleryPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTemplate = findStrategyGalleryTemplate(searchParams.get('template')) ?? STRATEGY_GALLERY_TEMPLATES[0];
  const [selectedTemplateId, setSelectedTemplateId] = useState(initialTemplate.id);
  const [runningTemplateId, setRunningTemplateId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [filters, setFilters] = useState<StrategyGalleryFilters>(EMPTY_STRATEGY_GALLERY_FILTERS);

  useEffect(() => {
    const template = findStrategyGalleryTemplate(searchParams.get('template'));
    if (template) {
      setSelectedTemplateId(template.id);
    }
  }, [searchParams]);

  const selectedTemplate = useMemo(
    () => findStrategyGalleryTemplate(selectedTemplateId) ?? STRATEGY_GALLERY_TEMPLATES[0],
    [selectedTemplateId]
  );
  const filterOptions = useMemo(() => getStrategyGalleryFilterOptions(STRATEGY_GALLERY_TEMPLATES), []);
  const filteredTemplates = useMemo(
    () => filterStrategyGalleryTemplates(STRATEGY_GALLERY_TEMPLATES, filters),
    [filters]
  );
  const hasActiveFilters = hasActiveStrategyGalleryFilters(filters);

  function updateFilter<Key extends keyof StrategyGalleryFilters>(key: Key, value: StrategyGalleryFilters[Key]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function handlePreview(template: StrategyGalleryTemplate) {
    setSelectedTemplateId(template.id);
    setSearchParams({ template: template.id });
    setRunError(null);
  }

  function handleUseInBuilder(template: StrategyGalleryTemplate) {
    navigate('/', {
      state: {
        source: 'strategy_gallery',
        sourceLabel: 'Strategy Gallery',
        sourceDraftConfig: cloneConfig(template.config)
      }
    });
  }

  async function handleRun(template: StrategyGalleryTemplate) {
    setRunningTemplateId(template.id);
    setRunError(null);

    try {
      const run = await createRun({
        draft_config: cloneConfig(template.config),
        run_type: 'SIMULATION',
        executor_type: 'SIMULATION_EXECUTOR',
        request_payload: {
          source: 'strategy_gallery',
          template_id: template.id,
          template_title: template.title
        },
        max_attempts: 1
      });

      await enqueueRun(run.id);
      navigate(`/runs/${run.id}`);
    } catch (error) {
      const duplicateRunId = extractDuplicateRunId(error);
      if (duplicateRunId) {
        navigate(`/runs/${duplicateRunId}`);
        return;
      }

      setRunError(formatUnknownError(error));
    } finally {
      setRunningTemplateId(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Strategy Gallery"
        title="Curated Strategy Ideas"
        description="Start from validated Strategy V2 templates, preview the rules, then run a draft simulation without saving a strategy first."
        actions={
          <>
            <Link to="/" className="app-button-secondary rounded-xl px-4 py-2 text-sm transition">
              Back to home
            </Link>
            <button
              type="button"
              onClick={() => handleRun(selectedTemplate)}
              disabled={runningTemplateId !== null}
              className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
            >
              {runningTemplateId === selectedTemplate.id ? 'Starting...' : 'Run selected'}
            </button>
          </>
        }
      />

      {runError ? <StateCard title="Could not start simulation" description={runError} tone="error" /> : null}

      <GalleryFilters
        filters={filters}
        options={filterOptions}
        resultCount={filteredTemplates.length}
        totalCount={STRATEGY_GALLERY_TEMPLATES.length}
        hasActiveFilters={hasActiveFilters}
        onChange={updateFilter}
        onReset={() => setFilters(EMPTY_STRATEGY_GALLERY_FILTERS)}
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        {/* Keep gallery rows content-sized; the sticky preview panel should not stretch card rhythm. */}
        <section className="grid self-start content-start items-start gap-4 md:grid-cols-2" aria-label="Strategy templates">
          {filteredTemplates.length > 0 ? (
            filteredTemplates.map((template) => (
              <StrategyTemplateCard
                key={template.id}
                template={template}
                selected={template.id === selectedTemplate.id}
                running={runningTemplateId === template.id}
                anyRunning={runningTemplateId !== null}
                onPreview={() => handlePreview(template)}
                onRun={() => {
                  void handleRun(template);
                }}
              />
            ))
          ) : (
            <StateCard
              title="No matching templates"
              description="Clear filters or broaden the search to see more Strategy V2 drafts."
            />
          )}
        </section>

        <TemplatePreview
          template={selectedTemplate}
          running={runningTemplateId === selectedTemplate.id}
          anyRunning={runningTemplateId !== null}
          onRun={() => {
            void handleRun(selectedTemplate);
          }}
          onUseInBuilder={() => handleUseInBuilder(selectedTemplate)}
        />
      </div>
    </div>
  );
}

function GalleryFilters({
  filters,
  options,
  resultCount,
  totalCount,
  hasActiveFilters,
  onChange,
  onReset
}: {
  filters: StrategyGalleryFilters;
  options: ReturnType<typeof getStrategyGalleryFilterOptions>;
  resultCount: number;
  totalCount: number;
  hasActiveFilters: boolean;
  onChange: <Key extends keyof StrategyGalleryFilters>(key: Key, value: StrategyGalleryFilters[Key]) => void;
  onReset: () => void;
}) {
  return (
    <section className="app-card rounded-2xl border p-3 app-shadow-soft" aria-label="Filter strategy templates">
      <div className="grid gap-3 lg:grid-cols-[minmax(220px,1.3fr)_repeat(5,minmax(120px,1fr))_auto]">
        <label className="min-w-0">
          <span className="sr-only">Search templates</span>
          <input
            type="search"
            value={filters.query}
            onChange={(event) => onChange('query', event.target.value)}
            placeholder="Search templates"
            className="app-input h-10 w-full rounded-xl border px-3 text-sm outline-none transition focus:border-cyan-500"
          />
        </label>

        <FilterSelect
          label="Style"
          value={filters.style}
          options={options.styles}
          onChange={(value) => onChange('style', value)}
        />
        <FilterSelect
          label="Risk"
          value={filters.riskLevel}
          options={options.riskLevels}
          onChange={(value) => onChange('riskLevel', value)}
        />
        <FilterSelect
          label="Symbol"
          value={filters.symbol}
          options={options.symbols}
          onChange={(value) => onChange('symbol', value)}
        />
        <FilterSelect
          label="Reference"
          value={filters.referenceSeriesUsage}
          options={options.referenceSeriesUsages}
          onChange={(value) => onChange('referenceSeriesUsage', value)}
        />
        <FilterSelect
          label="Tag/category"
          value={filters.tagOrCategory}
          options={options.tagsAndCategories}
          onChange={(value) => onChange('tagOrCategory', value)}
        />

        <button
          type="button"
          onClick={onReset}
          disabled={!hasActiveFilters}
          className="app-button-secondary h-10 whitespace-nowrap rounded-xl px-3 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50"
        >
          Clear
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs app-text-muted">
        <span className="font-medium app-title">
          {resultCount} of {totalCount} templates
        </span>
        {filters.query ? <ActiveFilterChip label={`Search: ${filters.query}`} /> : null}
        {filters.style ? <ActiveFilterChip label={filters.style} /> : null}
        {filters.riskLevel ? <ActiveFilterChip label={`${filters.riskLevel} risk`} /> : null}
        {filters.symbol ? <ActiveFilterChip label={filters.symbol} /> : null}
        {filters.referenceSeriesUsage ? <ActiveFilterChip label={filters.referenceSeriesUsage} /> : null}
        {filters.tagOrCategory ? <ActiveFilterChip label={filters.tagOrCategory} /> : null}
      </div>
    </section>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="min-w-0">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="app-input h-10 w-full rounded-xl border px-3 text-sm outline-none transition focus:border-cyan-500"
      >
        <option value="">{label}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function ActiveFilterChip({ label }: { label: string }) {
  return <span className="app-pill rounded-full border px-2 py-0.5 font-semibold">{label}</span>;
}

function StrategyTemplateCard({
  template,
  selected,
  running,
  anyRunning,
  onPreview,
  onRun
}: {
  template: StrategyGalleryTemplate;
  selected: boolean;
  running: boolean;
  anyRunning: boolean;
  onPreview: () => void;
  onRun: () => void;
}) {
  const displayChips = getStrategyGalleryDisplayChips(template);

  return (
    <article
      className={`app-card rounded-2xl border p-4 app-shadow-soft ${
        selected ? 'border-[color:var(--accent)]' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="app-label text-[11px] font-semibold uppercase tracking-[0.16em]">{template.style}</p>
          <p className="mt-1 text-xs font-medium app-text-muted">{template.categoryLabel}</p>
        </div>
        <span className={`w-28 shrink-0 whitespace-nowrap rounded-full border px-2.5 py-1 text-center text-xs font-semibold ${riskClassName(template.riskLevel)}`}>
          {template.riskLevel} risk
        </span>
      </div>

      <h3 className="mt-1.5 text-base font-semibold leading-6 app-title">{template.title}</h3>

      <p className="mt-2 text-sm leading-5 app-text-muted">{template.shortExplanation}</p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {displayChips.map((chip, index) => (
          <span
            key={chip}
            className={`app-pill rounded-full border px-2.5 py-1 text-xs ${index < template.symbols.length ? 'font-semibold' : ''}`}
          >
            {chip}
          </span>
        ))}
      </div>

      <p className="mt-3 text-xs leading-5 app-text-muted">{template.expectedBehavior}</p>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onPreview}
          className="app-button-secondary whitespace-nowrap rounded-xl px-4 py-2 text-sm font-medium transition"
        >
          Preview
        </button>
        <button
          type="button"
          onClick={onRun}
          disabled={anyRunning}
          className="app-button-primary whitespace-nowrap rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? 'Starting...' : 'Run simulation'}
        </button>
      </div>
    </article>
  );
}

function TemplatePreview({
  template,
  running,
  anyRunning,
  onRun,
  onUseInBuilder
}: {
  template: StrategyGalleryTemplate;
  running: boolean;
  anyRunning: boolean;
  onRun: () => void;
  onUseInBuilder: () => void;
}) {
  const config = template.config;
  const entrySummary = explainRule(config.entry_rule, { tradableSymbol: config.tradable_symbol });
  const exitSummary = explainRule(config.exit_rule, { tradableSymbol: config.tradable_symbol });
  const behaviorFields = getStrategyBehaviorFields(config as unknown as Record<string, unknown>);

  return (
    <aside className="xl:sticky xl:top-28 xl:self-start">
      <SectionCard
        title="Template Preview"
        subtitle="Structured draft summary before running a simulation."
        actions={
          <button
            type="button"
            onClick={onUseInBuilder}
            className="app-button-secondary rounded-xl px-3 py-2 text-sm font-medium transition"
          >
            Use in builder
          </button>
        }
      >
        <div className="space-y-5">
          <div>
            <p className="app-label text-[11px] font-semibold uppercase tracking-[0.18em]">Selected idea</p>
            <h3 className="mt-2 text-xl font-semibold app-title">{template.title}</h3>
            <p className="mt-2 text-sm leading-6 app-text-muted">{template.expectedBehavior}</p>
          </div>

          <dl className="grid gap-3 text-sm">
            <PreviewRow label="Tradable" value={config.tradable_symbol} />
            <PreviewRow label="Date range" value={`${config.start_date} to ${config.end_date}`} />
            <PreviewRow label="Reference symbols" value={config.reference_symbols.join(', ') || 'None'} />
            {behaviorFields.map((field) => (
              <PreviewRow key={`${field.label}-${field.value}`} label={field.label} value={field.value} />
            ))}
          </dl>

          <div className="grid gap-3">
            <RuleBlock label="Entry rules" text={template.entryRuleText} summary={entrySummary} />
            <RuleBlock label="Exit rules" text={template.exitRuleText} summary={exitSummary} />
          </div>

          <div>
            <p className="app-label text-[11px] font-semibold uppercase tracking-[0.18em]">Risk controls</p>
            <ul className="mt-2 space-y-2 text-sm app-text-muted">
              {template.riskControls.map((control) => (
                <li key={control}>- {control}</li>
              ))}
            </ul>
          </div>

          <div>
            <p className="app-label mb-2 text-[11px] font-semibold uppercase tracking-[0.18em]">
              Strategy V2 config
            </p>
            <pre className="app-form-code max-h-[360px] overflow-auto rounded-2xl p-4 font-mono text-xs leading-6">
              {JSON.stringify(config, null, 2)}
            </pre>
          </div>

          <button
            type="button"
            onClick={onRun}
            disabled={anyRunning}
            className="app-button-primary w-full rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? 'Starting simulation...' : 'Run simulation'}
          </button>
        </div>
      </SectionCard>
    </aside>
  );
}

function PreviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="app-value-block rounded-2xl px-4 py-3">
      <dt className="text-xs font-semibold uppercase tracking-[0.16em] app-text-soft">{label}</dt>
      <dd className="mt-1 app-title">{value}</dd>
    </div>
  );
}

function RuleBlock({ label, text, summary }: { label: string; text: string; summary: string }) {
  return (
    <div className="app-home-draft-panel rounded-2xl p-4">
      <p className="app-label text-[11px] font-semibold uppercase tracking-[0.18em]">{label}</p>
      <p className="mt-2 text-sm font-medium app-title">{text}</p>
      <p className="mt-1 text-xs leading-5 app-text-muted">Config summary: {summary}</p>
    </div>
  );
}

function riskClassName(riskLevel: StrategyGalleryTemplate['riskLevel']): string {
  if (riskLevel === 'Lower') return 'app-chip-success';
  if (riskLevel === 'Higher') return 'app-chip-warning';
  return 'app-chip-info';
}
