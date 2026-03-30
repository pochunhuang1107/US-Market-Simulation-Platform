from __future__ import annotations

import json
from pathlib import Path

from market_simulator.models.strategy_v1 import StrategyV1
from market_simulator.models.strategy_v2 import StrategyV2

def _convert_v1_to_v2(v1):
    return StrategyV2.model_validate({
        "schema_version": "2.0",
        "name": v1.name,
        "tradable_symbol": v1.symbol,
        "benchmark_symbol": v1.benchmark,
        "reference_symbols": [],
        "start_date": str(v1.start_date),
        "end_date": str(v1.end_date),
        "initial_capital": v1.initial_capital,
        "transaction_cost_bps": v1.transaction_cost_bps,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": v1.position_sizing.value,
            "max_position_pct": 1.0,
        },
        "entry_rule": {
            "kind": "atomic",
            "type": v1.entry.type,
            "symbol": v1.symbol,
            "lookback": v1.entry.lookback,
            "threshold": v1.entry.threshold,
        },
        "exit_rule": {
            "kind": "atomic",
            "type": v1.exit.type,
            "symbol": v1.symbol,
            "lookback": v1.exit.lookback,
            "threshold": v1.exit.threshold,
        },
        "risk": {
            "stop_loss_pct": v1.risk.stop_loss_pct,
            "take_profit_pct": v1.risk.take_profit_pct,
        },
    })

def load_any_strategy(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") == "2.0":
        return StrategyV2.model_validate(payload)
    return _convert_v1_to_v2(StrategyV1.model_validate(payload))
