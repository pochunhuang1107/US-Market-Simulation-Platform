from __future__ import annotations

import argparse
import json

from market_simulator.models.portfolio import PortfolioConfig
from market_simulator.portfolio.portfolio_engine import run_portfolio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-path", required=False)
    parser.add_argument("--artifacts-dir", required=False)
    args = parser.parse_args()

    with open(args.config) as f:
        config = PortfolioConfig(**json.load(f))

    result = run_portfolio(
        portfolio_config=config,
        data_path=args.data_path,
        artifacts_dir=args.artifacts_dir,
    )

    print("\n=== Portfolio Summary ===")
    for k, v in result["summary"].items():
        print(f"{k}: {v}")

    print(f"\nArtifacts written under: {result['artifact_dir']}")


if __name__ == "__main__":
    main()