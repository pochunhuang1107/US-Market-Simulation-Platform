from fastapi import FastAPI

from market_simulator.api.routers import health, strategies, runs, tracking

app = FastAPI()

app.include_router(health.router)
app.include_router(strategies.router)
app.include_router(runs.router)
app.include_router(tracking.router)