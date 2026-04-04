from __future__ import annotations

import argparse

from market_simulator.portfolio.comparison import run_portfolio_comparison


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-path", required=False)
    parser.add_argument("--artifacts-dir", required=False)
    args = parser.parse_args()

    result = run_portfolio_comparison(
        comparison_config_path=args.config,
        data_path=args.data_path,
        artifacts_dir=args.artifacts_dir,
    )

    print("\n=== Portfolio Comparison Summary ===")
    print(result["summary"].to_string(index=False))
    print(f"\nArtifacts written under: {result['comparison_dir']}")


if __name__ == "__main__":
    main()