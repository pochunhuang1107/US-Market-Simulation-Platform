from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAB_SOURCE = ROOT / "frontend/src/components/model-strategy-lab/ModelStrategyLab.tsx"


def test_model_signal_api_client_functions_are_present():
    api_source = (ROOT / "frontend/src/lib/api.ts").read_text()
    types_source = (ROOT / "frontend/src/types/api.ts").read_text()

    assert "fetchModelSignalCatalog" in api_source
    assert "fetchModelSignalCatalogDetail" in api_source
    assert "fetchCurrentModelSignalPreview" in api_source
    assert "/api/model-signals/catalog" in api_source
    assert "/current`" in api_source

    assert "ModelSignalCatalogItemResponse" in types_source
    assert "ModelSignalCatalogListResponse" in types_source
    assert "ModelSignalCurrentPreviewResponse" in types_source
    assert "ModelSignalRecommendedDefaultsResponse" in types_source


def test_model_lab_route_mounts_model_strategy_lab():
    router_source = (ROOT / "frontend/src/router.tsx").read_text()
    nav_source = (ROOT / "frontend/src/components/layout/AppShell.tsx").read_text()
    page_source = (ROOT / "frontend/src/pages/ModelLabPage.tsx").read_text()
    manual_page_source = (ROOT / "frontend/src/pages/CreateSimulationPage.tsx").read_text()

    assert "import { ModelLabPage }" in router_source
    assert "{ path: '/model-lab', element: <ModelLabPage /> }" in router_source
    assert "{ to: '/model-lab', label: 'Model Lab', end: true }" in nav_source
    assert "<ModelStrategyLab />" in page_source
    assert "cataloged model-signal research now lives in Model Lab" in manual_page_source
    assert "import { ModelStrategyLab }" not in manual_page_source
    assert "<ModelStrategyLab />" not in manual_page_source


def test_model_strategy_lab_renders_catalog_preview_and_entitlement_states():
    source = LAB_SOURCE.read_text()

    assert "Model Strategy Lab" in source
    assert "fetchModelSignalCatalog()" in source
    assert "fetchCurrentModelSignalPreview(model.model_version)" in source
    assert "model.display_name" in source
    assert "model.model_version" in source
    assert "model.research_status" in source
    assert "values.length > 0 ? `${values.length} ETFs`" in source
    assert "model.supported_universe" in source
    assert "model.default_universe" in source
    assert "sameSymbols(model.supported_universe, model.default_universe)" in source
    assert 'label="Universe"' in source
    assert 'label="Supported universe"' in source
    assert 'label="Default universe"' in source
    assert "model.default_top_n" in source
    assert "model.ranking_field" in source
    assert "model.default_signal_bucket_filter" in source
    assert "model.default_fallback" in source
    assert "Signal bucket filter" in source
    assert "Fallback" in source
    assert "Latest signal date" in source
    assert "Latest signal selection" in source
    assert "Signal score" in source
    assert "Signal bucket" in source
    assert "Preview source" in source
    assert "Configured artifact (MODEL_SIGNAL_DATA_PATH)" in source
    assert "formatLatestSignalSelection" in source
    assert "formatSignalScores" in source
    assert "formatSignalBuckets" in source
    assert "formatSignalNumber" in source
    assert "previewSelectedSymbols" in source
    assert "preview.selected_rows.map((row) => row.symbol)" in source
    assert "preview.selected_symbols" in source
    assert "UniverseInfo" in source
    assert "Show all" in source
    assert "Show less" in source
    assert "expandedUniverses" in source
    assert "model.risk_notes" in source
    assert "model.limitations" in source
    assert "allow_advanced_builder" in source
    assert "Beta Tester access" in source
    assert "Current preview unavailable" in source
    assert "No model signal catalog entries are available yet." in source


def test_model_strategy_lab_run_button_uses_catalog_defaults_and_queues_run():
    source = LAB_SOURCE.read_text()

    assert "export function buildModelSignalStrategyDraft" in source
    assert "model.recommended_defaults" in source
    assert "model_signal" in source
    assert "model_version: model.model_version" in source
    assert "ranking_field: defaults.ranking_field || model.ranking_field" in source
    assert "top_n: defaults.top_n || model.default_top_n" in source
    assert "signal_bucket_filter: signalBucketFilter" in source
    assert "draft_config: draftConfig" in source
    assert "run_type: 'SIMULATION'" in source
    assert "executor_type: 'SIMULATION_EXECUTOR'" in source
    assert "source: 'model_strategy_lab'" in source
    assert "await enqueueRun(run.id)" in source
    assert "navigate(`/runs/${run.id}`)" in source
    assert "Daily simulation limit reached." in source
    assert "Current signal preview is required before running." in source


def test_model_strategy_lab_uses_careful_research_wording():
    source = LAB_SOURCE.read_text()
    lower_source = source.lower()

    assert "research model" in lower_source
    assert "paper-tracking signal" in lower_source
    assert "run historical simulation" in lower_source
    assert "not investment advice" in lower_source
    assert "linear_smooth10_margin002_v1" not in source

    forbidden = [
        "buy now",
        "guaranteed",
        "will outperform",
        "best model",
        "live trading signal",
    ]
    for phrase in forbidden:
        assert phrase not in lower_source
