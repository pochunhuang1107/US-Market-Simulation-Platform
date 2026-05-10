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
from market_simulator.settings import get_settings


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
    holdoutRiskIds: module.filterStrategyGalleryTemplates(
      module.STRATEGY_GALLERY_TEMPLATES,
      { ...baseFilters, query: 'holdout' }
    ).map((template) => template.id),
    iwmSymbolIds: module.filterStrategyGalleryTemplates(
      module.STRATEGY_GALLERY_TEMPLATES,
      { ...baseFilters, symbol: 'IWM' }
    ).map((template) => template.id),
    vixOverlayIds: module.filterStrategyGalleryTemplates(
      module.STRATEGY_GALLERY_TEMPLATES,
      { ...baseFilters, style: 'Overlay', referenceSeriesUsage: 'VIX regime' }
    ).map((template) => template.id),
    sectorCategoryIds: module.filterStrategyGalleryTemplates(
      module.STRATEGY_GALLERY_TEMPLATES,
      { ...baseFilters, tagOrCategory: 'Sector overlay' }
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


def _collect_rule_symbols(rule: dict[str, Any] | None) -> set[str]:
    if not isinstance(rule, dict):
        return set()

    symbols = set()
    for key in ("symbol", "reference_symbol"):
        symbol = rule.get(key)
        if isinstance(symbol, str):
            symbols.add(symbol.upper())

    if isinstance(rule.get("rule"), dict):
        symbols.update(_collect_rule_symbols(rule["rule"]))

    rules = rule.get("rules")
    if isinstance(rules, list):
        for child in rules:
            symbols.update(_collect_rule_symbols(child))

    return symbols


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
        "qqq-core-vix-trend-overlay",
        "spy-core-vix-trend-overlay",
        "xlp-core-relative-strength-overlay",
        "xli-core-relative-strength-watchlist",
        "xlre-core-relative-strength-defensive",
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


def test_strategy_gallery_representative_templates_smoke_with_synthetic_data():
    templates = _load_gallery_templates()
    smoke_template_ids = [
        "qqq-core-rsi-starter",
        "xle-rsi-defensive-pullback",
        "qqq-core-vix-trend-overlay",
    ]

    for template_id in smoke_template_ids:
        config = _template_by_id(templates, template_id)["config"]
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
        config = template["config"]

        assert template["id"] not in seen_ids
        seen_ids.add(template["id"])

        assert isinstance(template["title"], str)
        assert template["title"].strip()
        assert isinstance(config["name"], str)
        assert config["name"].strip()
        assert isinstance(template["shortExplanation"], str)
        assert template["shortExplanation"].strip()
        assert isinstance(template["expectedBehavior"], str)
        assert template["expectedBehavior"].strip()
        assert isinstance(template["entryRuleText"], str)
        assert template["entryRuleText"].strip()
        assert isinstance(template["exitRuleText"], str)
        assert template["exitRuleText"].strip()
        assert isinstance(template["riskControls"], list)
        assert template["riskControls"]
        assert all(
            isinstance(control, str) and control.strip()
            for control in template["riskControls"]
        )
        assert isinstance(template["categoryLabel"], str)
        assert template["categoryLabel"].strip()
        assert isinstance(template["tags"], list)
        assert template["tags"]
        assert all(isinstance(tag, str) and tag.strip() for tag in template["tags"])
        assert len(template["tags"]) == len(
            {tag.strip().lower() for tag in template["tags"]}
        )
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

        serialized_config = json.dumps(config)
        for symbol in banned_reference_symbols:
            assert symbol not in serialized_config


def test_defensive_gallery_templates_are_clearly_labeled():
    defensive_terms = ("defensive", "risk-control", "risk control")

    for template in _load_gallery_templates():
        identifier_text = " ".join(
            [
                template["id"],
                template["title"],
                template["shortExplanation"],
            ]
        ).lower()
        label_text = " ".join(
            [
                template["categoryLabel"],
                template["strategyFamily"],
                template["expectedBehavior"],
                *template["tags"],
                *template["riskControls"],
            ]
        ).lower()

        if any(term in identifier_text for term in defensive_terms):
            assert any(term in label_text for term in defensive_terms)


def test_strategy_gallery_templates_use_supported_symbols():
    settings = get_settings()
    supported_symbols = set(settings.supported_etf_symbols)
    supported_references = set(settings.supported_reference_series_symbols)

    for template in _load_gallery_templates():
        config = template["config"]
        symbols = {
            config["tradable_symbol"],
            config["benchmark_symbol"],
            *config["reference_symbols"],
            *_collect_rule_symbols(config["entry_rule"]),
            *_collect_rule_symbols(config["exit_rule"]),
        }
        unsupported = sorted(
            symbol
            for symbol in symbols
            if symbol not in supported_symbols and symbol not in supported_references
        )
        assert unsupported == []


def test_strategy_gallery_filter_helpers_cover_search_and_filter_facets():
    probe = _run_gallery_helper_probe()

    assert "Mean reversion" in probe["options"]["styles"]
    assert "Lower" in probe["options"]["riskLevels"]
    assert "IWM" in probe["options"]["symbols"]
    assert "VIX regime" in probe["options"]["referenceSeriesUsages"]
    assert "Sector overlay" in probe["options"]["tagsAndCategories"]
    assert "iwm-rsi-defensive-pullback" in probe["iwmSymbolIds"]
    assert set(probe["holdoutRiskIds"]) >= {
        "xle-rsi-defensive-pullback",
        "qqq-core-vix-trend-overlay",
        "spy-core-rsi-starter",
    }
    assert set(probe["vixOverlayIds"]) >= {
        "qqq-core-vix-trend-overlay",
        "spy-core-vix-trend-overlay",
    }
    assert set(probe["sectorCategoryIds"]) >= {
        "xlp-core-relative-strength-overlay",
        "xli-core-relative-strength-watchlist",
        "xlre-core-relative-strength-defensive",
    }
    assert probe["activeFilters"] is True
    assert probe["emptyFilters"] is False

    qqq_vix_chips = probe["displayChipsById"]["qqq-core-vix-trend-overlay"]
    assert qqq_vix_chips == [
        "QQQ",
        "VIX",
        "Major ETF starter",
        "trend filter",
        "core sleeve",
    ]

    for chips in probe["displayChipsById"].values():
        normalized = [chip.lower() for chip in chips]
        assert len(normalized) == len(set(normalized))


def test_upgraded_gallery_templates_use_intentional_position_management():
    templates = _load_gallery_templates()

    xle = _template_by_id(templates, "xle-rsi-defensive-pullback")["config"]
    assert xle["allocation"]["max_position_pct"] == 0.75
    assert xle["risk"]["stop_loss_pct"] == 0.12
    assert xle["risk"]["cooldown_bars"] == 5
    assert xle["entry_rule"]["threshold"] == 45
    assert xle["exit_rule"]["threshold"] == 60
    assert xle["position_management"] == {
        "scale_in_fraction": 0.25,
        "exit_behavior": "sell_all",
        "profit_reduce_threshold": None,
        "max_scale_in_steps": 3,
        "min_bars_between_scale_ins": 3,
        "scale_in_requires_persistent_signal": True,
        "minimum_trade_notional": 500,
    }

    iwm = _template_by_id(templates, "iwm-rsi-defensive-pullback")["config"]
    assert iwm["tradable_symbol"] == "IWM"
    assert iwm["risk"]["stop_loss_pct"] == 0.08
    assert iwm["risk"]["cooldown_bars"] == 3
    assert iwm["entry_rule"]["threshold"] == 45
    assert iwm["exit_rule"]["threshold"] == 70
    assert iwm["position_management"]["exit_behavior"] == "sell_all"

    qqq_vix = _template_by_id(templates, "qqq-core-vix-trend-overlay")["config"]
    assert qqq_vix["reference_symbols"] == ["VIX"]
    assert qqq_vix["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.8,
    }
    assert qqq_vix["entry_rule"]["operator"] == "AND"
    assert qqq_vix["entry_rule"]["rules"][0]["type"] == "series_below"
    assert qqq_vix["entry_rule"]["rules"][0]["threshold"] == 30
    assert qqq_vix["entry_rule"]["rules"][1]["type"] == "sma_above"
    assert qqq_vix["entry_rule"]["rules"][1]["slow_window"] == 100
    assert qqq_vix["exit_rule"]["type"] == "sma_cross_below"
    assert qqq_vix["position_management"]["scale_in_fraction"] == 1.0
    assert qqq_vix["position_management"]["exit_behavior"] == "sell_all"

    qqq_core = _template_by_id(templates, "qqq-core-rsi-starter")["config"]
    assert qqq_core["core_overlay"] == {
        "enabled": True,
        "core_allocation_pct": 0.8,
    }
    assert qqq_core["entry_rule"]["threshold"] == 40
    assert qqq_core["exit_rule"]["threshold"] == 70
    assert qqq_core["position_management"] == {
        "scale_in_fraction": 0.5,
        "exit_behavior": "sell_all",
        "profit_reduce_threshold": None,
        "max_scale_in_steps": 2,
        "min_bars_between_scale_ins": 3,
        "scale_in_requires_persistent_signal": True,
        "minimum_trade_notional": 500,
    }

    xlp = _template_by_id(templates, "xlp-core-relative-strength-overlay")["config"]
    assert xlp["tradable_symbol"] == "XLP"
    assert xlp["benchmark_symbol"] == "SPY"
    assert xlp["reference_symbols"] == ["SPY"]
    assert xlp["core_overlay"]["core_allocation_pct"] == 0.5
    assert xlp["entry_rule"]["type"] == "relative_return_above"
    assert xlp["entry_rule"]["lookback"] == 30


def test_refreshed_gallery_templates_include_major_etfs_and_defensive_candidates():
    templates = _load_gallery_templates()
    ids = {template["id"] for template in templates}
    symbols = {symbol for template in templates for symbol in template["symbols"]}

    assert {"QQQ", "SPY", "XLE", "IWM", "XLV"} <= symbols
    assert {
        "xle-rsi-defensive-pullback",
        "iwm-rsi-defensive-pullback",
        "xlv-rsi-healthcare-risk-control",
    } <= ids


def test_gallery_templates_avoid_performance_promising_wording():
    banned_phrases = [
        "will outperform",
        "beats the market",
        "proven alpha",
        "guaranteed",
        "best strategy",
        "profitable signal",
        "will beat",
    ]

    for template in _load_gallery_templates():
        text = " ".join(
            [
                template["title"],
                template["shortExplanation"],
                template["expectedBehavior"],
                template["entryRuleText"],
                template["exitRuleText"],
                " ".join(template["tags"]),
            ]
        ).lower()
        assert "zero-trade" not in text
        assert "diagnostic" not in text
        for phrase in banned_phrases:
            assert phrase not in text


def test_builder_sample_prompt_sources_include_refreshed_examples():
    prompt_sources = "\n".join(
        [
            (ROOT / "frontend/src/components/strategy-chat/ExamplePromptChips.tsx").read_text(),
            (ROOT / "frontend/src/components/strategy-chat/ChatMessageList.tsx").read_text(),
        ]
    )

    expected_examples = [
        "Create an XLE RSI pullback strategy with RSI below 45",
        "Create an IWM RSI strategy that enters below 45",
        "Create a QQQ strategy with entry when VIX below 30",
        "Create a SPY strategy with entry when VIX below 30",
        "Create an XLV RSI risk-control strategy",
    ]
    for example in expected_examples:
        assert example in prompt_sources


def test_featured_strategy_ideas_use_refreshed_gallery_templates():
    source = (ROOT / "frontend/src/pages/StrategyChatPage.tsx").read_text()

    for template_id in [
        "xle-rsi-defensive-pullback",
        "iwm-rsi-defensive-pullback",
        "qqq-core-vix-trend-overlay",
    ]:
        assert template_id in source


def test_gallery_and_featured_template_imports_seed_workspace_draft_card_path():
    gallery_source = (ROOT / "frontend/src/pages/StrategyGalleryPage.tsx").read_text()
    workspace_source = (ROOT / "frontend/src/pages/StrategyChatPage.tsx").read_text()
    message_list_source = (
        ROOT / "frontend/src/components/strategy-chat/ChatMessageList.tsx"
    ).read_text()

    assert "function cloneConfig(config: StrategyV2TemplateConfig)" in gallery_source
    assert "source: 'strategy_gallery'" in gallery_source
    assert "sourceLabel: 'Strategy Gallery'" in gallery_source
    assert "sourceDraftConfig: cloneConfig(template.config)" in gallery_source
    assert "navigate('/workspace', {" in gallery_source

    assert "function handleUseGalleryTemplate(template: StrategyGalleryTemplate)" in workspace_source
    assert "sourceDraftConfig: JSON.parse(JSON.stringify(template.config))" in workspace_source
    assert "buildSeededDraftMessage({" in workspace_source
    assert "response_type: 'UPDATE_DRAFT'" in workspace_source
    assert "Loaded ${strategyName} as the current editing context." in workspace_source
    assert "<FeaturedStrategyIdeas onUseTemplate={handleUseGalleryTemplate} />" in workspace_source

    assert "isRunnableDraftMessage(message)" in message_list_source
    assert "isStrategyDraftMessage(message)" in message_list_source
    assert "<StrategyDraftCard" in message_list_source


def test_strategy_draft_actions_remain_stacked_not_side_by_side():
    source = (
        ROOT / "frontend/src/components/strategy-chat/StrategyDraftCard.tsx"
    ).read_text()

    assert "function StrategyDraftActions" in source
    assert 'className="flex flex-col items-start gap-3 lg:items-end"' in source
    assert "w-[6.75rem] whitespace-nowrap" in source
    assert "min-w-[8.75rem] whitespace-nowrap" in source
    assert "flex-row" not in source[source.index("function StrategyDraftActions"):source.index("export function StrategyDraftCard")]


def test_gallery_templates_do_not_include_duplicate_visible_tags_or_chips():
    probe = _run_gallery_helper_probe()
    templates = _load_gallery_templates()

    for template in templates:
        normalized_tags = [tag.lower() for tag in template["tags"]]
        assert len(normalized_tags) == len(set(normalized_tags))

    for chips in probe["displayChipsById"].values():
        normalized = [chip.lower() for chip in chips]
        assert len(normalized) == len(set(normalized))


def test_gallery_templates_do_not_mix_sell_all_with_visible_scale_out_fraction():
    templates = _load_gallery_templates()

    for template in templates:
        position_management = template["config"].get("position_management")
        if isinstance(position_management, dict) and position_management.get("exit_behavior") == "sell_all":
            assert "scale_out_fraction" not in position_management
