# ML Research Export Contract

This document is the cross-repo checklist for model signal artifacts exported by
`pochunhuang1107/US-Market-ML-Research` and consumed by this platform.

ML research, training, feature generation, labeling, notebooks, and offline
model evaluation happen in `US-Market-ML-Research`. This repository consumes
validated, point-in-time signal artifacts only. It must not train models, run
live inference, add sklearn/tensorflow runtime dependencies, or use future
labels as decision signals.

## Runtime Artifact Schema

Export one row per point-in-time `date` / `symbol` / `model_version` signal.

Required columns:

| Column | Type | Notes |
| --- | --- | --- |
| `date` | ISO date string or date-like | Point-in-time signal availability date, normalized by the platform to midnight. |
| `symbol` | string | Supported ETF symbol from this platform's ETF universe. Symbols are normalized to uppercase. |
| `model_version` | string | Non-empty immutable model artifact/version identifier. Must not contain path separators. |
| `score` | numeric | Ranking or prediction score used by model-signal strategies. Higher scores rank first. |

Optional columns:

| Column | Type | Notes |
| --- | --- | --- |
| `predicted_return` | numeric | Optional predicted return. This is a prediction, not a realized future return. |
| `rank` | numeric | Optional cross-sectional rank for the same date/model version. |
| `confidence` | numeric | Optional confidence from `0` to `1`, inclusive. |
| `signal_bucket` | string | Optional filter bucket. Currently supported by strategy filtering as exact string values; use `top`, `middle`, `bottom`, or stable quantile names such as `q1` through `q5`. |
| `feature_set_version` | string | Optional immutable feature pipeline/version identifier. |
| `label_horizon_days` | numeric | Optional training metadata describing the research label horizon, for example `21`. It is metadata only. |
| `created_at` | timestamp-like | Optional artifact creation timestamp. |

## Naming Conventions

Use stable lowercase identifiers with hyphens or underscores:

- `model_version`: `<model-family>-<target>-v<integer>` or
  `<model-family>-<target>-YYYYMMDD`, for example `etf-ranker-21d-v1`.
- `feature_set_version`: `features-<domain>-v<integer>` or
  `features-<domain>-YYYYMMDD`, for example `features-crossasset-v4`.
- `label_horizon_days`: integer number of calendar days represented by the
  research label horizon. Do not encode multiple horizons in one runtime row.

## Date And No-Lookahead Rules

`date` is the availability date for the exported signal. A Strategy V2
model-signal run may use a signal row only on or after that date, and the engine
selects the latest eligible row as of each rebalance date.

Runtime artifacts must not include future realized returns, labels, outcomes, or
target columns such as `future_return`, `forward_return`, `realized_return`,
`target_return`, or horizon-prefixed variants like `future_return_21d`. Research
labels can remain in `US-Market-ML-Research` or in a separate research-only
export, but this platform's runtime artifact never uses them as decision
signals.

## File And Storage Convention

Preferred local export:

```text
data/exports/model_signals/model_version=<MODEL_VERSION>/signals.parquet
```

Supported validation formats are `.csv`, `.json`, `.jsonl`, and `.parquet`.
Keep examples tiny and do not commit large generated model signal files.

Intended curated S3-style path:

```text
s3://<bucket>/curated/model_signals/model_version=<MODEL_VERSION>/signals.parquet
```

This platform's validation CLI and tests do not require S3 credentials.

## Example Research Export

From `pochunhuang1107/US-Market-ML-Research`, an export command should produce a
validated runtime artifact:

```bash
python scripts/export_model_signals.py \
  --model-version etf-ranker-21d-v1 \
  --feature-set-version features-crossasset-v4 \
  --label-horizon-days 21 \
  --output data/exports/model_signals/model_version=etf-ranker-21d-v1/signals.parquet
```

Expected output shape:

```text
wrote data/exports/model_signals/model_version=etf-ranker-21d-v1/signals.parquet
rows: 7800
date_min: 2021-01-29
date_max: 2025-12-31
symbols: QQQ, SPY, TLT, XLK
model_versions: etf-ranker-21d-v1
```

## Platform Validation

Validate an exported artifact from this repository before using it in a
simulation:

```bash
python scripts/validate_model_signal_export.py \
  --path data/exports/model_signals/model_version=etf-ranker-21d-v1/signals.parquet \
  --model-version etf-ranker-21d-v1 \
  --start-date 2021-01-01 \
  --end-date 2025-12-31
```

The command loads the artifact through the platform model-signal repository and
validation utilities, prints a compact summary, and exits nonzero if the file is
not consumable by this platform.

## Checklist

- Export only point-in-time runtime signals from `US-Market-ML-Research`.
- Include `date`, `symbol`, `model_version`, and `score`.
- Use supported ETF symbols only.
- Keep one row per `date` / `symbol` / `model_version`.
- Keep future labels and realized outcomes out of runtime artifacts.
- Use immutable `model_version` and `feature_set_version` values.
- Store local and S3 artifacts under `model_version=<MODEL_VERSION>/signals.parquet`.
- Validate with `scripts/validate_model_signal_export.py` before platform use.
