from __future__ import annotations

from pathlib import Path

from market_simulator.data.repository import MarketDataRepository
from market_simulator.engine.artifacts import write_artifacts
from market_simulator.engine.runner import run_simulation
from market_simulator.settings import get_settings
from market_simulator.strategy.compat import load_any_strategy

class SimulationService:
    def __init__(self, market_data_path: str | None = None, artifacts_dir: str | None = None):
        settings = get_settings()
        self.market_data_path = market_data_path or settings.market_data_path
        self.artifacts_dir = Path(artifacts_dir or settings.artifacts_dir)
        self.repo = MarketDataRepository(
            market_data_path=self.market_data_path,
            duckdb_database=settings.duckdb_database,
            s3_region=settings.s3_region,
        )

    def run_from_file(self, path: str | Path):
        strategy = load_any_strategy(path)
        market_data = self.repo.get_market_data(
            tradable_symbol=strategy.tradable_symbol,
            reference_symbols=strategy.reference_symbols,
            start_date=str(strategy.start_date),
            end_date=str(strategy.end_date),
        )
        result = run_simulation(market_data, strategy)
        artifact_dir = write_artifacts(result, self.artifacts_dir / strategy.name)
        result.artifact_dir = str(artifact_dir)
        return result
