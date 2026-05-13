from fastapi import FastAPI

from market_simulator.api.routers import (
    health,
    me,
    model_signals,
    runs,
    strategies,
    strategy_builder,
    tracking,
)

app = FastAPI()

app.include_router(health.router)
app.include_router(me.router)
app.include_router(model_signals.router)
app.include_router(strategies.router)
app.include_router(runs.router)
app.include_router(tracking.router)
app.include_router(strategy_builder.router)
