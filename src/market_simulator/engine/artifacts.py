from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from market_simulator.reporting.tearsheet import (
    build_report_bundle,
    build_monthly_return_table,
)


def write_artifacts(result, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # existing
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
    (output_dir / "trade_signal_snapshots.json").write_text(
        json.dumps(getattr(result, "trade_signal_snapshots", None) or [], indent=2),
        encoding="utf-8",
    )

    timeline_df = pd.DataFrame(result.timeline)
    trade_df = pd.DataFrame(result.trade_log)

    monthly_df = build_monthly_return_table(timeline_df)
    monthly_df.to_csv(output_dir / "monthly_returns.csv", index=False)

    report_bundle = build_report_bundle(
        result.summary,
        trade_df,
        timeline_df,
    )

    (output_dir / "report_bundle.json").write_text(
        json.dumps(report_bundle, indent=2),
        encoding="utf-8",
    )

    result.report_bundle = report_bundle

    return output_dir
