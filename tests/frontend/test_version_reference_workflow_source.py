from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_run_detail_header_does_not_expose_new_version_action():
    source = (ROOT / "frontend/src/components/run-detail/RunHeader.tsx").read_text()

    assert "New version" not in source
    assert "Back to Results" in source
    assert "Compare this result" in source
    assert "Save strategy" in source
    assert "Modify in Workspace" in source
    assert "Finished</div>" in source
    assert "whitespace-nowrap" in source
    assert "min-w-[13rem]" in source
    assert "Result ID:" in source
    assert "Simulation Result" in source
    assert "Parameter Sweep Result" in source
    assert "Open strategy" in source


def test_completed_run_detail_keeps_chart_first_compact_result_hierarchy():
    page_source = (ROOT / "frontend/src/pages/RunDetailPage.tsx").read_text()
    hero_source = (ROOT / "frontend/src/components/run-detail/RunInsightHero.tsx").read_text()

    assert "NextResearchStepsPanel" not in page_source
    assert "canSaveDraftStrategy = Boolean" in page_source
    assert "getDraftConfig(data.run)" in page_source
    assert "Completed result" in hero_source
    assert "isModelSignalHero" in hero_source
    assert "grid items-start gap-6" in hero_source
    assert "h-[320px]" in hero_source
    assert "self-start rounded-3xl" in hero_source
    assert "h-[360px]" in hero_source
    assert "const cagrPct = getSummaryNumber(summary, 'cagr_pct');" in hero_source
    assert "label: 'Total Return'" in hero_source
    assert "label: 'CAGR'" in hero_source
    assert "label: 'Max Drawdown'" in hero_source
    assert "label: 'Trades'" in hero_source
    assert "label: 'Alpha'" in hero_source
    assert "label: 'Sharpe'" not in hero_source
    assert "verdict.description" not in hero_source


def test_run_detail_displays_model_signal_context_without_affecting_normal_drafts():
    page_source = (ROOT / "frontend/src/pages/RunDetailPage.tsx").read_text()
    header_source = (ROOT / "frontend/src/components/run-detail/RunHeader.tsx").read_text()
    hero_source = (ROOT / "frontend/src/components/run-detail/RunInsightHero.tsx").read_text()
    context_source = (ROOT / "frontend/src/lib/modelSignalRunContext.ts").read_text()

    assert "fetchModelSignalCatalogDetail(modelVersion)" in page_source
    assert "modelSignalCatalogItem={modelSignalCatalogItem}" in page_source
    assert "getModelSignalVersion" in page_source
    assert "Model Signal Result" in header_source
    assert "Model signal strategy" in header_source
    assert ": 'Unsaved draft run'" in header_source
    assert "modelSignalContext ? modelSignalContext.displayName ?? 'Model signal strategy' : 'Draft strategy'" in hero_source
    assert "ModelSignalContextPill" in hero_source
    assert "Model version" in hero_source
    assert "Signal date" in hero_source
    assert "Ranking field" in hero_source
    assert "Top N" in hero_source
    assert "Signal bucket" in hero_source
    assert "Fallback" in hero_source
    assert "Latest rebalance holding" in hero_source
    assert "latestRebalanceSelection" in hero_source
    assert "Paper tracking" in hero_source
    assert "Research-only paper-tracking signal; not investment advice." in hero_source
    assert "Research / paper tracking" in context_source
    assert "paper tracking - paper-tracking" not in context_source
    assert "summary.strategy_type === 'model_signal'" in context_source
    assert "draftConfig.model_signal.enabled === true" in context_source
    assert "run.request_payload?.latest_signal_date" in context_source
    assert "selected_symbols" not in context_source
    assert "Modify in Model Lab" in header_source


def test_strategy_behavior_summary_includes_model_signal_fields():
    source = (ROOT / "frontend/src/lib/strategyBehaviorSummary.ts").read_text()

    assert "modelSignal?.enabled === true" in source
    assert "label: 'Model version'" in source
    assert "label: 'Model universe'" in source
    assert "label: 'Ranking field'" in source
    assert "label: 'Signal bucket'" in source
    assert "label: 'Fallback'" in source


def test_run_detail_uses_rotation_rebalance_inspector_for_rotation_runs():
    page_source = (ROOT / "frontend/src/pages/RunDetailPage.tsx").read_text()
    inspector_source = (
        ROOT / "frontend/src/components/run-detail/RotationRebalanceInspector.tsx"
    ).read_text()
    types_source = (ROOT / "frontend/src/types/api.ts").read_text()

    assert "import { RotationRebalanceInspector }" in page_source
    assert "data.rotation_review?.is_rotation" in page_source
    assert "mode={isModelSignal ? 'model_signal' : 'rotation'}" in page_source
    assert "isRotation ? (" in page_source
    assert "Rotation rebalance artifacts are not available for this result." in page_source
    assert "<TradeEventInspector runId={data.run.id} />" in page_source
    assert "Rotation Rebalance Inspector" in inspector_source
    assert "Ranks / trailing returns" in inspector_source
    assert "Rebalance trades" in inspector_source
    assert "Holdings after rebalance" in inspector_source
    assert "Model Signal Selection Inspector" in inspector_source
    assert "Model signal scores" in inspector_source
    assert "min-w-[760px]" in inspector_source
    assert "min-w-24 px-3 py-2" in inspector_source
    assert "model_score" in types_source
    assert "model_signal_date" in types_source
    assert "rotation_review: Nullable<RotationReviewResponse>;" in types_source


def test_model_signal_breakdown_hides_builder_prompts():
    source = (ROOT / "frontend/src/components/run-detail/RunInsightBreakdown.tsx").read_text()

    assert "isModelSignalRun" in source
    assert "const nextSteps = isModelSignal ? [] : buildNextSteps" in source
    assert "nextSteps.length > 0" in source


def test_run_detail_hero_has_optional_universe_equal_weight_metrics():
    hero_source = (ROOT / "frontend/src/components/run-detail/RunInsightHero.tsx").read_text()

    assert "universe_equal_weight_buy_hold_return_pct" in hero_source
    assert "label: 'Equal-Weight Universe'" in hero_source
    assert "label: 'Universe Alpha'" in hero_source
    assert "label: 'Rebalances'" in hero_source


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


def test_run_detail_stops_polling_when_succeeded_artifacts_are_unavailable():
    source = (ROOT / "frontend/src/pages/RunDetailPage.tsx").read_text()
    api_source = (ROOT / "frontend/src/lib/api.ts").read_text()

    assert "isArtifactUnavailableError" in source
    assert "artifactUnavailableMessage" in source
    assert "setArtifactUnavailable(artifactUnavailableMessage(error));" in source
    assert "setIsFinalizing(false);" in source
    assert "Result artifacts are unavailable" in source
    assert "RunMetaPanel run={run}" in source
    assert "RunInsightBreakdown run={run}" in source
    assert "ARTIFACT_UNAVAILABLE" in api_source
    assert "error.status !== 424" in api_source


def test_trade_event_inspector_distinguishes_missing_artifacts_from_empty_trades():
    source = (ROOT / "frontend/src/components/run-detail/TradeEventInspector.tsx").read_text()

    assert "isArtifactUnavailableError" in source
    assert "artifactUnavailableMessage(error)" in source
    assert "No trade events were available for this result." in source


def test_results_page_exposes_compact_artifact_storage_filter():
    page_source = (ROOT / "frontend/src/pages/RunsPage.tsx").read_text()
    filters_source = (ROOT / "frontend/src/components/runs/RunFilters.tsx").read_text()
    types_source = (ROOT / "frontend/src/types/api.ts").read_text()

    assert "artifactStorageType || undefined" in page_source
    assert "artifact_storage_type?: RunArtifactStorageFilter;" in types_source
    assert "Storage" in filters_source
    assert '<option value="">Current storage</option>' in filters_source
    assert '<option value="ALL">All</option>' in filters_source
    assert '<option value="S3">S3</option>' in filters_source
    assert '<option value="LOCAL">Local</option>' in filters_source


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
    assert "comparableResultTypeLabel" in source
    assert "comparableResultDetailPath" in source


def test_compare_page_does_not_auto_run_comparison_from_selection_or_url():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert "autoCompareKeyRef" not in source
    assert "void handleCompare(initialSelectedResultRefs)" not in source
    assert "if (initialSelectedResultRefs.length < 2)" not in source
    assert "disabled={loadingComparison || selectedResultRefs.length < 2}" in source
    assert "void handleCompare();" in source
    assert "Compare ${selectedResultRefs.length} selected" in source


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


def test_compare_page_empty_and_selected_states_explain_supported_targets():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert "Select 2+ results, then compare when ready." in source
    assert "Select 2+ results." in source
    assert "Runs and selected sweep variants are supported." in source
    assert "Expand sweep parents to choose variants." in source
    assert "Status: {comparableResultStatusLabel(run)}" in source
    assert "Remove" in source


def test_compare_page_outputs_metrics_before_charts_with_source_links():
    source = (ROOT / "frontend/src/pages/ComparePage.tsx").read_text()

    assert "Comparison metrics" in source
    assert "Top return" in source
    assert "Top relative result" in source
    assert "<th className=\"px-4 py-3\">Benchmark</th>" in source
    assert "<th className=\"px-4 py-3\">Trades</th>" in source
    assert "formatPct(run.benchmark_return_pct)" in source
    assert "formatNumber(run.trade_count)" in source
    assert "to={comparableResultDetailPath(run)}" in source
    assert "ComparisonInsightSummary" not in source
    assert "Next comparison steps" not in source


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
