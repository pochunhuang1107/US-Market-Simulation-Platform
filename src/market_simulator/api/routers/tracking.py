from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_db, get_current_user
from market_simulator.api.schemas.tracking import CreateTrackedStrategyRequest
from market_simulator.repositories.tracking import (
    create_tracked_strategy,
    list_tracked_strategies,
)


router = APIRouter(prefix="/tracked-strategies", tags=["tracking"])


@router.post("")
def create_tracking_api(req: CreateTrackedStrategyRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
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