from __future__ import annotations

import argparse

from market_simulator.experiments.runner import run_sweep


def main() -> None:
    parser = argparse.ArgumentParser(description="Run parameter sweep")
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-path", required=False)
    parser.add_argument("--artifacts-dir", required=False)
    args = parser.parse_args()

    exp_dir = run_sweep(
        sweep_config_path=args.config,
        data_path=args.data_path,
        artifacts_dir=args.artifacts_dir,
    )

    print(f"\nSweep artifacts written under: {exp_dir}")


if __name__ == "__main__":
    main()