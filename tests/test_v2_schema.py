from pathlib import Path
from market_simulator.strategy.compat import load_any_strategy

def test_load_v2():
    strategy = load_any_strategy(Path("data/sample_strategies/qqq_engine_v2.json"))
    assert strategy.schema_version == "2.0"
    assert strategy.reference_symbols == ["SPY"]
