from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.runs import (
    CreateRunRequest,
    RecoverStaleRunsResponse,
    RunActionResponse,
    RunListResponse,
    RunResponse,
)
from market_simulator.platform.services.run_dispatcher_service import RunDispatcherService
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories.runs import create_run, get_run_for_user, list_runs


router = APIRouter(prefix="/runs", tags=["runs"])

dispatcher = RunDispatcherService()
worker_service = RunWorkerService()


@router.post("", response_model=RunResponse)
def create_run_api(
    req: CreateRunRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    run = create_run(
        db,
        user["id"],
        req.strategy_id,
        req.strategy_version_id,
        req.run_type,
        req.executor_type,
        req.request_payload,
        max_attempts=req.max_attempts,
    )
    return RunResponse.model_validate(run)


@router.get("", response_model=RunListResponse)
def list_runs_api(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    runs = list_runs(db, user["id"])
    return RunListResponse(
        items=[RunResponse.model_validate(run) for run in runs]
    )


@router.get("/{run_id}", response_model=RunResponse)
def get_run_api(
    run_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    run = get_run_for_user(db, run_id, user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunResponse.model_validate(run)


@router.post("/{run_id}/enqueue", response_model=RunActionResponse)
def enqueue_run_api(
    run_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        result = dispatcher.dispatch_run(db, run_id, user["id"])
        return RunActionResponse.model_validate(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{run_id}/cancel", response_model=RunActionResponse)
def cancel_run_api(
    run_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        result = dispatcher.cancel_run(db, run_id, user["id"])
        return RunActionResponse.model_validate(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/admin/recover-stale", response_model=RecoverStaleRunsResponse)
def recover_stale_runs_api(
    db: Session = Depends(get_db),
):
    try:
        result = worker_service.recover_stale_runs(db)
        return RecoverStaleRunsResponse.model_validate(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc