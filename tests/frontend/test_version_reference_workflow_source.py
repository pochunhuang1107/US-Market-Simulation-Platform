from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_run_detail_header_does_not_expose_new_version_action():
    source = (ROOT / "frontend/src/components/run-detail/RunHeader.tsx").read_text()

    assert "New version" not in source
    assert "Back to results" in source
    assert "Open strategy" in source


def test_strategy_detail_still_exposes_new_version_and_run_this_version():
    source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()

    assert "New Version" in source
    assert "Run this version" in source
    assert "reference_strategy_version_id: currentVersion.id" in source
    assert "to={`/runs/${referenceRunId}`}" in source
    assert "to={`/compare?runIds=${referenceRunId}`}" in source


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

    assert "searchParams.get('results')" in source
    assert "runResultRef" in source
    assert "sweepVariantResultRef" in source
    assert "isParameterSweepGroup" in source
    assert "Expand to select variants" in source
    assert "Parameter sweep · {variantCount} variants" in source
    assert "toggleResult(variant.comparable_result_ref)" in source
    assert "selectedResultRefs.length" in source


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
