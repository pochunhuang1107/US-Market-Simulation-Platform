# Model Signal Ingestion Contract

This contract defines how the platform will ingest precomputed ML model signal
artifacts from `pochunhuang1107/US-Market-ML-Research`. It is intentionally an
ingestion and validation boundary only. Model training, live inference,
notebooks, feature research, and model evaluation workflows are out of scope for
this repository.

The platform consumes validated, point-in-time signal files as deterministic
inputs for Strategy V2 model-signal simulations. This repository does not train
models, run notebooks, perform live inference, add sklearn/tensorflow runtime
dependencies, or call external ML services.

## File Schema

Signal artifacts are tabular files with one row per `date` / `symbol` /
`model_version` signal. The schema supports cross-sectional ETF ranking signals
at daily, monthly, or other explicit signal dates.

Required columns:

| Column | Type | Notes |
| --- | --- | --- |
| `date` | date-like | Signal date. The signal is available for decisions on or after this date according to the strategy execution convention used later. |
| `symbol` | string | Supported ETF symbol from the platform ETF universe. |
| `model_version` | string | Non-empty immutable model artifact/version identifier. |
| `score` | numeric | Ranking score or prediction score. Higher/lower direction must be documented by the exporting model version. |

Optional columns:

| Column | Type | Notes |
| --- | --- | --- |
| `predicted_return` | numeric | Optional model-predicted return. This is a prediction, not a realized future return. |
| `rank` | numeric | Optional cross-sectional rank for the same date/model version. |
| `confidence` | numeric | Optional confidence from `0` to `1`, inclusive. |
| `signal_bucket` | string | Optional bucket such as `top`, `middle`, `bottom`, or quantile labels. |
| `feature_set_version` | string | Optional feature pipeline/version identifier from the ML research repo. |
| `label_horizon_days` | numeric | Optional metadata describing the research label horizon used to train or evaluate the model. |
| `created_at` | timestamp-like | Optional artifact creation timestamp. |

Small CSV example:

```csv
date,symbol,model_version,score,predicted_return,rank,confidence,signal_bucket
2024-01-31,QQQ,etf-ranker-v1,0.72,0.018,1,0.83,top
2024-01-31,SPY,etf-ranker-v1,0.41,0.009,2,0.61,middle
2024-01-31,TLT,etf-ranker-v1,-0.12,-0.004,3,0.55,bottom
```

Supported local file formats for validation are `.csv`, `.json`, `.jsonl`, and
`.parquet`.

## Validation Rules

`validate_model_signal_frame(...)` enforces:

- Required columns exist: `date`, `symbol`, `model_version`, `score`.
- `date` values parse as dates.
- `symbol` values are supported ETF symbols.
- `model_version` is present and non-empty.
- No duplicate `date` / `symbol` / `model_version` rows exist.
- `score` is numeric.
- `rank` is numeric when present.
- `confidence` is between `0` and `1` when present.
- Runtime files do not include lookahead label columns such as `future_return`,
  `forward_return`, `realized_return`, `target_return`, or prefixed variants
  like `future_return_21d`.

## No-Lookahead Rules

The signal `date` is the point-in-time availability date. Future Strategy V2
execution should treat a signal row as available only on or after that date,
subject to the execution convention selected later.

Runtime ingestion must not require future realized returns, labels, performance
outcomes, or any other value that would not have been known at the signal date.
Prediction and score fields are allowed. Research labels may exist in the ML
research repository, but exported future-return labels must either be excluded
from runtime signal artifacts or written to a separate research-only file.

## Storage Convention

Preferred curated layout:

```text
curated/model_signals/model_version=<VERSION>/signals.parquet
```

The same layout can be mirrored locally or in S3 later, for example:

```text
s3://<bucket>/curated/model_signals/model_version=etf-ranker-v1/signals.parquet
```

Tests and validation utilities do not require S3 or AWS credentials.

## Export Expectations For ML Research

`pochunhuang1107/US-Market-ML-Research` should export one validated signal file
per immutable model version. The export should:

- Use supported ETF symbols only.
- Include a non-empty `model_version` matching the artifact directory.
- Emit point-in-time `date` values matching when each signal becomes available.
- Include deterministic `score` values suitable for cross-sectional ranking.
- Keep training labels and realized future performance columns out of runtime
  signal files.

## Strategy V2 Consumption

The model-signal Strategy V2 MVP consumes an injected, already validated signal
frame using a block like:

```yaml
model_signal:
  enabled: true
  model_version: "ml_v1"
  ranking_field: "score"
  universe: ["QQQ", "SPY", "XLK", "TLT"]
  top_n: 2
  rebalance:
    frequency: "monthly"
    day: "first_trading_day"
  fallback:
    type: "cash"
  min_confidence: 0.6
  signal_bucket_filter: ["top"]
```

On each rebalance date, execution filters rows to the configured
`model_version`, configured universe, and rows whose signal `date` is on or
before the rebalance date. If multiple rows are available for a symbol, the
latest available row is used. Rows after the rebalance date are ignored, even if
they would change the ranking.

Eligible symbols are ranked descending by `ranking_field`, with symbol as the
deterministic tie-breaker. The engine holds the top `top_n` symbols at equal
weight. If no eligible rows remain after `min_confidence` or
`signal_bucket_filter` filters, the configured fallback is used: cash or a
single fallback ETF.

Timeline and rebalance rows add model-signal fields such as `selected_assets`,
`target_weights`, `model_scores`, `model_ranks`, `model_signal_dates`,
`model_version`, `rebalance`, `holdings`, and `cash`. These fields are additive
and do not change existing single-ETF or rotation outputs.

## Platform Interfaces

The platform-side placeholder types are:

- `ModelSignalDataset`
- `ModelSignalRepository`
- `validate_model_signal_frame(...)`
- `load_model_signal_frame(...)`

The MVP test path injects a pandas DataFrame directly into the engine. Local
file loading is available for CSV, JSON/JSONL, and parquet artifacts. S3 path
integration should reuse the documented
`curated/model_signals/model_version=<VERSION>/signals.parquet` convention in a
future branch; tests must not require S3 or AWS credentials.
