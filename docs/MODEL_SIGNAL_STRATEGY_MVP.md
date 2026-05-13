# Model-Signal Strategy MVP

Strategy V2 supports a backend-only MVP for deterministic model-signal-driven
ETF rotation. The platform consumes precomputed signal artifacts exported by
`pochunhuang1107/US-Market-ML-Research`; it does not train models, run live
inference, add notebooks, add sklearn/tensorflow dependencies, or call external
ML services.

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
model_signal_frame=...)`. The existing `ModelSignalRepository` and
`load_model_signal_frame(...)` support local CSV, JSON/JSONL, and parquet files.
Production S3 loading is intentionally left for a future integration using:

```text
curated/model_signals/model_version=<VERSION>/signals.parquet
```
