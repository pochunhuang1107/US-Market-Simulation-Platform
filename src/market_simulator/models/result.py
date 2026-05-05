from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SimulationResult:
    summary: dict[str, Any]
    sleeve_summary: dict[str, Any]
    yearly_report: list[dict[str, Any]]
    trade_log: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    events: list[dict[str, Any]]
    trade_signal_snapshots: list[dict[str, Any]] | None = None
    artifact_dir: str | None = None
