# Strategy Discovery Harness

Use the discovery harness to screen Strategy V2 candidates before deciding whether
any belong in the Gallery. It is research tooling only; it does not update Gallery
templates or landing-page copy.

## Run It

```bash
python scripts/discover_gallery_candidates.py
```

Search modes:

- `smoke`: tiny fast run for CLI checks and development
- `standard`: bounded default search across the main supported families
- `broad`: larger local research search across wider ETF, risk, VIX, trend, sector, and rotation grids
- `refine`: reads promising configs from a JSON file when `--refine-input` is supplied and tries nearby risk-control variants

By default the script reads the same market data settings as the backend:

- `MARKET_DATA_PATH`
- `REFERENCE_SERIES_DATA_PATH`
- `SUPPORTED_DATA_START_DATE`
- `SUPPORTED_DATA_END_DATE`
- `SUPPORTED_ETF_SYMBOLS`
- `SUPPORTED_REFERENCE_SERIES_SYMBOLS`

Useful options:

```bash
python scripts/discover_gallery_candidates.py \
  --mode broad \
  --start-date 2018-01-02 \
  --end-date 2026-05-05 \
  --output-dir data/discovery_reports \
  --cache-dir data/discovery_reports/cache \
  --resume \
  --run-id latest \
  --families trend_pullback,core_rsi_overlay \
  --top-n 25
```

For a quick smoke run against configured data:

```bash
python scripts/discover_gallery_candidates.py --mode smoke --max-candidates 5
```

For resumable broad runs, start with a bounded slice and then increase the cap:

```bash
python scripts/discover_gallery_candidates.py --mode broad --max-candidates 3000 --resume
python scripts/discover_gallery_candidates.py --mode broad --max-candidates 10000 --resume --top-n 50
```

With `--resume`, cache hits count toward `--max-candidates` but are skipped
instead of re-executed. If `--max-candidates` is omitted, the script selects all
deterministically generated candidates after family filtering and de-duplication.
The cache key uses canonical Strategy V2 JSON plus the evaluation window and
split/benchmark policy, so changing the config or date window produces a new key.

The CLI prints available family names at the end of each run. If `--families`
does not match any generated candidates, the report metadata includes
`available_families` and `unmatched_families`.

Current generated families include:

- `asset_rotation_momentum`
- `core_rsi_overlay`
- `core_vix_trend_overlay`
- `defensive_relative_strength`
- `defensive_rotation_momentum`
- `defensive_trend_filtered_pullback`
- `realized_volatility_filter`
- `rsi_mean_reversion`
- `rsi_vix_regime_filter`
- `sector_core_relative_strength`
- `sector_relative_strength`
- `sector_rotation_momentum`
- `sma_trend_filter`
- `trend_pullback`
- `vix_risk_on_off`
- `vix_trend_filter`

## Outputs

Reports are written under `data/discovery_reports/`, which is gitignored:

- `candidate_summary.csv`: ranked table for spreadsheet review
- `candidate_summary.json`: ranked results, split-period metrics, configs, and failures
- `gallery_ready_outperformance.csv` / `.json`: candidates with positive alpha versus the traded ETF buy-and-hold screen
- `gallery_ready_defensive.csv` / `.json`: candidates labeled as risk-improvement candidates because they materially improve drawdown
- `watchlist_candidates.csv` / `.json`: near misses or risk-improvement candidates for manual review
- `failed_candidates.csv` / `.json`: successful runs that did not meet either screen
- `top_by_alpha_vs_tradable.csv`: best rows by alpha versus traded ETF buy-and-hold, whether or not they are Gallery-ready
- `top_by_drawdown_improvement.csv`: best rows by drawdown improvement versus traded ETF buy-and-hold
- `top_by_recent_alpha.csv`: best holdout-period rows by alpha versus traded ETF buy-and-hold
- `top_by_primary_alpha.csv`: best rows by the scoring benchmark used for the candidate type
- `candidate_configs/top_*.json`: Gallery-ready and watchlist Strategy V2 configs for manual inspection

Per-candidate resume cache files are written under `data/discovery_reports/cache/`
by default, or the directory passed to `--cache-dir`. Corrupt or incompatible
cache files are ignored with a warning and recomputed.

The discovery loader also keeps an in-process market-data cache while a run is
active. Identical `(tradable_symbol, sorted reference_symbols, start_date,
end_date)` bundles are reused across candidates, and single-symbol buy-and-hold
frames are cached separately. Console output and `candidate_summary.json`
include:

- `bundle_cache_hits`
- `bundle_cache_misses`
- `symbol_frame_cache_hits`
- `symbol_frame_cache_misses`

## Metrics

- `strategy_return_pct`: full-period strategy return
- `tradable_buy_hold_return_pct`: buy-and-hold return for the traded ETF
- `alpha_vs_tradable_buy_hold_pct`: strategy return minus traded ETF buy-and-hold return
- `market_benchmark_symbol`: broader comparison benchmark, commonly `SPY` for sector tests
- `market_benchmark_return_pct`: buy-and-hold return for the market benchmark when available
- `alpha_vs_market_benchmark_pct`: strategy return minus market benchmark return when available
- `cagr_pct`: annualized strategy return
- `max_drawdown_pct`: worst strategy equity drawdown during the period
- `tradable_buy_hold_max_drawdown_pct`: worst drawdown for the traded ETF buy-and-hold path
- `drawdown_delta_vs_tradable_buy_hold_pct`: strategy drawdown minus traded ETF drawdown; positive values mean the strategy drew down less
- `universe_equal_weight_buy_hold_return_pct`: for rotation candidates, equal-weight buy-and-hold return across the rotation universe
- `universe_equal_weight_buy_hold_max_drawdown_pct`: for rotation candidates, worst drawdown of the equal-weight universe path
- `alpha_vs_universe_equal_weight_pct`: for rotation candidates, strategy return minus equal-weight universe return
- `drawdown_delta_vs_universe_equal_weight_pct`: for rotation candidates, strategy drawdown minus equal-weight universe drawdown; positive values mean the strategy drew down less
- `primary_alpha_pct`: alpha metric used by discovery scoring; rotation candidates use universe equal-weight first, while non-rotation candidates use traded ETF buy-and-hold
- `benchmark_comparison_basis`: the benchmark family used as the primary scoring basis
- `rebalance_count`: for rotation candidates, count of scheduled rebalance rows considered for activity reasonableness
- `trade_count`: count of full exits reported by the engine
- `sharpe_ratio`: annualized Sharpe from daily strategy equity changes

The script also evaluates an earlier split and a recent holdout split. The flags
are sanity checks, not proof of robustness:

- `candidate_category`
- `gallery_ready_outperformance`
- `gallery_ready_defensive`
- `gallery_ready`
- `watchlist`
- `full_period_outperforms`
- `earlier_period_outperforms`
- `recent_period_outperforms`
- `drawdown_improvement_vs_benchmark`
- `enough_trades`
- `not_too_many_trades`
- `alpha_positive`
- `recent_alpha_positive`
- `train_alpha_vs_tradable_buy_hold_pct`
- `holdout_alpha_vs_tradable_buy_hold_pct`
- `train_alpha_vs_universe_equal_weight_pct`
- `holdout_alpha_vs_universe_equal_weight_pct`
- `train_primary_alpha_pct`
- `holdout_primary_alpha_pct`
- `train_pass`
- `holdout_pass`
- `stability_flag`
- `max_drawdown_acceptable`
- `trade_count_reasonable`
- `basic_sanity_pass`

If no candidates pass the stricter screen, the CLI prints
`No Gallery-ready candidates found.` Weak candidates are shown only as watchlist
or least-bad failed rows, not as recommendations.

Non-rotation outperformance candidates are screened against the traded ETF
buy-and-hold path. Rotation candidates are screened against the universe
equal-weight path and market benchmark metrics, so a placeholder
`tradable_symbol` does not dominate the decision. Defensive candidates may
underperform buy-and-hold on total return, but must be clearly labeled and
materially improve drawdown.

## Review Workflow

1. Run the discovery script against the intended local or S3 data window.
2. Review `gallery_ready_outperformance.csv` first, then `gallery_ready_defensive.csv`, then `watchlist_candidates.csv`.
3. Inspect drawdown, trade count, and the JSON config before considering Gallery inclusion.
4. Re-run promising configs manually through normal simulation flows before adding templates.

Historical outperformance is not a promise of future returns. These reports are a
screen for historically interesting candidates, and they can still reflect regime
luck, data quirks, or parameter overfit.
