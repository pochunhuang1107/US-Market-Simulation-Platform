# Artifact Correctness Checklist

## Expected Artifacts

Normal Strategy V2 run:
- Required: `summary`, `timeline`, `monthly_returns`, `trade_log`, `report_bundle`
- Optional: `sleeve_summary`, `yearly_report`, `trade_signal_snapshots`, `events`

Rotation run:
- Required: `summary`, `timeline`, `monthly_returns`, `trade_log`, `report_bundle`
- Timeline should include rotation context when available: `selected_assets`, `target_weights`, `asset_ranks`, `rebalance`, `risk_filter_passed`, `fallback_used`, `risk_filter_signals`
- Rotation trade snapshots should include ranking context and risk-filter actual values/thresholds when a risk filter is configured.
- Optional: `sleeve_summary`, `yearly_report`, `trade_signal_snapshots`, `events`
- Rotation Rebalance Inspector reads `timeline`, same-date `trade_log` rows, and optional `report_bundle.summary`

Sweep parent:
- Required: `sweep_summary`, `sweep_results`
- `sweep_summary.results` rows should include `variant_id`, metrics, status, parameters, config when available, and `artifact_dir` for succeeded variants

Sweep variant:
- Required: `timeline`, `monthly_returns`, `trade_log`
- Optional: `summary`, `sleeve_summary`, `yearly_report`, `trade_signal_snapshots`, `events`, `report_bundle`

## Missing Artifact Behavior

- Required run chart/dashboard artifacts that cannot be read return `424 ARTIFACT_UNAVAILABLE`.
- Missing optional `trade_signal_snapshots` does not fail trade inspection; the inspector falls back to timeline-derived context.
- Missing sweep variant required artifacts return `424 ARTIFACT_UNAVAILABLE` for variant trade inspection instead of a misleading empty trade list.
- Parameter sweep parent dashboards return empty chart data and show sweep results, not normal run charts.
- Compare skips unreadable chart artifacts and returns available curves plus metadata warnings where date windows cannot be inferred.

## Local/S3 Parity

- `artifact_storage_type=LOCAL` manifests must contain local filesystem paths.
- `artifact_storage_type=S3` manifests must contain `s3://` URIs and should not depend on the worker's temporary local artifact directory.
- Sweep S3 finalization rewrites variant `artifact_dir` values to S3 roots before upload.
- In S3 mode, result lists default to S3-backed runs; `artifact_storage_type=ALL` includes historical local runs.
- Detail endpoints may still show historical local run metadata even when the current backend is S3.

## Guardrails

- Do not change simulation math to satisfy artifact-reader tests.
- Do not commit generated artifact directories.
- Do not weaken run ownership checks while making missing artifacts easier to diagnose.
