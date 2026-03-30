from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException

from market_simulator.service import SimulationService

app = FastAPI(title="US Market Backtest Engine V2", version="0.2.0")
service = SimulationService()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/simulations/run")
def run_simulation(payload: dict):
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(payload, tmp)
            tmp_path = tmp.name
        result = service.run_from_file(tmp_path)
        Path(tmp_path).unlink(missing_ok=True)
        return {
            "summary": result.summary,
            "yearly_report": result.yearly_report,
            "timeline_rows": len(result.timeline),
            "trade_rows": len(result.trade_log),
            "events_rows": len(result.events),
            "artifact_dir": result.artifact_dir,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
