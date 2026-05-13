# linear_smooth10_margin002_v1 Local Run

This is the first platform-side Strategy V2 candidate for the exported ML
signal artifact `linear_smooth10_margin002_v1`. The platform consumes the
precomputed signal artifact only. Do not add model training, live inference, or
ML runtime dependencies here.

## Private Environment

Keep the artifact path in a private `.env` or shell session. Do not commit it.

```bash
# .env
MODEL_SIGNAL_DATA_PATH=<absolute-path-to-ml-research-repo>/artifacts/model_signals/model_version=linear_smooth10_margin002_v1/signals.parquet
```

For a shell-only run, set the same value before invoking the CLI:

```bash
ML_RESEARCH_REPO="$HOME/Projects/Research/US-Market-ML-Research"
MODEL_SIGNAL_DATA_PATH="$ML_RESEARCH_REPO/artifacts/model_signals/model_version=linear_smooth10_margin002_v1/signals.parquet"
```

If your ML research checkout lives elsewhere, set `ML_RESEARCH_REPO` to that
local path.

## Validate The Export

```bash
python scripts/validate_model_signal_export.py \
  --path "$MODEL_SIGNAL_DATA_PATH" \
  --model-version linear_smooth10_margin002_v1
```

Expected validation characteristics:

- `rows: 9126`
- `date_min: 2025-01-02`
- `date_max: 2026-05-08`
- `model_versions: linear_smooth10_margin002_v1`
- `duplicate_count: 0`

## Run The Strategy Locally

The local-only example config is:

```text
docs/examples/linear_smooth10_margin002_v1.strategy-v2.local.example.json
```

Run it with the existing Strategy V2 CLI after your private `.env` has
`MODEL_SIGNAL_DATA_PATH` and `MARKET_DATA_PATH` configured:

```bash
python scripts/run_simulation.py \
  --strategy docs/examples/linear_smooth10_margin002_v1.strategy-v2.local.example.json
```

If you are using shell variables instead of `.env`, prefix the same command with
`MODEL_SIGNAL_DATA_PATH="$MODEL_SIGNAL_DATA_PATH"`.

The candidate uses `score` as the ranking field, selects `top_n: 1`, and filters
to `signal_bucket_filter: ["top"]`. Generated run artifacts are written under
the local artifacts directory and should not be committed.
