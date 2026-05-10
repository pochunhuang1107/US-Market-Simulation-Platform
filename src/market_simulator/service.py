from __future__ import annotations

from pathlib import Path

from market_simulator.data.repository import MarketDataRepository
from market_simulator.engine.artifacts import write_artifacts
from market_simulator.engine.runner import run_simulation
from market_simulator.settings import get_settings
from market_simulator.strategy.compat import load_any_strategy
from market_simulator.models.strategy_v2 import StrategyV2


class SimulationService:
    def __init__(self, market_data_path: str | None = None, artifacts_dir: str | None = None):
        settings = get_settings()
        self.market_data_path = market_data_path or settings.market_data_path
        self.artifacts_dir = Path(artifacts_dir or settings.artifacts_dir)
        self.repo = MarketDataRepository(
            market_data_path=self.market_data_path,
            reference_series_data_path=settings.reference_series_data_path,
            supported_reference_series_symbols=settings.supported_reference_series_symbols,
            duckdb_database=settings.duckdb_database,
            s3_region=settings.s3_region,
        )

    def run_from_file(self, path: str | Path, output_dir: str | Path | None = None):
        strategy = load_any_strategy(path)
        return self.run_from_strategy(strategy, output_dir=output_dir)

    def run_from_config(self, config: dict, output_dir: str | Path | None = None):
        strategy = StrategyV2.model_validate(config)
        return self.run_from_strategy(strategy, output_dir=output_dir)

    def run_from_strategy(self, strategy, output_dir: str | Path | None = None):
        reference_symbols = (
            strategy.rotation_required_reference_symbols()
            if getattr(getattr(strategy, "rotation", None), "enabled", False)
            else strategy.reference_symbols
        )
        market_data = self.repo.get_market_data(
            tradable_symbol=strategy.tradable_symbol,
            reference_symbols=reference_symbols,
            start_date=str(strategy.start_date),
            end_date=str(strategy.end_date),
        )
        result = run_simulation(market_data, strategy)

        artifact_output_dir = Path(output_dir) if output_dir else (self.artifacts_dir / strategy.name)
        artifact_dir = write_artifacts(result, artifact_output_dir)
        result.artifact_dir = str(artifact_dir)
        return result
