from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_run_detail_header_does_not_expose_new_version_action():
    source = (ROOT / "frontend/src/components/run-detail/RunHeader.tsx").read_text()

    assert "New version" not in source
    assert "Back to results" in source
    assert "Result ID:" in source
    assert "Simulation Result" in source
    assert "Parameter Sweep Result" in source
    assert "Open strategy" in source


def test_run_detail_polls_active_runs_more_responsively():
    source = (ROOT / "frontend/src/pages/RunDetailPage.tsx").read_text()
    api_source = (ROOT / "frontend/src/lib/api.ts").read_text()

    assert "const ACTIVE_RUN_INITIAL_POLL_INTERVAL_MS = 750" in source
    assert "const UNSUCCESSFUL_RUN_STATUSES = new Set(['FAILED', 'CANCELED', 'CANCELLED']);" in source
    assert "const ACTIVE_RUN_STEADY_POLL_INTERVAL_MS = 1500" in source
    assert "const ACTIVE_RUN_LONG_POLL_INTERVAL_MS = 3000" in source
    assert "const HIDDEN_TAB_POLL_INTERVAL_MS = 5000" in source
    assert "const FINALIZING_DASHBOARD_POLL_INTERVAL_MS = 2000" in source
    assert "document.hidden" in source
    assert "elapsedMs < 10_000" in source
    assert "elapsedMs < 60_000" in source
    assert "}, activeProgressPollIntervalMs());" in source
    assert "}, FINALIZING_DASHBOARD_POLL_INTERVAL_MS);" in source
    assert "fetchRunProgress" in source
    assert "progressResponse.progress_pct" in source
    assert "progressResponse.progress_message" in source
    assert "progressResponse.is_terminal" in source
    assert "run.progress_message" in source
    assert "`${run.progress_message} (${run.progress_pct}%)`" in source
    assert "`/api/runs/${runId}/progress`" in api_source


def test_navigation_shortens_results_label_while_results_page_uses_research_results_language():
    nav_source = (ROOT / "frontend/src/components/layout/AppShell.tsx").read_text()
    page_source = (ROOT / "frontend/src/pages/RunsPage.tsx").read_text()
    table_source = (ROOT / "frontend/src/components/runs/RunsTable.tsx").read_text()

    assert "label: 'Results'" in nav_source
    assert 'title="Research Results"' in page_source
    assert 'eyebrow="Results"' in page_source
    assert 'label="Visible results"' in page_source
    assert 'label="Completed results"' in page_source
    assert "No results match these filters." in table_source
    assert "Loading results…" in table_source
    assert "Open result" in table_source
    assert "Open run" not in table_source


def test_strategy_detail_still_exposes_new_version_and_run_this_version():
    source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()

    assert "New Version" in source
    assert "Run this version" in source
    assert "reference_strategy_version_id: selectedVersion.id" in source
    assert "to={`/runs/${referenceRunId}`}" in source
    assert "to={`/compare?runIds=${referenceRunId}`}" in source
    assert "Version selector" in source
    assert "selectedVersion?.reference_performance" in source
    assert "handleRunSelectedVersion" in source
    assert "selectedVersionRuns" in source
    assert "?fromVersionId=${selectedVersion.id}" in source


def test_strategy_detail_preserves_and_restores_selected_version_from_url():
    source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()

    assert "searchParams.get('versionId')" in source
    assert "searchParams.get('version')" in source
    assert "nextParams.set('versionId', selectedVersion.id)" in source
    assert "setSearchParams(nextParams, { replace: true })" in source
    assert "handleSelectVersion(version)" in source
    assert "selectedVersionLabel(version)" in source


def test_strategy_detail_shows_selected_version_config_and_run_history():
    source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()
    table_source = (ROOT / "frontend/src/components/strategy/VersionsTable.tsx").read_text()
    runs_source = (ROOT / "frontend/src/components/runs/RunsTable.tsx").read_text()

    assert "function configSummaryRows" in source
    assert "Version Config Summary" in source
    assert "summarizeStrategyRule(config.entry_rule" in source
    assert "summarizeStrategyRule(config.exit_rule" in source
    assert "`Results for v${selectedVersion.version_number}`" in source
    assert "`No results recorded for v${selectedVersion.version_number}.`" in source
    assert "Reference Total Return" in source
    assert "Open reference result" in source
    assert "Compare reference result" in source
    assert "run.strategy_version_id === selectedVersion.id" in source
    assert "selectedVersionId" in table_source
    assert "aria-selected={isSelected}" in table_source
    assert "Selected" in table_source
    assert "Reference" in runs_source
    assert "referenceRunId === run.run_id" in runs_source


def test_new_version_page_can_prefill_from_selected_strategy_version():
    source = (ROOT / "frontend/src/pages/CreateStrategyVersionPage.tsx").read_text()

    assert "fromVersionId" in source
    assert "findRequestedVersion" in source
    assert "sourceVersion?.config_json" in source
    assert "Starting Version" in source
    assert "Reset to Starting Version" in source
    assert "navigate(`/strategies/${strategyId}?versionId=${response.version_id}`" in source


def test_advanced_manual_run_does_not_expose_internal_s3_path():
    source = (ROOT / "frontend/src/pages/CreateSimulationPage.tsx").read_text()

    assert "s3://" not in source
    assert "us-market-data" not in source
    assert "data_path" not in source


def test_new_version_editable_config_removes_name_field():
    source = (ROOT / "frontend/src/pages/CreateStrategyVersionPage.tsx").read_text()

    assert "delete editable.name" in source
    assert "editableConfigText" in source


def test_compare_page_uses_typed_result_refs_and_sweep_variant_groups():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert "Selected Results" in source
    assert "Comparable Results" in source
    assert "searchParams.get('results')" in source
    assert "runResultRef" in source
    assert "sweepVariantResultRef" in source
    assert "isParameterSweepGroup" in source
    assert "Expand to select variants" in source
    assert "Parameter sweep · {variantCount} variants" in source
    assert "toggleResult(variant.comparable_result_ref)" in source
    assert "selectedResultRefs.length" in source
    assert "message.replace(/\\bruns\\b/g, 'results')" in source


def test_compare_page_does_not_auto_run_comparison_from_selection_or_url():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert "autoCompareKeyRef" not in source
    assert "void handleCompare(initialSelectedResultRefs)" not in source
    assert "if (initialSelectedResultRefs.length < 2)" not in source
    assert "disabled={loadingComparison || selectedResultRefs.length < 2}" in source
    assert "void handleCompare();" in source


def test_compare_page_selection_changes_clear_existing_comparison():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert "function clearComparisonOutput()" in source
    assert "setComparison(null);" in source
    assert "setComparisonChart(null);" in source
    assert "setSelectedResultRefs(next);" in source
    assert "clearComparisonOutput();" in source


def test_compare_page_sweep_expand_control_is_icon_only_and_accessible():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert "function ChevronIcon" in source
    assert "<ChevronIcon expanded={isExpanded} />" in source
    assert "aria-label={isExpanded ? 'Collapse sweep variants' : 'Expand sweep variants'}" in source
    assert "aria-expanded={isExpanded}" in source
    assert "{isExpanded ? 'Collapse' : 'Expand'}" not in source


def test_compare_page_sweep_children_are_nested_and_selectable():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert "isSweepGroup ? 'app-surface-soft border-y app-divider'" in source
    assert "bg-black/[0.025] dark:bg-white/[0.035]" in source
    assert "h-8 w-1 rounded-full bg-cyan-500/70" in source
    assert "pl-5" in source
    assert "checked={variantChecked}" in source
    assert "onChange={() => toggleResult(variant.comparable_result_ref)}" in source


def test_compare_page_uses_two_unified_chart_sections():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert 'title="Performance Comparison"' in source
    assert 'title="Drawdown Comparison"' in source
    assert 'title="Strategy Performance"' not in source
    assert 'title="Benchmark / Buy-and-Hold Reference"' not in source
    assert 'title="Strategy Drawdowns"' not in source
    assert 'title="Benchmark Drawdowns"' not in source
    assert "[...chart.strategy_curves, ...chart.benchmark_curves]" in source
    assert "[...chart.strategy_drawdown_curves, ...chart.benchmark_drawdown_curves]" in source


def test_compare_page_dedupes_shared_benchmark_chart_curves():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()
    chart_source = (ROOT / "frontend/src/components/compare/CurveChart.tsx").read_text()

    assert "function dedupeBenchmarkCurves" in source
    assert "benchmarkIdentity(curve)" in source
    assert "curveDateWindow(curve)" in source
    assert "curvePointsSignature(curve)" in source
    assert "Benchmark: ${identity}" in source
    assert "Benchmarks shown:" in source
    assert "strokeDasharray={isBenchmark" not in chart_source


def test_compare_chart_tooltip_uses_compact_labels_and_solid_benchmark_lines():
    chart_source = (ROOT / "frontend/src/components/compare/CurveChart.tsx").read_text()

    assert "function CurveTooltip" in chart_source
    assert "export function getCurveTooltipLabel" in chart_source
    assert "Benchmark: ${benchmarkLabel}" in chart_source
    assert "parameterValues.join('/')" in chart_source
    assert "className=\"truncate\"" in chart_source
    assert "w-64" in chart_source
    assert "grid-cols-[minmax(0,1fr)_auto]" in chart_source
    assert "strokeWidth={isBenchmark ? 1.75 : 2.35}" in chart_source
    assert "opacity={isBenchmark ? 0.72 : 1}" in chart_source
