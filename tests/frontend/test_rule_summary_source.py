from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_shared_rule_summary_helper_has_readable_relative_return_copy():
    source = (ROOT / "frontend/src/lib/ruleSummaries.ts").read_text()

    assert "outperforms ${referenceSymbol} by more than" in source
    assert "over ${lookback} trading days" in source
    assert "no longer outperforms ${referenceSymbol}" in source
    assert "${lookback}-day realized volatility is ${direction} ${formatPercent(rule.threshold)}" in source
    assert "case 'realized_volatility_below'" in source
    assert "case 'realized_volatility_above'" in source
    assert "case 'bullish_candle'" in source
    assert "case 'close_below_previous_low'" in source
    assert "closes in the top ${formatCompactPercent(threshold ?? 0.2)} of the day's range" in source
    assert "closes in the bottom ${formatCompactPercent(threshold ?? 0.2)} of the day's range" in source
    assert "rule.symbol ?? options.tradableSymbol" in source
    assert "price is no longer above its ${slowWindow}-day SMA" in source


def test_strategy_draft_and_saved_config_use_shared_rule_summary_helper():
    draft_source = (
        ROOT / "frontend/src/components/strategy-chat/StrategyDraftCard.tsx"
    ).read_text()
    signal_logic_source = (ROOT / "frontend/src/pages/CreateStrategyPage.tsx").read_text()
    saved_version_source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()

    assert "from '../../lib/ruleSummaries'" in draft_source
    assert "tradableSymbol: config.tradable_symbol" in draft_source
    assert "whitespace-nowrap" in draft_source
    assert "min-w-[8.75rem]" in draft_source
    assert "summarizeRule(config.entry_rule" in signal_logic_source
    assert "summarizeRule(config.exit_rule" in signal_logic_source
    assert "summarizeStrategyRule(config.entry_rule" in saved_version_source
    assert "summarizeStrategyRule(config.exit_rule" in saved_version_source


def test_strategy_behavior_summary_helper_keeps_position_copy_compact():
    helper_source = (ROOT / "frontend/src/lib/strategyBehaviorSummary.ts").read_text()
    draft_source = (
        ROOT / "frontend/src/components/strategy-chat/StrategyDraftCard.tsx"
    ).read_text()
    gallery_source = (ROOT / "frontend/src/pages/StrategyGalleryPage.tsx").read_text()
    saved_version_source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()
    run_create_source = (ROOT / "frontend/src/pages/CreateSimulationPage.tsx").read_text()

    assert "getStrategyBehaviorFields" in helper_source
    assert "Entry sizing" in helper_source
    assert "`${formatPercent(scaleInFraction)} per entry`" in helper_source
    assert "Max entries" in helper_source
    assert "Wait between adds" in helper_source
    assert "`${minBarsBetweenAdds} bars`" in helper_source
    assert "Requires persistent signal" in helper_source
    assert "Sell all" in helper_source
    assert "Scale out ${formatPercent(scaleOutFraction)} at a time" in helper_source
    assert "scale_out_fraction" not in helper_source.split("positionManagement?.exit_behavior === 'sell_all'")[1].split("} else if")[0]
    assert "Entry allocation" in helper_source
    assert "field.label === 'Entry sizing'" in saved_version_source

    for source in [draft_source, gallery_source, saved_version_source, run_create_source]:
        assert "getStrategyBehaviorFields" in source


def test_strategy_name_helper_knows_realized_volatility_rules():
    source = (ROOT / "frontend/src/lib/suggestStrategyName.ts").read_text()

    assert "'realized_volatility_below'" in source
    assert "'realized_volatility_above'" in source
    assert "'close_near_high'" in source
    assert "daily price-action strategy" in source
    assert "realized volatility strategy" in source
    assert "getReferenceTrendFilterSymbol" in source
    assert "RSI with ${referenceTrendFilterSymbol} trend filter" in source


def test_sweep_helpers_use_contextual_parameter_labels_and_trade_activity_copy():
    helper_source = (ROOT / "frontend/src/lib/sweepVariants.ts").read_text()
    draft_card_source = (
        ROOT / "frontend/src/components/strategy-chat/ParameterSweepDraftCard.tsx"
    ).read_text()
    results_source = (
        ROOT / "frontend/src/components/run-detail/ParameterSweepResults.tsx"
    ).read_text()
    variant_source = (ROOT / "frontend/src/pages/SweepVariantDetailPage.tsx").read_text()

    assert "VIX add threshold" in helper_source
    assert "VIX reduce threshold" in helper_source
    assert "${side} RSI threshold" in helper_source
    assert "formatParameterLabel(path, baseConfig)" in draft_card_source
    assert "formatTradeActivity(row)" in results_source
    assert "<th className=\"px-4 py-3\">Activity</th>" in results_source
    assert "formatParameterLabel(path, config)" in variant_source
    assert "label: 'Trades'" in variant_source
