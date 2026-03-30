from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def write_artifacts(result, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "summary.json").write_text(
        json.dumps(result.summary, indent=2),
        encoding="utf-8",
    )

    (output_dir / "sleeve_summary.json").write_text(
        json.dumps(result.sleeve_summary, indent=2),
        encoding="utf-8",
    )

    pd.DataFrame(result.yearly_report).to_csv(output_dir / "yearly_report.csv", index=False)
    pd.DataFrame(result.trade_log).to_csv(output_dir / "trade_log.csv", index=False)
    pd.DataFrame(result.timeline).to_csv(output_dir / "timeline.csv", index=False)
    pd.DataFrame(result.events).to_csv(output_dir / "events.csv", index=False)

    return output_dir