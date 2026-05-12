# Reference-Series And Regime Filters

This checklist pins the beta behavior for reference-series data and regime-aware rules.

## Supported Reference Series

The default supported reference-series symbols are configured in `Settings.supported_reference_series_symbols`:

- `VIX`
- `VIX9D`
- `VXEEM`
- `DGS10`
- `DGS2`
- `T10Y2Y`
- `DFF`

Builder and draft validation must reject symbols outside the configured ETF universe and the configured reference-series universe. Do not make unsupported reference symbols pass silently.

## Data Boundaries

- Runtime market data must come from curated ETF daily prices and curated `reference_series`.
- Do not read raw or staging data in runtime paths or CI tests.
- CI tests should use synthetic/local parquet data and must not require S3 or AWS credentials.
- `REFERENCE_SERIES_METADATA_S3_URI` is readiness/coverage metadata. Strategy execution uses the curated reference-series rows loaded for the requested date range; missing or stale metadata must not fabricate market values.

## Alignment Convention

- Strategy evaluation is exact-date aligned to the tradable bar date.
- A reference value for tradable date `T` is used only when that same reference date `T` is present.
- Missing reference dates evaluate as unavailable and the atomic rule returns `False`.
- The engine does not forward-fill from future dates or backfill from earlier dates.
- Indicator rules on reference assets or series use only rows at or before the matched row position in that same dataframe.

## Missing Data Behavior

- Reference data starting after ETF data: rules are `False` until the first same-date reference row exists.
- Holidays or isolated missing reference dates: rules are `False` on those tradable dates.
- Missing `value`: `series_below` and `series_above` use `close` when present; if both are unavailable, the rule is `False`.
- Missing configured symbol/path: repository loading raises a controlled `ValueError`.
- Missing reference metadata: readiness may warn elsewhere, but execution does not infer values from metadata.

## Artifact Expectations

- Normal strategy timelines should include symbol-qualified signal columns when applicable, for example `VIX_value`, `SPY_SMA_100`, or `SPY_realized_volatility_20`.
- `trade_signal_snapshots` should preserve actual signal values, thresholds, operators, and match status for trade-triggering rules.
- Rotation timelines include `risk_filter_passed`, `fallback_used`, `asset_returns`, `asset_ranks`, and `risk_filter_signals`.
- Rotation trade snapshots include ranking context plus risk-filter signal actuals when a risk filter exists.

## Adding A New Reference Series

1. Add the symbol to the configured supported reference-series set.
2. Add curated `reference_series/symbol=<SYMBOL>/...` data with stable `date`, `symbol`, and either `value` or `close`.
3. Update builder/parser labels and docs only after curated data exists.
4. Add synthetic no-lookahead and missing-date tests for `series_below`/`series_above`.
5. Add artifact assertions for timeline/snapshot actual values.
