from pathlib import Path
from market_simulator.strategy.compat import load_any_strategy

def test_load_v1_compatible():
    strategy = load_any_strategy(Path("data/sample_strategies/qqq_simple_compatible.json"))
    assert strategy.schema_version == "2.0"
    assert strategy.tradable_symbol == "QQQ"
