import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { STRATEGY_GALLERY_TEMPLATES } from '../lib/strategyGalleryTemplates';

const HOW_IT_WORKS_STEPS = ['Idea', 'Draft', 'Run', 'Inspect', 'Compare'];

type LandingSectionId = 'research' | 'product' | 'templates' | 'safety';

const NAV_ITEMS: Array<{ id: LandingSectionId; label: string }> = [
  { id: 'research', label: 'Research' },
  { id: 'product', label: 'Product' },
  { id: 'templates', label: 'Templates' },
  { id: 'safety', label: 'Safety' }
];

const DIFFERENTIATORS = [
  {
    title: 'Natural-language drafting',
    description: 'Describe ETF strategy rules in plain English, then review the generated structure before running it.'
  },
  {
    title: 'Deterministic Strategy V2 configs',
    description: 'Strategy V2 configs make each idea explicit, reusable, and easier to compare across versions.'
  },
  {
    title: 'Historical ETF simulations',
    description: 'Run backtests on ETF ideas to understand how rules behaved over the selected historical window.'
  },
  {
    title: 'Trade-level signal values',
    description: 'Inspect the values that led into entries, exits, and position changes.'
  },
  {
    title: 'Capital usage inspection',
    description: 'See how much capital the strategy put to work across the simulation.'
  },
  {
    title: 'Parameter sweeps and comparison',
    description: 'Compare variants to understand how assumptions change outcomes.'
  }
];

const RESEARCH_FRAMING = [
  'Historical backtests only',
  'Not financial advice',
  'No guaranteed performance',
  'Not a broker or live trading platform'
];

export function LandingPage() {
  const featuredTemplates = STRATEGY_GALLERY_TEMPLATES.slice(0, 3);
  const sectionIds = useMemo(() => NAV_ITEMS.map((item) => item.id), []);
  const [activeSection, setActiveSection] = useState<LandingSectionId | null>(null);
  const [showStickyNav, setShowStickyNav] = useState(false);

  useEffect(() => {
    const sections = sectionIds
      .map((id) => document.getElementById(id))
      .filter((section): section is HTMLElement => Boolean(section));

    if (sections.length === 0) return;

    function updateActiveSection() {
      const firstSection = sections[0];
      const firstSectionTop = firstSection.getBoundingClientRect().top;
      const marker = window.innerHeight * 0.38;
      const isNearPageBottom =
        window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;

      if (firstSectionTop > marker) {
        setActiveSection(null);
        return;
      }

      if (isNearPageBottom) {
        setActiveSection(sectionIds[sectionIds.length - 1]);
        return;
      }

      const currentSection = sections.find((section) => {
        const rect = section.getBoundingClientRect();
        return rect.top <= marker && rect.bottom >= marker;
      });

      if (currentSection?.id && sectionIds.includes(currentSection.id as LandingSectionId)) {
        setActiveSection(currentSection.id as LandingSectionId);
        return;
      }

      const nearestSection = sections
        .map((section) => ({
          id: section.id,
          distance: Math.abs(section.getBoundingClientRect().top - marker)
        }))
        .sort((a, b) => a.distance - b.distance)[0];

      if (nearestSection?.id && sectionIds.includes(nearestSection.id as LandingSectionId)) {
        setActiveSection(nearestSection.id as LandingSectionId);
      }
    }

    const observer = new IntersectionObserver(
      () => {
        updateActiveSection();
      },
      {
        rootMargin: '-28% 0px -58% 0px',
        threshold: [0, 0.18, 0.36, 0.6]
      }
    );

    sections.forEach((section) => observer.observe(section));
    updateActiveSection();
    window.addEventListener('scroll', updateActiveSection, { passive: true });
    window.addEventListener('resize', updateActiveSection);

    return () => {
      observer.disconnect();
      window.removeEventListener('scroll', updateActiveSection);
      window.removeEventListener('resize', updateActiveSection);
    };
  }, [sectionIds]);

  useEffect(() => {
    const hero = document.getElementById('landing-hero');
    if (!hero) return;
    const heroElement = hero;

    function updateStickyNav() {
      setShowStickyNav(heroElement.getBoundingClientRect().bottom <= 96);
    }

    updateStickyNav();
    window.addEventListener('scroll', updateStickyNav, { passive: true });
    window.addEventListener('resize', updateStickyNav);

    return () => {
      window.removeEventListener('scroll', updateStickyNav);
      window.removeEventListener('resize', updateStickyNav);
    };
  }, []);

  return (
    <div className="min-h-screen bg-[color:var(--bg-start)] text-[color:var(--text)]">
      <header className="relative z-10">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4 lg:px-8">
          <Link to="/" className="text-sm font-semibold app-title">
            US Market Research
          </Link>

          <nav className="hidden items-center gap-7 text-sm app-text-muted md:flex" aria-label="Landing navigation">
            <LandingNavLinks activeSection={activeSection} />
          </nav>

          <div className="flex items-center gap-2">
            <Link
              to="/gallery"
              className="hidden rounded-full px-4 py-2 text-sm font-medium app-text-muted transition hover:text-[color:var(--title)] sm:inline-flex"
            >
              Browse templates
            </Link>
            <Link
              to="/workspace"
              className="app-button-primary rounded-full px-4 py-2 text-sm font-semibold transition"
            >
              Open workspace
            </Link>
          </div>
        </div>
      </header>

      <div
        className={`fixed left-0 right-0 top-0 z-40 border-b border-[color:color-mix(in_srgb,var(--border-soft)_78%,transparent)] bg-[color:color-mix(in_srgb,var(--bg-start)_90%,transparent)] shadow-[0_1px_18px_rgba(15,23,42,0.05)] backdrop-blur-xl transition duration-300 ${
          showStickyNav ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-full opacity-0'
        }`}
        aria-hidden={!showStickyNav}
      >
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3 lg:px-8">
          <Link to="/" className="text-sm font-semibold app-title">
            US Market Research
          </Link>
          <nav className="hidden items-center gap-7 text-sm app-text-muted md:flex" aria-label="Sticky landing navigation">
            <LandingNavLinks activeSection={activeSection} />
          </nav>
          <Link
            to="/workspace"
            className="app-button-primary rounded-full px-4 py-2 text-sm font-semibold transition"
          >
            Open workspace
          </Link>
        </div>
      </div>

      <main>
        <section id="landing-hero" className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-5xl flex-col items-center justify-center px-6 pb-20 pt-12 text-center lg:px-8">
          <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.3em]">
            ETF strategy research workspace
          </p>
          <h1 className="mt-5 max-w-4xl text-5xl font-semibold leading-[1.04] tracking-tight app-title md:text-7xl">
            Turn ETF ideas into testable research.
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 app-text-muted md:text-xl">
            Describe a strategy, run a historical simulation, inspect trades, and compare results.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link
              to="/workspace"
              className="app-button-primary rounded-full px-5 py-3 text-sm font-semibold transition"
            >
              Start researching
            </Link>
            <Link
              to="/gallery"
              className="app-button-secondary rounded-full px-5 py-3 text-sm font-semibold transition"
            >
              Browse templates
            </Link>
          </div>
        </section>

        <section id="research" className="scroll-mt-24 px-6 py-28 lg:px-8">
          <div className="mx-auto max-w-6xl">
            <div className="grid gap-12 border-y app-border-soft py-16 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
              <div>
                <p className="app-label text-xs font-semibold uppercase tracking-[0.24em]">
                  Research
                </p>
                <p className="mt-5 max-w-xl text-4xl font-semibold leading-tight tracking-tight app-title md:text-5xl">
                  Test the idea before trusting the story.
                </p>
              </div>
              <div className="space-y-6 text-lg leading-8 app-text-muted">
                <p>
                  Investors often have clear strategy ideas, but testing them can become a scattered mix of notes,
                  spreadsheets, screenshots, and scripts.
                </p>
                <p>
                  US Market Research turns plain-English ETF ideas into deterministic Strategy V2 configs, so each
                  assumption is visible before a simulation runs.
                </p>
                <p className="border-l app-border-soft pl-5 text-xl leading-8 app-title">
                  Backtests return the artifacts a researcher needs to reason about an idea: charts, metrics, trades,
                  signal values, and capital usage.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section id="product" className="scroll-mt-24 px-6 py-28 lg:px-8">
          <div className="mx-auto max-w-6xl">
            <div className="overflow-hidden rounded-[2rem] border app-border-soft bg-[color:color-mix(in_srgb,var(--surface-soft)_42%,transparent)]">
              <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                <div className="px-6 pt-10 md:px-10 md:pt-12">
                  <p className="app-label text-xs font-semibold uppercase tracking-[0.24em]">How it works</p>
                  <h2 className="mt-4 text-3xl font-semibold tracking-tight app-title md:text-4xl">
                    One loop from idea to comparison.
                  </h2>
                </div>
                <p className="max-w-md px-6 text-sm leading-6 app-text-muted md:px-10 md:pt-12">
                  Each step leaves behind a clearer artifact: a config, a run, a trade record, or a comparison.
                </p>
              </div>

              <div className="mt-12 grid border-t app-border-soft md:grid-cols-5">
                {HOW_IT_WORKS_STEPS.map((step, index) => (
                  <div key={step} className="relative min-h-40 border-t app-border-soft p-6 md:border-l md:border-t-0 md:p-7">
                    <div className="text-xs font-semibold uppercase tracking-[0.18em] app-text-soft">0{index + 1}</div>
                    <div className="mt-5 text-2xl font-semibold app-title">{step}</div>
                    <p className="mt-3 text-sm leading-6 app-text-muted">{getStepDescription(step)}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-28 grid gap-12 lg:grid-cols-[0.78fr_1.22fr]">
              <div className="lg:sticky lg:top-28 lg:self-start">
                <p className="app-label text-xs font-semibold uppercase tracking-[0.24em]">
                  What makes it different
                </p>
                <h2 className="mt-4 text-3xl font-semibold tracking-tight app-title md:text-4xl">
                  A research loop, not a prediction machine.
                </h2>
              </div>
              <div className="grid gap-4">
                {DIFFERENTIATORS.map((item) => (
                  <article
                    key={item.title}
                    className="grid gap-3 rounded-3xl border app-border-soft bg-[color:color-mix(in_srgb,var(--surface-soft)_26%,transparent)] p-5 md:grid-cols-[0.7fr_1fr] md:p-6"
                  >
                    <h3 className="text-lg font-semibold app-title">{item.title}</h3>
                    <p className="text-sm leading-6 app-text-muted">{item.description}</p>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="templates" className="scroll-mt-24 px-6 py-28 lg:px-8">
          <div className="mx-auto max-w-6xl">
            <div className="flex flex-col gap-5 border-t app-border-soft pt-12 md:flex-row md:items-end md:justify-between">
              <div className="max-w-2xl">
                <p className="app-label text-xs font-semibold uppercase tracking-[0.24em]">
                  Start from templates
                </p>
                <h2 className="mt-4 text-3xl font-semibold tracking-tight app-title md:text-4xl">
                  Use a known pattern as your first draft.
                </h2>
                <p className="mt-4 text-base leading-7 app-text-muted">
                  The Gallery is the discovery surface for curated ETF strategy templates. Open one, inspect the
                  assumptions, then continue in the workspace.
                </p>
              </div>
              <Link to="/gallery" className="app-button-primary inline-flex rounded-full px-5 py-3 text-sm font-semibold transition">
                Open Gallery
              </Link>
            </div>

            <div className="mt-12 grid gap-6 md:grid-cols-3">
              {featuredTemplates.map((template) => (
                <article
                  key={template.id}
                  className="group flex min-h-72 flex-col rounded-[1.75rem] border app-border-soft bg-[color:color-mix(in_srgb,var(--surface-soft)_32%,transparent)] p-6 transition duration-200 hover:-translate-y-0.5 hover:border-[color:color-mix(in_srgb,var(--accent)_30%,var(--border-soft))] hover:bg-[color:color-mix(in_srgb,var(--surface-soft)_48%,transparent)]"
                >
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] app-text-soft">{template.style}</p>
                  <h3 className="mt-4 text-lg font-semibold leading-6 app-title">{template.title}</h3>
                  <p className="mt-4 flex-1 text-sm leading-6 app-text-muted">{template.expectedBehavior}</p>
                  <Link
                    to={`/gallery?template=${template.id}`}
                    className="mt-6 inline-flex items-center text-sm font-semibold app-accent transition group-hover:translate-x-1"
                  >
                    Preview template -&gt;
                  </Link>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="safety" className="scroll-mt-24 px-6 py-28 lg:px-8">
          <div className="mx-auto max-w-6xl rounded-[2rem] border app-border-soft bg-[color:color-mix(in_srgb,var(--surface-soft)_30%,transparent)] px-6 py-10 md:px-10 md:py-12">
            <div className="grid gap-10 md:grid-cols-[0.75fr_1.25fr] md:items-start">
              <div>
                <p className="app-label text-xs font-semibold uppercase tracking-[0.24em]">
                  Research framing
                </p>
                <h2 className="mt-4 text-3xl font-semibold tracking-tight app-title">
                  Built for analysis, not execution.
                </h2>
                <p className="mt-4 text-sm leading-6 app-text-muted">
                  The platform helps structure research questions and historical simulations. It does not execute
                  trades or promise future results.
                </p>
              </div>
              <div className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
                {RESEARCH_FRAMING.map((item) => (
                  <p key={item} className="border-t app-border-soft pt-4 text-base font-semibold app-title">
                    {item}
                  </p>
                ))}
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="px-6 pb-10 pt-4 lg:px-8">
        <div className="mx-auto grid max-w-6xl gap-8 border-t app-border-soft pt-8 md:grid-cols-[1fr_auto]">
          <div>
            <p className="text-sm font-semibold app-title">US Market Research</p>
            <p className="mt-2 max-w-xl text-sm leading-6 app-text-muted">
              ETF strategy research workspace for historical simulation and comparison.
            </p>
          </div>

          <div className="grid gap-6 sm:grid-cols-2 md:text-right">
            <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm app-text-muted md:justify-end" aria-label="Landing footer">
              <Link to="/workspace" className="transition hover:text-[color:var(--title)]">Workspace</Link>
              <Link to="/gallery" className="transition hover:text-[color:var(--title)]">Gallery</Link>
              <Link to="/runs" className="transition hover:text-[color:var(--title)]">Results</Link>
              <Link to="/compare" className="transition hover:text-[color:var(--title)]">Compare</Link>
            </nav>
            <div className="space-y-1 text-sm app-text-soft">
              <p>Historical backtests only</p>
              <p>Not financial advice</p>
              <p>No guaranteed performance</p>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

function LandingNavLinks({ activeSection }: { activeSection: LandingSectionId | null }) {
  return (
    <>
      {NAV_ITEMS.map((item) => (
        <a
          key={item.id}
          href={`#${item.id}`}
          aria-current={activeSection === item.id ? 'page' : undefined}
          className={`border-b py-1 transition ${
            activeSection === item.id
              ? 'border-[color:var(--accent)] text-[color:var(--title)]'
              : 'border-transparent hover:text-[color:var(--title)]'
          }`}
        >
          {item.label}
        </a>
      ))}
    </>
  );
}

function getStepDescription(step: string): string {
  switch (step) {
    case 'Idea':
      return 'Start with a plain-English ETF strategy hypothesis.';
    case 'Draft':
      return 'Review the generated Strategy V2 configuration.';
    case 'Run':
      return 'Simulate the rules across historical data.';
    case 'Inspect':
      return 'Read the metrics, trades, signals, and capital usage.';
    case 'Compare':
      return 'Place variants side by side and decide what to test next.';
    default:
      return '';
  }
}
