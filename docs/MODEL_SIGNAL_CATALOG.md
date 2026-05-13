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
```

The endpoints resolve `current_user` and enforce model-signal catalog access
through current plan entitlements. Free/public users should not receive model
strategy metadata. Enabled models are returned by default.

API responses intentionally expose only `artifact_path_setting` and a safe
relative/template `artifact_path_hint`; they must not expose resolved local
absolute paths, secrets, bucket credentials, or artifact contents.

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

## Guardrails

Catalog entries are research candidates, not investment advice. Do not claim
outperformance, future returns, or guaranteed signals in registry metadata,
docs, API copy, or future frontend UI.
