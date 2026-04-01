from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from market_simulator.service import SimulationService

from .generator import generate_configs
from .ranking import rank_results
from .registry import create_experiment_dir, hash_config


def run_sweep(
    sweep_config_path: str,
    data_path: str | None = None,
    artifacts_dir: str | None = None,
):
    with open(sweep_config_path, "r", encoding="utf-8") as f:
        sweep = json.load(f)

    with open(sweep["base_strategy_path"], "r", encoding="utf-8") as f:
        base_config = json.load(f)

    ranking_cfg = sweep["ranking"]
    search_space = sweep["search_space"]

    base_artifacts_dir = artifacts_dir or "data/local_artifacts/experiments"
    exp_dir = create_experiment_dir(base_artifacts_dir)

    service = SimulationService(
        market_data_path=data_path,
        artifacts_dir=str(exp_dir),
    )

    rows = []

    for idx, config in enumerate(generate_configs(base_config, search_space), start=1):
        run_hash = hash_config(config)
        config["name"] = f"{base_config['name']}-sweep-{idx:03d}-{run_hash[:6]}"

        result = service.run_from_config(config)

        row = dict(result.summary)
        row["run_id"] = run_hash
        row["strategy_name"] = config["name"]
        row["artifact_dir"] = result.artifact_dir

        for key in search_space:
            current = config
            for part in key.split("."):
                if "[" in part and part.endswith("]"):
                    name, idx_part = part[:-1].split("[", 1)
                    current = current[name][int(idx_part)]
                else:
                    current = current[part]
            row[key] = current

        rows.append(row)

    df = pd.DataFrame(rows)

    if "trade_count" in df.columns and "min_trade_count" in ranking_cfg:
        df = df[df["trade_count"] >= ranking_cfg["min_trade_count"]].copy()

    ranked = rank_results(
        df=df,
        primary=ranking_cfg["primary_metric"],
        secondary=ranking_cfg["secondary_metric"],
    )

    ranked.to_csv(exp_dir / "runs_summary.csv", index=False)
    ranked.head(10).to_csv(exp_dir / "top_10.csv", index=False)

    return exp_dir