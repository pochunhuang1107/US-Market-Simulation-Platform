from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from market_simulator.api.schemas.runs import CreateRunRequest
from market_simulator.data.repository import MarketDataBundle
from market_simulator.engine.runner import run_simulation
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


def _run_gallery_helper_probe() -> dict[str, Any]:
    script = """
import('jiti').then(({ createJiti }) => {
  const jiti = createJiti(process.cwd() + '/');
  const module = jiti('./src/lib/strategyGalleryTemplates.ts');
  const baseFilters = module.EMPTY_STRATEGY_GALLERY_FILTERS;
  const probe = {
    options: module.getStrategyGalleryFilterOptions(module.STRATEGY_GALLERY_TEMPLATES),
    displayChipsById: Object.fromEntries(
      module.STRATEGY_GALLERY_TEMPLATES.map((template) => [
        template.id,
        module.getStrategyGalleryDisplayChips(template),
      ])
    ),
    strictRiskIds: module.filterStrategyGalleryTemplates(
      module.STRATEGY_GALLERY_TEMPLATES,
      { ...baseFilters, query: 'stricter' }
    ).map((template) => template.id),
    defensiveSymbolIds: module.filterStrategyGalleryTemplates(
      module.STRATEGY_GALLERY_TEMPLATES,
      { ...baseFilters, symbol: 'IEF' }
    ).map((template) => template.id),
    vixOverlayIds: module.filterStrategyGalleryTemplates(
      module.STRATEGY_GALLERY_TEMPLATES,
      { ...baseFilters, style: 'Overlay', referenceSeriesUsage: 'VIX regime' }
    ).map((template) => template.id),
    sectorCategoryIds: module.filterStrategyGalleryTemplates(
      module.STRATEGY_GALLERY_TEMPLATES,
      { ...baseFilters, tagOrCategory: 'Sector rotation' }
    ).map((template) => template.id),
    activeFilters: module.hasActiveStrategyGalleryFilters({ ...baseFilters, riskLevel: 'Lower' }),
    emptyFilters: module.hasActiveStrategyGalleryFilters(baseFilters),
  };
  console.log(JSON.stringify(probe));
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


def _synthetic_bars(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    dates = pd.date_range(start_date, end_date, freq="B")
    closes = [
        100.0 + (index * 0.04) + ((index % 23) - 11) * 0.15
        for index in range(len(dates))
    ]
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": [symbol] * len(dates),
            "open": [close - 0.2 for close in closes],
            "high": [close + 0.7 for close in closes],
            "low": [close - 0.7 for close in closes],
            "close": closes,
            "volume": [1_000_000.0] * len(dates),
            "vwap": closes,
            "transactions": [10_000.0] * len(dates),
        }
    )


def _synthetic_reference_series(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    dates = pd.date_range(start_date, end_date, freq="B")
    values = [24.0 + ((index % 40) - 20) * 0.45 for index in range(len(dates))]
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": [symbol] * len(dates),
            "value": values,
            "close": values,
        }
    )


def test_strategy_gallery_templates_validate_and_build_run_payloads():
    templates = _load_gallery_templates()
    assert len(templates) >= 10

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


def test_strategy_gallery_reference_templates_remain_runnable_with_synthetic_data():
    templates = _load_gallery_templates()
    reference_templates = [
        template for template in templates if template["config"]["reference_symbols"]
    ]

    assert {template["id"] for template in reference_templates} >= {
        "qqq-vix-risk-on-risk-off",
        "qqq-core-vix-overlay",
        "xlk-sector-relative-strength",
        "qqq-tlt-defensive-relative-strength",
        "spy-vix-rsi-regime-pullback",
        "spy-core-defensive-vix-overlay",
        "xlu-defensive-sector-relative-strength",
        "qqq-ief-trend-filtered-pullback",
    }

    for template in reference_templates:
        config = template["config"]
        strategy = StrategyV2.model_validate(config)
        references = {}
        for symbol in config["reference_symbols"]:
            if symbol == "VIX":
                references[symbol] = _synthetic_reference_series(
                    symbol,
                    config["start_date"],
                    config["end_date"],
                )
            else:
                references[symbol] = _synthetic_bars(
                    symbol,
                    config["start_date"],
                    config["end_date"],
                )

        result = run_simulation(
            MarketDataBundle(
                tradable=_synthetic_bars(
                    config["tradable_symbol"],
                    config["start_date"],
                    config["end_date"],
                ),
                references=references,
            ),
            strategy,
        )

        assert len(result.timeline) > 0
        assert result.summary["initial_capital"] == config["initial_capital"]


def test_strategy_gallery_templates_include_discovery_metadata():
    templates = _load_gallery_templates()
    banned_reference_symbols = {"DGS10", "DGS2", "T10Y2Y", "DFF", "VIX9D", "VXEEM"}

    seen_ids: set[str] = set()
    for template in templates:
        assert template["id"] not in seen_ids
        seen_ids.add(template["id"])

        assert isinstance(template["categoryLabel"], str)
        assert template["categoryLabel"].strip()
        assert isinstance(template["tags"], list)
        assert template["tags"]
        assert all(isinstance(tag, str) and tag.strip() for tag in template["tags"])
        assert isinstance(template["strategyFamily"], str)
        assert template["strategyFamily"].strip()
        assert template["referenceSeriesUsage"] in {
            "None",
            "VIX regime",
            "ETF relative strength",
            "ETF trend filter",
        }
        assert template["style"]
        assert template["riskLevel"]
        assert template["symbols"]
        assert template["shortExplanation"]
        assert template["expectedBehavior"]

        serialized_config = json.dumps(template["config"])
        for symbol in banned_reference_symbols:
            assert symbol not in serialized_config


def test_strategy_gallery_filter_helpers_cover_search_and_filter_facets():
    probe = _run_gallery_helper_probe()

    assert "Mean reversion" in probe["options"]["styles"]
    assert "Lower" in probe["options"]["riskLevels"]
    assert "IEF" in probe["options"]["symbols"]
    assert "ETF trend filter" in probe["options"]["referenceSeriesUsages"]
    assert "Sector rotation" in probe["options"]["tagsAndCategories"]
    assert "qqq-ief-trend-filtered-pullback" in probe["defensiveSymbolIds"]
    assert "spy-rsi-strict-pullback" in probe["strictRiskIds"]
    assert set(probe["vixOverlayIds"]) >= {
        "qqq-core-vix-overlay",
        "spy-core-defensive-vix-overlay",
    }
    assert set(probe["sectorCategoryIds"]) >= {
        "xlk-sector-relative-strength",
        "xlu-defensive-sector-relative-strength",
    }
    assert probe["activeFilters"] is True
    assert probe["emptyFilters"] is False

    qqq_vix_chips = probe["displayChipsById"]["qqq-vix-risk-on-risk-off"]
    assert qqq_vix_chips == ["QQQ", "VIX", "Volatility regime", "RSI", "risk filter"]

    for chips in probe["displayChipsById"].values():
        normalized = [chip.lower() for chip in chips]
        assert len(normalized) == len(set(normalized))


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

    strict = _template_by_id(templates, "spy-rsi-strict-pullback")["config"]
    assert strict["risk"]["stop_loss_pct"] == 0.06
    assert strict["risk"]["cooldown_bars"] == 2
    assert strict["position_management"]["scale_in_fraction"] == 0.2
    assert strict["position_management"]["max_scale_in_steps"] == 3
    assert strict["position_management"]["exit_behavior"] == "sell_all"

    defensive = _template_by_id(templates, "qqq-ief-trend-filtered-pullback")["config"]
    assert defensive["reference_symbols"] == ["IEF"]
    assert defensive["entry_rule"]["rules"][1]["type"] == "sma_above"
    assert defensive["entry_rule"]["rules"][1]["symbol"] == "IEF"
    assert defensive["exit_rule"]["rules"][1]["type"] == "sma_cross_below"
    assert defensive["position_management"]["exit_behavior"] == "sell_all"


def test_gallery_templates_do_not_mix_sell_all_with_visible_scale_out_fraction():
    templates = _load_gallery_templates()

    for template in templates:
        position_management = template["config"].get("position_management")
        if isinstance(position_management, dict) and position_management.get("exit_behavior") == "sell_all":
            assert "scale_out_fraction" not in position_management
