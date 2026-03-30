from __future__ import annotations

import argparse
from market_simulator.service import SimulationService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a deterministic strategy simulation")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--data-path", required=False)
    parser.add_argument("--artifacts-dir", required=False)
    args = parser.parse_args()

    result = SimulationService(
        market_data_path=args.data_path,
        artifacts_dir=args.artifacts_dir,
    ).run_from_file(args.strategy)

    print("\n=== Summary ===")
    for key, value in result.summary.items():
        print(f"{key}: {value}")

    print("\n=== Sleeve Summary ===")
    for key, value in result.sleeve_summary.items():
        print(f"{key}: {value}")

    print(f"\nArtifacts written under: {result.artifact_dir}")


if __name__ == "__main__":
    main()