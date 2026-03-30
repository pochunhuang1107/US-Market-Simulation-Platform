# US Market Backtest Engine V2

A richer deterministic ETF strategy simulation engine.

## Included
- v1-compatible strategy ingestion
- v2 canonical strategy schema
- composite rules with AND / OR / NOT
- RSI, SMA, EMA, MACD, KD indicators
- reference-symbol conditions
- percent-of-equity allocation
- stop loss, take profit, partial take profit
- timeline output for strategy vs benchmark playback
- yearly and LTD reporting
- FastAPI starter endpoint

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run

```bash
python scripts/run_simulation.py --strategy data/sample_strategies/qqq_engine_v2.json
```
