from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from market_simulator.api.schemas.runs import CreateRunRequest
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.services.draft_validation import validate_draft_config


ROOT = Path(__file__).resolve().parents[2]


def _load_gallery_templates() -> list[dict[str, Any]]:
    script = """
import('jiti').then(({ createJiti }) => {
  const jiti = createJiti(process.cwd() + '/');
  const module = jiti('./src/lib/strategyGalleryTemplates.ts');
  console.log(JSON.stringify(module.STRATEGY_GALLERY_TEMPLATES));
});
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT / "frontend",
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _template_by_id(templates: list[dict[str, Any]], template_id: str) -> dict[str, Any]:
    return next(template for template in templates if template["id"] == template_id)


def test_strategy_gallery_templates_validate_and_build_run_payloads():
    templates = _load_gallery_templates()
    assert len(templates) == 6

    for template in templates:
        config = template["config"]
        StrategyV2.model_validate(config)
        validate_draft_config(config=config, max_backtest_years=5)
        CreateRunRequest.model_validate(
            {
                "draft_config": config,
                "run_type": "SIMULATION",
                "executor_type": "SIMULATION_EXECUTOR",
                "request_payload": {
                    "source": "strategy_gallery",
                    "template_id": template["id"],
                    "template_title": template["title"],
                },
                "max_attempts": 1,
            }
        )


def test_upgraded_gallery_templates_use_intentional_position_management():
    templates = _load_gallery_templates()

    rsi = _template_by_id(templates, "qqq-rsi-mean-reversion")["config"]
    assert rsi["entry_rule"]["threshold"] == 35
    assert rsi["exit_rule"]["threshold"] == 65
    assert rsi["position_management"] == {
        "scale_in_fraction": 0.25,
        "exit_behavior": "sell_all",
        "profit_reduce_threshold": None,
        "max_scale_in_steps": 4,
        "min_bars_between_scale_ins": 3,
        "scale_in_requires_persistent_signal": True,
        "minimum_trade_notional": 500,
    }

    vix = _template_by_id(templates, "qqq-vix-risk-on-risk-off")["config"]
    assert vix["reference_symbols"] == ["VIX"]
    assert vix["entry_rule"]["operator"] == "AND"
    assert vix["entry_rule"]["rules"][0]["type"] == "series_below"
    assert vix["entry_rule"]["rules"][1]["type"] == "rsi_below"
    assert vix["position_management"]["scale_in_fraction"] == 0.25
    assert vix["position_management"]["max_scale_in_steps"] == 3
    assert vix["position_management"]["exit_behavior"] == "sell_all"
    assert vix["position_management"]["minimum_trade_notional"] == 500

    overlay = _template_by_id(templates, "qqq-core-vix-overlay")["config"]
    assert overlay["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.6,
    }
    assert overlay["position_management"]["scale_in_fraction"] == 1.0
    assert overlay["position_management"]["max_scale_in_steps"] == 1
    assert overlay["position_management"]["exit_behavior"] == "sell_all"

    trend = _template_by_id(templates, "spy-moving-average-trend-filter")["config"]
    assert trend["position_management"]["scale_in_fraction"] == 1.0
    assert trend["position_management"]["max_scale_in_steps"] == 1
    assert trend["position_management"]["exit_behavior"] == "sell_all"


def test_gallery_templates_do_not_mix_sell_all_with_visible_scale_out_fraction():
    templates = _load_gallery_templates()

    for template in templates:
        position_management = template["config"].get("position_management")
        if isinstance(position_management, dict) and position_management.get("exit_behavior") == "sell_all":
            assert "scale_out_fraction" not in position_management

