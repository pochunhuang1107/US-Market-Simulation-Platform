from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from market_simulator.platform.services.artifact_manifest import build_variant_artifact_manifest
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

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploads.append((filename, bucket, key))
        self.objects[(bucket, key)] = Path(filename).read_bytes()

    def body_text(self, bucket: str, key: str) -> str:
        return self.objects[(bucket, key)].decode("utf-8")

    def get_object(self, Bucket: str, Key: str):
        return {"Body": FakeBody(self.objects[(Bucket, Key)])}


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
