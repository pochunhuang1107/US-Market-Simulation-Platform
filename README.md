# US Market Strategy Platform

A full-stack strategy research and simulation platform for ETF-based trading strategies.

Users can describe strategies in natural language, convert them into a structured strategy definition, and run deterministic backtests with reporting and analytics.

---

## Overview

This project combines:

- Natural language strategy input through a chat-style strategy builder
- A deterministic backtesting engine powered by the Strategy V2 schema
- A full run lifecycle for creating, queuing, executing, and reviewing simulations
- A React frontend for strategy building and run analysis
- A FastAPI backend for orchestration and API access

---

## Architecture

### Design Principle

Natural language is an input method, not the execution engine.

- The strategy builder parses prompts into a validated structured config
- The backtest engine executes strategies deterministically
- Results are reproducible, inspectable, and auditable

---

## System Components

### Frontend
- React + Vite + TypeScript + Tailwind
- Chat-style Strategy Builder
- Structured strategy preview UI
- Run detail and dashboard views

### Backend
- FastAPI application for strategy, run, and builder APIs
- Async run orchestration and queue management
- PostgreSQL-backed application state
- Separate worker process for claiming and executing queued runs

### Engine
- Custom deterministic backtesting engine
- Strategy V2 canonical schema
- Multi-indicator rule system
- Risk controls including stop loss, take profit, and cooldown
- Portfolio and allocation logic

### Data Layer
- S3 + parquet historical datasets
- DuckDB for analytics and research reads

---

## Features

### Strategy Builder
- Natural language to Strategy V2 config
- Sequential editing with existing config context
- Structured preview before execution

### Strategy Engine
- RSI, SMA, EMA, MACD, KD indicators
- AND / OR / NOT composite rules
- Cross-symbol conditions
- Percent-of-equity allocation
- Stop loss / take profit / cooldown support

### Simulation Runs
- createStrategy -> createVersion -> createRun -> enqueueRun
- Async execution model with worker-based processing
- Run tracking and result retrieval through API endpoints

### Reporting
- Total return, CAGR, Sharpe ratio
- Max drawdown
- Trade logs
- Yearly performance
- Timeline output for playback and comparison

---

## Local Development

### 1. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install backend dependencies

```bash
pip install -e .
```

### 3. Start the FastAPI backend

```bash
uvicorn market_simulator.api.main:app --reload
```

### 4. Start the run worker

Open a second terminal, activate the same virtual environment, then run:

```bash
python -m market_simulator.platform.worker --recover-stale
```

### 5. Start the frontend

Open a third terminal and run:

```bash
cd frontend
npm install
npm run dev
```

The frontend will typically be available at:

```text
http://localhost:5173
```

The backend will typically be available at:

```text
http://127.0.0.1:8000
```

For beta-oriented Docker packaging and deployment notes, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Running a Simulation from the CLI

```bash
python scripts/run_simulation.py --strategy data/sample_strategies/qqq_engine_v2.json
```

---

## Parameter Sweep MVP

Backend parameter sweeps run through the normal run queue with:

- `run_type`: `PARAMETER_SWEEP`
- `executor_type`: `SWEEP_EXECUTOR`

Sweeps execute variants sequentially from one Strategy V2 base config, write `sweep_summary.json` and `sweep_results.csv`, and rank successful variants by `ranking_metric` (`sharpe` by default). The default safety cap is 25 variants unless `max_variants` is set lower in the request.

Example run payload:

```json
{
  "run_type": "PARAMETER_SWEEP",
  "executor_type": "SWEEP_EXECUTOR",
  "request_payload": {
    "base_config": {
      "...": "Strategy V2 config"
    },
    "grid": {
      "entry_rule.threshold": [20, 25, 30],
      "exit_rule.threshold": [60, 65, 70],
      "risk.stop_loss_pct": [null, 0.1]
    },
    "ranking_metric": "sharpe",
    "max_variants": 25
  }
}
```

If a saved strategy version is attached to the run, `base_config` may be omitted and the version config is used as the sweep base.

---

## Notes

- All strategies must map to the Strategy V2 schema
- Execution is deterministic
- The parser helps generate configs, but it does not execute strategy logic directly
- For the full web app flow, run the backend, worker, and frontend together
