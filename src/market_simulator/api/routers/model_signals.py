from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.model_signals import (
    ModelSignalCatalogItemResponse,
    ModelSignalCatalogListResponse,
    ModelSignalCurrentPreviewResponse,
)
from market_simulator.services.entitlements import enforce_model_signal_access
from market_simulator.services.model_signal_catalog import (
    get_model_signal_catalog_entry,
    list_model_signal_catalog,
)
from market_simulator.services.model_signal_preview import (
    ModelSignalPreviewInvalidError,
    ModelSignalPreviewNotFoundError,
    preview_current_model_signal,
)


router = APIRouter(prefix="/model-signals", tags=["model-signals"])


def _enforce_model_signal_catalog_access(db: Session, user_id: str) -> None:
    enforce_model_signal_access(db, user_id)


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


@router.get(
    "/catalog/{model_version}/current",
    response_model=ModelSignalCurrentPreviewResponse,
)
def get_current_model_signal_preview(
    model_version: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _enforce_model_signal_catalog_access(db, user["id"])
    try:
        preview = preview_current_model_signal(model_version)
    except ModelSignalPreviewNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ModelSignalPreviewInvalidError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return ModelSignalCurrentPreviewResponse.model_validate(preview)
