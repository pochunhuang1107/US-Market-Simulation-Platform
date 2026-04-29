from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_db, get_current_user
from market_simulator.api.schemas.tracking import CreateTrackedStrategyRequest
from market_simulator.repositories.strategies import get_strategy_for_user, get_strategy_version
from market_simulator.repositories.tracking import (
    create_tracked_strategy,
    list_tracked_strategies,
)


router = APIRouter(prefix="/tracked-strategies", tags=["tracking"])


@router.post("")
def create_tracking_api(
    req: CreateTrackedStrategyRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    strategy = get_strategy_for_user(db, req.strategy_id, user["id"])
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if req.strategy_version_id is not None:
        version = get_strategy_version(db, req.strategy_version_id)
        if version is None or str(version.strategy_id) != str(strategy.id):
            raise HTTPException(status_code=404, detail="Strategy version not found")

    return create_tracked_strategy(
        db,
        user["id"],
        req.strategy_id,
        req.strategy_version_id,
        req.tracking_mode,
    )


@router.get("")
def list_tracking_api(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return list_tracked_strategies(db, user["id"])
