from __future__ import annotations

import argparse
import json

from market_simulator.models.portfolio import PortfolioConfig
from market_simulator.portfolio.portfolio_engine import run_portfolio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    with open(args.config) as f:
        config = PortfolioConfig(**json.load(f))

    result = run_portfolio(config)

    print("\n=== Portfolio Summary ===")
    for k, v in result["summary"].items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()