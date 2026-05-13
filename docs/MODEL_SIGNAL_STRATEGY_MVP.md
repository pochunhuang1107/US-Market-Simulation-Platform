# Model-Signal Strategy MVP

Strategy V2 supports a backend-only MVP for deterministic model-signal-driven
ETF rotation. The platform consumes precomputed signal artifacts exported by
`pochunhuang1107/US-Market-ML-Research`; it does not train models, run live
inference, add notebooks, add sklearn/tensorflow dependencies, or call external
ML services.

The backend catalog in `docs/MODEL_SIGNAL_CATALOG.md` owns onboarded model
metadata and recommended defaults. Runtime execution still uses the explicit
Strategy V2 `model_signal` block and separately managed signal artifacts.

## Strategy V2 Block

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
    type: "asset"
    symbol: "TLT"
  min_confidence: 0.6
  signal_bucket_filter: ["top"]
```

`rotation` and `model_signal` are mutually exclusive. Existing single-ETF and
rotation configs remain unchanged.

## Execution Convention

On each rebalance date, the engine uses only rows where:

- `model_version` equals the configured model version
- `symbol` is in the configured universe
- signal `date` is on or before the rebalance date
- `confidence` meets `min_confidence`, when configured
- `signal_bucket` is included in `signal_bucket_filter`, when configured

For each symbol, the latest eligible signal row as of the rebalance date is
used. Future rows are ignored. Eligible symbols are ranked descending by
`ranking_field`, then by symbol for deterministic tie-breaking. The strategy
holds the top `top_n` symbols at equal weight.

If no signals are eligible, the strategy follows `fallback`: hold cash or hold
the configured fallback ETF.

## Artifact Fields

Timeline rows add model-signal-specific fields:

- `selected_assets`
- `target_weights`
- `model_scores`
- `model_ranks`
- `model_signal_dates`
- `model_version`
- `ranking_field`
- `rebalance`
- `fallback_used`
- `holdings`
- `cash`

These columns are additive and do not change existing Strategy V2 artifacts.

## Loading

Tests inject pandas DataFrames directly into `run_simulation(...,
model_signal_frame=...)`. When no frame is injected and `model_signal.enabled`
is true, `run_simulation(...)` loads precomputed artifacts through
`ModelSignalRepository` from `MODEL_SIGNAL_DATA_PATH`.

`MODEL_SIGNAL_DATA_PATH` defaults to empty, so beta preflight does not require a
real model-signal path unless model-signal strategies are intentionally run.
Supported local shapes include:

```text
/data/curated/model_signals/model_version=<VERSION>/signals.parquet
/data/curated/model_signals/model_version=<VERSION>/signals.csv
/data/curated/model_signals
/data/curated/model_signals/**/*.parquet
```

The intended S3-style shape mirrors the ML research export layout:

```text
s3://<bucket>/curated/model_signals/model_version=<VERSION>/signals.parquet
s3://<bucket>/curated/model_signals/**/*.parquet
```

Artifacts are validated with the model-signal ingestion contract, then filtered
by configured `model_version`, universe, and strategy date range before
execution. This repo remains an artifact consumer only: no training, notebooks,
live inference, sklearn, or tensorflow runtime dependencies belong here.
