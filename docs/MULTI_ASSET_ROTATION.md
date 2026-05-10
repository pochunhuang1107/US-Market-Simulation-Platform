# Multi-Asset Rotation MVP

Strategy V2 supports an additive backend-only `rotation` block for deterministic ETF rotation strategies. When `rotation.enabled` is true, the engine ranks a universe of assets on scheduled rebalance dates and rebalances into the selected holdings instead of using the single-symbol entry/exit loop.

## Supported MVP Behavior

- Universe assets are loaded as market-data symbols.
- Ranking supports trailing `relative_return` momentum over a fixed lookback window.
- Rebalance supports `monthly`, `weekly`, and `quarterly` first-trading-day schedules.
- Selection supports `top_n`.
- Allocation supports equal weight with `max_position_pct`.
- Optional `risk_filter` uses the existing Strategy V2 rule tree.
- Fallback can move to `cash` or a configured fallback `asset`.
- Timeline, summary, trade log, yearly report, sleeve summary, and report bundles remain compatible. Rotation runs add fields such as `selected_assets`, `target_weights`, `asset_returns`, `asset_ranks`, `rebalance`, per-symbol holdings, and `cash`.

## Example Config

```json
{
  "schema_version": "2.0",
  "name": "QQQ SPY XLK TLT Monthly Momentum",
  "tradable_symbol": "QQQ",
  "benchmark_symbol": "SPY",
  "reference_symbols": ["SPY", "XLK", "TLT"],
  "start_date": "2018-01-02",
  "end_date": "2024-12-31",
  "initial_capital": 100000,
  "transaction_cost_bps": 5,
  "rotation": {
    "enabled": true,
    "universe": ["QQQ", "SPY", "XLK", "TLT"],
    "ranking": {
      "type": "relative_return",
      "lookback": 63,
      "descending": true
    },
    "rebalance": {
      "frequency": "monthly",
      "day": "first_trading_day"
    },
    "selection": {
      "top_n": 1
    },
    "allocation": {
      "weighting": "equal_weight",
      "max_position_pct": 1.0
    },
    "risk_filter": {
      "kind": "atomic",
      "type": "sma_above",
      "symbol": "SPY",
      "fast_window": 1,
      "slow_window": 200
    },
    "fallback": {
      "type": "asset",
      "symbol": "TLT"
    }
  }
}
```

## Limitations

- No LLM or ML ranking logic is included.
- No frontend-specific workflow has been added.
- Ranking uses close data available on the rebalance date and does not use future bars.
- The MVP uses whole-share rebalancing, so realized weights can differ slightly from targets.
- The engine does not promise future returns; results are deterministic historical simulations only.
