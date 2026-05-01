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
    assert "rule.symbol ?? options.tradableSymbol" in source


def test_strategy_draft_and_saved_config_use_shared_rule_summary_helper():
    draft_source = (
        ROOT / "frontend/src/components/strategy-chat/StrategyDraftCard.tsx"
    ).read_text()
    signal_logic_source = (ROOT / "frontend/src/pages/CreateStrategyPage.tsx").read_text()
    saved_version_source = (ROOT / "frontend/src/pages/StrategyPage.tsx").read_text()

    assert "from '../../lib/ruleSummaries'" in draft_source
    assert "tradableSymbol: config.tradable_symbol" in draft_source
    assert "summarizeRule(config.entry_rule" in signal_logic_source
    assert "summarizeRule(config.exit_rule" in signal_logic_source
    assert "summarizeStrategyRule(config.entry_rule" in saved_version_source
    assert "summarizeStrategyRule(config.exit_rule" in saved_version_source


def test_strategy_name_helper_knows_realized_volatility_rules():
    source = (ROOT / "frontend/src/lib/suggestStrategyName.ts").read_text()

    assert "'realized_volatility_below'" in source
    assert "'realized_volatility_above'" in source
    assert "realized volatility strategy" in source
