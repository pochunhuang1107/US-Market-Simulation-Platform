from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-dir", required=True)
    args = parser.parse_args()

    artifacts_dir = Path(args.artifacts_dir)
    timeline = pd.read_csv(artifacts_dir / "timeline.csv")
    timeline["date"] = pd.to_datetime(timeline["date"])

    plt.figure(figsize=(12, 6))
    plt.plot(timeline["date"], timeline["strategy_equity"], label="Strategy")
    plt.plot(timeline["date"], timeline["benchmark_equity"], label="Benchmark")
    plt.xlabel("Date")
    plt.ylabel("Equity")
    plt.title("Strategy vs Benchmark")
    plt.legend()
    plt.tight_layout()

    output = artifacts_dir / "strategy_vs_benchmark.png"
    plt.savefig(output, dpi=150)
    print(f"Saved plot to: {output}")

if __name__ == "__main__":
    main()
