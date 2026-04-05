import hashlib
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_db, get_current_user
from market_simulator.api.schemas.strategies import CreateStrategyRequest, CreateStrategyVersionRequest
from market_simulator.repositories.strategies import (
    create_strategy,
    create_strategy_version,
    list_strategies,
)


router = APIRouter(prefix="/strategies", tags=["strategies"])


def hash_config(config):
    return hashlib.sha256(str(config).encode()).hexdigest()


@router.post("")
def create_strategy_api(req: CreateStrategyRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    strategy = create_strategy(
        db,
        user["id"],
        req.name,
        req.description,
        req.strategy_type,
    )

    version = create_strategy_version(
        db,
        strategy.id,
        req.config,
        hash_config(req.config),
        user["id"],
    )

    return {"strategy_id": strategy.id, "version_id": version.id}


@router.get("")
def list_strategies_api(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return list_strategies(db, user["id"])