from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.model_signals import (
    ModelSignalCatalogItemResponse,
    ModelSignalCatalogListResponse,
)
from market_simulator.services.entitlements import get_user_entitlements
from market_simulator.services.model_signal_catalog import (
    get_model_signal_catalog_entry,
    list_model_signal_catalog,
)


router = APIRouter(prefix="/model-signals", tags=["model-signals"])


MODEL_SIGNAL_ACCESS_LIMIT_DETAIL = {
    "code": "PLAN_LIMIT_MODEL_SIGNALS",
    "message": "Model-signal catalog access requires advanced research access.",
    "guidance": (
        "These entries are research candidates and are not available on the "
        "free plan."
    ),
    "plan_limit": True,
}


def _enforce_model_signal_catalog_access(db: Session, user_id: str) -> None:
    entitlements = get_user_entitlements(db, user_id)
    if entitlements.allow_advanced_builder:
        return
    raise HTTPException(status_code=403, detail=MODEL_SIGNAL_ACCESS_LIMIT_DETAIL)


@router.get("/catalog", response_model=ModelSignalCatalogListResponse)
def list_catalog(
    include_disabled: bool = Query(default=False),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _enforce_model_signal_catalog_access(db, user["id"])
    return ModelSignalCatalogListResponse(
        models=[
            ModelSignalCatalogItemResponse.model_validate(entry.to_public_dict())
            for entry in list_model_signal_catalog(include_disabled=include_disabled)
        ]
    )


@router.get("/catalog/{model_version}", response_model=ModelSignalCatalogItemResponse)
def get_catalog_model(
    model_version: str,
    include_disabled: bool = Query(default=False),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _enforce_model_signal_catalog_access(db, user["id"])
    entry = get_model_signal_catalog_entry(
        model_version,
        include_disabled=include_disabled,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Model signal not found")
    return ModelSignalCatalogItemResponse.model_validate(entry.to_public_dict())
