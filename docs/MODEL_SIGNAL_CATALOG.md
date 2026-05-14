# Model Signal Catalog

The model signal catalog is the backend-owned registry for onboarded
model-signal Strategy V2 candidates. It gives the API and future UI a safe
place to discover model metadata, recommended defaults, risk notes, supported
universes, and artifact configuration hints without hardcoding model details in
the frontend.

The catalog does not train models, run live inference, or store model signal
artifacts. Strategy execution still consumes point-in-time exported signal
files through `MODEL_SIGNAL_DATA_PATH` and the existing model signal artifact
loader.

## Registered Models

`linear_smooth10_margin002_v1` is the first registered model-signal candidate.

- Display name: `Linear Smooth 10 Margin 0.002`
- Research status: `paper_tracking`
- Ranking field: `score`
- Default selection: top 1 symbol with `signal_bucket_filter=["top"]`
- Label horizon: 20 trading days
- Feature set: `default_features_v1`
- Default fallback: cash
- Default benchmark: `SPY`
- Artifact setting: `MODEL_SIGNAL_DATA_PATH`

Risk notes are part of the registry response. The current entry calls out that
top-1 selection is concentrated, the model is for research and paper tracking
only, volatile contributors include XLE, IBIT, ARKK, SLV, and QQQ, and the
signal is not investment advice or guaranteed.

## API

Protected catalog endpoints:

```text
GET /model-signals/catalog
GET /model-signals/catalog/{model_version}
GET /model-signals/catalog/{model_version}/current
GET /strategies/{strategy_id}/current-signal
```

The endpoints resolve `current_user` and enforce model-signal catalog access
through current plan entitlements. Free/public users should not receive model
strategy metadata. Enabled models are returned by default.

API responses intentionally expose only `artifact_path_setting` and a safe
relative/template `artifact_path_hint`; they must not expose resolved local
absolute paths, secrets, bucket credentials, or artifact contents.

The current preview endpoint loads the configured signal artifact, filters to
the requested registered `model_version`, finds the latest available signal
date, applies the registry defaults, and returns a compact paper-tracking
preview. For `linear_smooth10_margin002_v1`, the runtime defaults are:

- `ranking_field=score`
- `top_n=1`
- `signal_bucket_filter=["top"]`

The response includes the latest signal date, selected symbols, selected row
fields such as `score`, `rank`, `predicted_return`, `confidence`, and
`signal_bucket` when present, row/symbol counts for the latest date, and
manifest status/warnings when a sibling `model_signal_manifest.json` exists.
The endpoint does not run model training, does not run live inference, and does
not expose local artifact paths.

Saved strategies use the strategy-specific current signal endpoint. Unlike the
catalog preview, it evaluates the saved `model_signal` config for the owned
strategy version: universe, ranking field, top N, bucket filter, confidence
floor, fallback, and optional `as_of_date`. This lets the backend answer the
current paper holding for a saved strategy before any UI tracking, scheduler,
notification, or channel work exists.

## Adding a Model After Research Export

After the ML research repository exports a candidate that satisfies
`docs/ML_RESEARCH_EXPORT_CONTRACT.md` and
`docs/MODEL_SIGNAL_INGESTION_CONTRACT.md`, add a registry entry with:

- `model_version`
- `display_name`
- `description`
- `family`
- `research_status`
- `supported_universe`
- `default_universe`
- `ranking_field` and allowed ranking fields
- `default_top_n`
- `default_signal_bucket_filter`
- `default_fallback`
- `default_benchmark`
- `label_horizon_days`
- `feature_set_version`
- `artifact_path_setting` or safe artifact path hint
- `risk_notes`
- `limitations`
- `recommended_use`
- `enabled`

Then add or update tests for catalog list/detail responses, entitlement
blocking, disabled model visibility, Strategy V2 config building, invalid input
rejection, and path leak prevention.

## Registry vs Artifacts

The registry is metadata and defaults. Artifacts are precomputed, point-in-time
signal files stored outside the repository and loaded at runtime when a
model-signal strategy is executed.

Do not commit signal artifacts, training data, trained model binaries, local
absolute paths, or private bucket URLs. The platform should only need the
artifact path setting at runtime and should validate artifacts before use.

Daily/latest artifacts exported by `US-Market-ML-Research` can be used locally
by pointing `MODEL_SIGNAL_DATA_PATH` at the export root or a specific signal
file. Example:

```bash
MODEL_SIGNAL_DATA_PATH=/path/to/US-Market-ML-Research/artifacts/model_signals_daily \
  uvicorn market_simulator.api.main:app --reload
```

Then call:

```text
GET /model-signals/catalog/linear_smooth10_margin002_v1/current
```

The known daily/latest export for this model was generated for
`latest_signal_date=2026-05-08` with `status=ready`, 162 merged rows, 27 symbols,
and top selected symbol `VUG`. Treat this as a research/paper-tracking preview,
not a live trading signal or investment advice.

## Guardrails

Catalog entries are research candidates, not investment advice. Do not claim
outperformance, future returns, or guaranteed signals in registry metadata,
docs, API copy, or future frontend UI.
