from __future__ import annotations

from fastapi import APIRouter, Depends

from market_simulator.api.deps import get_current_user
from market_simulator.api.schemas.strategy_builder import (
    StrategyBuilderGenerateRequest,
    StrategyBuilderGenerateResponse,
)
from market_simulator.services.strategy_builder_service import (
    generate_strategy_builder_draft,
)

router = APIRouter(prefix="/strategy-builder", tags=["strategy-builder"])

@router.post("/generate", response_model=StrategyBuilderGenerateResponse)
def generate_strategy_draft_api(
    req: StrategyBuilderGenerateRequest,
    user=Depends(get_current_user),
):
    _ = user

    config, summary, warnings, _, changes = generate_strategy_builder_draft(req)

    return StrategyBuilderGenerateResponse(
        config=config,
        summary=summary,
        warnings=warnings,
        changes=changes,
    )
