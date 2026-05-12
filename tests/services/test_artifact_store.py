from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from market_simulator.platform.services.artifact_manifest import (
    ARTIFACT_EXPECTATIONS_BY_RUN_TYPE,
    RUN_ARTIFACT_FILES,
    SWEEP_ARTIFACT_FILES,
    build_variant_artifact_manifest,
)
from market_simulator.platform.services.artifact_store import S3ArtifactStore
from market_simulator.platform.services.run_chart_service import RunChartService


class FakeBody:
    def __init__(self, content: bytes):
        self.content = content

    def read(self) -> bytes:
        return self.content


class FakeS3Client:
    def __init__(self):
        self.uploads: list[tuple[str, str, str]] = []
        self.objects: dict[tuple[str, str], bytes] = {}
        self.presign_calls: list[tuple[str, dict, int]] = []

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploads.append((filename, bucket, key))
        self.objects[(bucket, key)] = Path(filename).read_bytes()

    def body_text(self, bucket: str, key: str) -> str:
        return self.objects[(bucket, key)].decode("utf-8")

    def get_object(self, Bucket: str, Key: str):
        return {"Body": FakeBody(self.objects[(Bucket, Key)])}

    def generate_presigned_url(self, operation: str, Params: dict, ExpiresIn: int):
        self.presign_calls.append((operation, Params, ExpiresIn))
        return f"https://signed.example.test/{Params['Bucket']}/{Params['Key']}"


def _write_variant_artifacts(variant_dir: Path) -> None:
    variant_dir.mkdir(parents=True)
    (variant_dir / "summary.json").write_text(
        json.dumps({"total_return_pct": 12.5}),
        encoding="utf-8",
    )
    (variant_dir / "sleeve_summary.json").write_text("{}", encoding="utf-8")
    (variant_dir / "yearly_report.csv").write_text(
        "year,end_equity\n2024,112.5\n",
        encoding="utf-8",
    )
    (variant_dir / "trade_log.csv").write_text("date,action\n2024-01-02,BUY\n", encoding="utf-8")
    (variant_dir / "trade_signal_snapshots.json").write_text(
        '[{"event_index":0,"signals":[]}]\n',
        encoding="utf-8",
    )
    (variant_dir / "timeline.csv").write_text(
        "date,strategy_equity,benchmark_equity\n2024-01-01,100,100\n2024-01-02,112.5,108\n",
        encoding="utf-8",
    )
    (variant_dir / "events.csv").write_text("date,event\n2024-01-02,buy\n", encoding="utf-8")
    (variant_dir / "monthly_returns.csv").write_text(
        "month,strategy_return_pct\n2024-01,12.5\n",
        encoding="utf-8",
    )
    (variant_dir / "report_bundle.json").write_text("{}", encoding="utf-8")


def _write_normal_artifacts(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"total_return_pct": 10.0}),
        encoding="utf-8",
    )
    (run_dir / "sleeve_summary.json").write_text("{}", encoding="utf-8")
    (run_dir / "yearly_report.csv").write_text(
        "year,end_equity\n2024,110\n",
        encoding="utf-8",
    )
    (run_dir / "trade_log.csv").write_text("date,action\n2024-01-02,BUY\n", encoding="utf-8")
    (run_dir / "trade_signal_snapshots.json").write_text(
        '[{"event_index":0,"signals":[]}]\n',
        encoding="utf-8",
    )
    (run_dir / "timeline.csv").write_text(
        "date,strategy_equity,benchmark_equity\n2024-01-01,100,100\n2024-01-02,110,105\n",
        encoding="utf-8",
    )
    (run_dir / "events.csv").write_text("date,event\n2024-01-02,buy\n", encoding="utf-8")
    (run_dir / "monthly_returns.csv").write_text(
        "month,strategy_return_pct\n2024-01,10\n",
        encoding="utf-8",
    )
    (run_dir / "report_bundle.json").write_text(
        json.dumps({"summary": "bundle"}),
        encoding="utf-8",
    )


def test_s3_finalize_simulation_artifacts_uploads_expected_manifest(tmp_path) -> None:
    run_id = "run-normal-123"
    bucket = "unit-test-bucket"
    run_dir = tmp_path / "runs" / run_id
    _write_normal_artifacts(run_dir)

    s3 = FakeS3Client()
    store = S3ArtifactStore(
        bucket=bucket,
        prefix="artifacts",
        region="us-west-2",
        local_base_dir=str(tmp_path),
        s3_client=s3,
    )

    result = store.finalize_simulation_artifacts(run_id)

    assert result.storage_type == "S3"
    assert result.artifact_root_uri == f"s3://{bucket}/artifacts/runs/{run_id}"
    assert result.manifest_json["summary"] == (
        f"s3://{bucket}/artifacts/runs/{run_id}/summary.json"
    )
    assert result.manifest_json["timeline"] == (
        f"s3://{bucket}/artifacts/runs/{run_id}/timeline.csv"
    )
    assert result.manifest_json["trade_log"] == (
        f"s3://{bucket}/artifacts/runs/{run_id}/trade_log.csv"
    )
    assert result.manifest_json["report_bundle"] == (
        f"s3://{bucket}/artifacts/runs/{run_id}/report_bundle.json"
    )
    assert result.manifest_json["trade_signal_snapshots"] == (
        f"s3://{bucket}/artifacts/runs/{run_id}/trade_signal_snapshots.json"
    )

    uploaded_keys = {key for _, _, key in s3.uploads}
    assert {
        f"artifacts/runs/{run_id}/summary.json",
        f"artifacts/runs/{run_id}/timeline.csv",
        f"artifacts/runs/{run_id}/trade_log.csv",
        f"artifacts/runs/{run_id}/report_bundle.json",
        f"artifacts/runs/{run_id}/trade_signal_snapshots.json",
        f"artifacts/runs/{run_id}/monthly_returns.csv",
    }.issubset(uploaded_keys)
    assert s3.body_text(bucket, f"artifacts/runs/{run_id}/summary.json") == (
        '{"total_return_pct": 10.0}'
    )

    chart_service = object.__new__(RunChartService)
    chart_service.s3 = s3
    chart_data = chart_service.load_chart_data(result.manifest_json)
    assert chart_data["equity_curve"][-1]["strategy_equity"] == 110.0
    assert chart_data["monthly_returns"][0]["return_pct"] == 10.0
    assert chart_data["trade_markers"][0]["side"] == "BUY"


def test_artifact_expectations_codify_required_and_optional_run_types() -> None:
    assert ARTIFACT_EXPECTATIONS_BY_RUN_TYPE["SIMULATION"]["required"] == (
        "summary",
        "timeline",
        "monthly_returns",
        "trade_log",
        "report_bundle",
    )
    assert "trade_signal_snapshots" in ARTIFACT_EXPECTATIONS_BY_RUN_TYPE["SIMULATION"]["optional"]
    assert ARTIFACT_EXPECTATIONS_BY_RUN_TYPE["ROTATION"]["timeline_fields"] == (
        "selected_assets",
        "target_weights",
        "asset_ranks",
        "rebalance",
    )
    assert ARTIFACT_EXPECTATIONS_BY_RUN_TYPE["PARAMETER_SWEEP"]["required"] == (
        "sweep_summary",
        "sweep_results",
    )
    assert ARTIFACT_EXPECTATIONS_BY_RUN_TYPE["SWEEP_VARIANT"]["required"] == (
        "timeline",
        "monthly_returns",
        "trade_log",
    )


def test_local_finalize_uses_local_paths_and_sweep_manifest_keys(tmp_path) -> None:
    from market_simulator.platform.services.artifact_store import LocalArtifactStore

    run_id = "run-local-123"
    store = LocalArtifactStore(base_dir=str(tmp_path))

    simulation_result = store.finalize_simulation_artifacts(run_id)
    assert simulation_result.storage_type == "LOCAL"
    assert set(simulation_result.manifest_json) == set(RUN_ARTIFACT_FILES)
    assert all(not str(uri).startswith("s3://") for uri in simulation_result.manifest_json.values())
    assert simulation_result.manifest_json["timeline"] == str(
        tmp_path / "runs" / run_id / "timeline.csv"
    )

    sweep_result = store.finalize_sweep_artifacts(run_id)
    assert set(sweep_result.manifest_json) == set(SWEEP_ARTIFACT_FILES)
    assert sweep_result.manifest_json["sweep_summary"] == str(
        tmp_path / "runs" / run_id / "sweep_summary.json"
    )


def test_s3_download_urls_only_presign_s3_artifact_uris(tmp_path) -> None:
    s3 = FakeS3Client()
    store = S3ArtifactStore(
        bucket="unit-test-bucket",
        prefix="artifacts",
        region="us-west-2",
        local_base_dir=str(tmp_path),
        s3_client=s3,
    )

    assert store.generate_download_url("/tmp/local-artifacts/summary.json") is None
    signed_url = store.generate_download_url(
        "s3://unit-test-bucket/artifacts/runs/run-123/summary.json"
    )

    assert signed_url == (
        "https://signed.example.test/unit-test-bucket/artifacts/runs/run-123/"
        "summary.json"
    )
    assert s3.presign_calls == [
        (
            "get_object",
            {
                "Bucket": "unit-test-bucket",
                "Key": "artifacts/runs/run-123/summary.json",
            },
            3600,
        )
    ]


def test_s3_finalize_sweep_artifacts_uploads_root_and_variant_files_and_rewrites_rows(
    tmp_path,
) -> None:
    run_id = "run-123"
    bucket = "unit-test-bucket"
    run_dir = tmp_path / "runs" / run_id
    variant_dir = run_dir / "variants" / "001_variant-a"
    _write_variant_artifacts(variant_dir)

    local_artifact_dir = str(variant_dir)
    summary = {
        "run_type": "PARAMETER_SWEEP",
        "ranking_metric": "sharpe_ratio",
        "variant_count": 1,
        "best_variant": {
            "variant_id": "variant-a",
            "status": "SUCCEEDED",
            "artifact_dir": local_artifact_dir,
        },
        "results": [
            {
                "variant_id": "variant-a",
                "status": "SUCCEEDED",
                "artifact_dir": local_artifact_dir,
            }
        ],
    }
    (run_dir / "sweep_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with (run_dir / "sweep_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["rank", "variant_id", "status", "artifact_dir"])
        writer.writeheader()
        writer.writerow(
            {
                "rank": 1,
                "variant_id": "variant-a",
                "status": "SUCCEEDED",
                "artifact_dir": local_artifact_dir,
            }
        )

    s3 = FakeS3Client()
    store = S3ArtifactStore(
        bucket=bucket,
        prefix="artifacts",
        region="us-west-2",
        local_base_dir=str(tmp_path),
        s3_client=s3,
    )

    result = store.finalize_sweep_artifacts(run_id)

    expected_variant_uri = f"s3://{bucket}/artifacts/runs/{run_id}/variants/001_variant-a"
    assert result.artifact_root_uri == f"s3://{bucket}/artifacts/runs/{run_id}"
    assert result.summary_json["results"][0]["artifact_dir"] == expected_variant_uri
    assert result.summary_json["best_variant"]["artifact_root_uri"] == expected_variant_uri

    uploaded_keys = {key for _, _, key in s3.uploads}
    assert {
        f"artifacts/runs/{run_id}/sweep_summary.json",
        f"artifacts/runs/{run_id}/sweep_results.csv",
        f"artifacts/runs/{run_id}/variants/001_variant-a/summary.json",
        f"artifacts/runs/{run_id}/variants/001_variant-a/timeline.csv",
        f"artifacts/runs/{run_id}/variants/001_variant-a/trade_log.csv",
        f"artifacts/runs/{run_id}/variants/001_variant-a/trade_signal_snapshots.json",
        f"artifacts/runs/{run_id}/variants/001_variant-a/monthly_returns.csv",
    }.issubset(uploaded_keys)

    uploaded_summary = json.loads(
        s3.body_text(bucket, f"artifacts/runs/{run_id}/sweep_summary.json")
    )
    assert uploaded_summary["results"][0]["artifact_dir"] == expected_variant_uri
    assert str(tmp_path) not in json.dumps(uploaded_summary)

    uploaded_results = s3.body_text(bucket, f"artifacts/runs/{run_id}/sweep_results.csv")
    rows = list(csv.DictReader(io.StringIO(uploaded_results)))
    assert rows[0]["artifact_dir"] == expected_variant_uri
    assert str(tmp_path) not in uploaded_results

    chart_service = object.__new__(RunChartService)
    chart_service.s3 = s3
    chart_data = chart_service.load_chart_data(
        build_variant_artifact_manifest(expected_variant_uri)
    )
    assert chart_data["equity_curve"][-1]["strategy_equity"] == 112.5
    assert chart_data["monthly_returns"][0]["return_pct"] == 12.5
    assert chart_data["trade_markers"][0]["side"] == "BUY"


def test_variant_artifact_manifest_supports_s3_without_local_path_checks() -> None:
    manifest = build_variant_artifact_manifest(
        "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a",
        require_local_required_files=True,
    )

    assert manifest == {
        "summary": "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/summary.json",
        "sleeve_summary": (
            "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/"
            "sleeve_summary.json"
        ),
        "yearly_report": (
            "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/"
            "yearly_report.csv"
        ),
        "trade_log": "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/trade_log.csv",
        "timeline": "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/timeline.csv",
        "trade_signal_snapshots": (
            "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/"
            "trade_signal_snapshots.json"
        ),
        "events": "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/events.csv",
        "monthly_returns": (
            "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/"
            "monthly_returns.csv"
        ),
        "report_bundle": (
            "s3://unit-test-bucket/artifacts/runs/run-123/variants/001_variant-a/"
            "report_bundle.json"
        ),
    }


def test_local_variant_artifact_manifest_still_requires_chart_files(tmp_path) -> None:
    variant_dir = tmp_path / "variants" / "001_variant-a"
    variant_dir.mkdir(parents=True)
    assert build_variant_artifact_manifest(
        str(variant_dir),
        require_local_required_files=True,
    ) is None

    for filename in ("timeline.csv", "monthly_returns.csv", "trade_log.csv"):
        (variant_dir / filename).write_text("date,value\n2024-01-01,1\n", encoding="utf-8")

    manifest = build_variant_artifact_manifest(
        str(variant_dir),
        require_local_required_files=True,
    )
    assert manifest["timeline"] == str(variant_dir / "timeline.csv")
