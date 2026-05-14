from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_saved_strategy_current_signal_api_client_is_typed_and_safe():
    api_source = (ROOT / "frontend/src/lib/api.ts").read_text()
    types_source = (ROOT / "frontend/src/types/api.ts").read_text()

    assert "fetchStrategyCurrentSignal" in api_source
    assert "`/api/strategies/${strategyId}/current-signal" in api_source
    assert "strategy_version_id: options?.strategyVersionId" in api_source
    assert "StrategyCurrentSignalResponse" in types_source
    assert "target_weights: Record<string, number>" in types_source
    assert "fallback_used: boolean" in types_source
    assert "artifact_dir" not in types_source.split("export interface StrategyCurrentSignalResponse")[1].split("}")[0]


def test_strategy_detail_shows_current_signal_only_for_model_signal_versions():
    source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()

    assert "function isModelSignalStrategyConfig" in source
    assert "modelSignal?.enabled === true" in source
    assert "isSelectedModelSignalStrategy" in source
    assert "fetchStrategyCurrentSignal(strategyId, { strategyVersionId: selectedVersion.id })" in source
    assert "currentSignalError?.kind !== 'hidden'" in source
    assert "<CurrentSignalCard" in source
    assert "STRATEGY_NOT_MODEL_SIGNAL" in source


def test_current_signal_card_renders_compact_signal_fields_and_states():
    source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()

    assert "Current model signal" in source
    assert "Latest signal selection" in source
    assert "Paper-tracking signal. Not investment advice." in source
    assert "Loading current signal..." in source
    assert "signal artifact is missing or not configured" in source
    assert "Advanced research access is required for current model signal." in source
    assert 'label="Latest signal date"' in source
    assert 'label="Selected symbols"' in source
    assert 'label="Score"' in source
    assert 'label="Rank"' in source
    assert 'label="Signal bucket"' in source
    assert 'label="Fallback used"' in source
    assert 'label="Target weights"' in source
    assert "formatTargetWeights" in source
    assert "signalScore(signal)" in source
    assert "signalRank(signal)" in source
    assert "signalBucket(signal)" in source
    assert "Open latest run" in source
    assert "Run model backtest" in source


def test_current_signal_copy_avoids_performance_promises_and_local_paths():
    source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()
    lower_source = source.lower()

    forbidden = [
        "buy now",
        "live trading signal",
        "guaranteed",
        "will outperform",
    ]
    for phrase in forbidden:
        assert phrase not in lower_source

    assert "artifact_path" not in source
    assert "artifact_dir" not in source
    assert "MODEL_SIGNAL_DATA_PATH" not in source
