from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderGenerateRequest,
    StrategyBuilderGenerateResponse,
)
from market_simulator.services.entitlements import enforce_builder_access
from market_simulator.services.strategy_builder_service import (
    generate_strategy_builder_draft,
)

router = APIRouter(prefix="/strategy-builder", tags=["strategy-builder"])


@router.post("/generate", response_model=StrategyBuilderGenerateResponse)
def generate_strategy_draft_api(
    req: StrategyBuilderGenerateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    enforce_builder_access(db, user["id"])

    config, summary, warnings, _, changes = generate_strategy_builder_draft(req)

    return StrategyBuilderGenerateResponse(
        config=config,
        summary=summary,
        warnings=warnings,
        changes=changes,
    )