from __future__ import annotations

from fastapi import APIRouter, Depends

from market_simulator.api.deps import get_current_user
from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderGenerateRequest,
    StrategyBuilderGenerateResponse,
)
from market_simulator.models.strategy_v2 import StrategyV2

router = APIRouter(prefix="/strategy-builder", tags=["strategy-builder"])


def _generate_strategy_draft(req: StrategyBuilderGenerateRequest) -> tuple[dict, str, list[str], list[str]]:
    """
    MVP draft generator.

    This is intentionally a deterministic/mock generation boundary so we can
    replace it later with a real LLM-backed implementation without changing
    the API contract used by the frontend.
    """
    prompt = req.prompt.strip()
    prompt_lower = prompt.lower()

    warnings: list[str] = []
    assumptions: list[str] = []

    tradable_symbol = "QQQ"
    benchmark_symbol = "QQQ"

    for symbol in ["SPY", "QQQ", "DIA", "IWM", "VTI", "GLD", "TLT", "XLF", "XLK"]:
        if symbol.lower() in prompt_lower:
            tradable_symbol = symbol
            benchmark_symbol = symbol
            break

    if "mean reversion" in prompt_lower:
        entry_rule = {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 30,
        }
        exit_rule = {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 70,
        }
        summary = (
            f"Drafted a mean-reversion strategy for {tradable_symbol}: "
            f"enter when RSI(14) drops below 30 and exit when RSI(14) rises above 70."
        )
        assumptions.append("Interpreted the prompt as an RSI-based mean-reversion strategy.")
    elif "moving average" in prompt_lower or "sma" in prompt_lower:
        entry_rule = {
            "kind": "atomic",
            "type": "sma_cross_above",
            "symbol": tradable_symbol,
            "fast_window": 20,
            "slow_window": 50,
        }
        exit_rule = {
            "kind": "atomic",
            "type": "sma_cross_below",
            "symbol": tradable_symbol,
            "fast_window": 20,
            "slow_window": 50,
        }
        summary = (
            f"Drafted a trend-following strategy for {tradable_symbol}: "
            f"enter on 20/50 SMA bullish crossover and exit on bearish crossover."
        )
        assumptions.append("Used 20/50 SMA as the default moving-average pair.")
    else:
        entry_rule = {
            "kind": "atomic",
            "type": "rsi_below",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 30,
        }
        exit_rule = {
            "kind": "atomic",
            "type": "rsi_above",
            "symbol": tradable_symbol,
            "lookback": 14,
            "threshold": 70,
        }
        summary = (
            f"Drafted a default RSI strategy for {tradable_symbol}: "
            f"enter when RSI(14) is below 30 and exit when RSI(14) is above 70."
        )
        warnings.append("Prompt was interpreted using the default RSI template.")
        assumptions.append("Used QQQ unless a supported symbol was explicitly mentioned.")
        assumptions.append("Used the same symbol as the benchmark by default.")

    config = {
        "schema_version": "2.0",
        "name": f"{tradable_symbol.lower()}-draft-strategy",
        "tradable_symbol": tradable_symbol,
        "benchmark_symbol": benchmark_symbol,
        "reference_symbols": [],
        "start_date": "2018-01-02",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "transaction_cost_bps": 5,
        "allocation": {
            "entry_mode": "percent_of_equity",
            "entry_value": 1.0,
            "max_position_pct": 1.0,
        },
        "entry_rule": entry_rule,
        "exit_rule": exit_rule,
        "risk": {
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "partial_take_profit": None,
            "cooldown_bars": 0,
        },
        "core_overlay": {
            "enabled": False,
            "core_allocation_pct": 0.0,
        },
        "position_management": None,
    }

    validated = StrategyV2.model_validate(config)

    return validated.model_dump(mode="json"), summary, warnings, assumptions


@router.post("/generate", response_model=StrategyBuilderGenerateResponse)
def generate_strategy_draft_api(
    req: StrategyBuilderGenerateRequest,
    user=Depends(get_current_user),
):
    _ = user

    config, summary, warnings, assumptions = _generate_strategy_draft(req)

    return StrategyBuilderGenerateResponse(
        config=config,
        summary=summary,
        warnings=warnings,
        assumptions=assumptions,
    )