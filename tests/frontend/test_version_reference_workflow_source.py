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
