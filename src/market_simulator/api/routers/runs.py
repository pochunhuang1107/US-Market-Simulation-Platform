from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.runs import CreateRunRequest
from market_simulator.platform.services.run_dispatcher_service import RunDispatcherService
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories.runs import create_run, get_run, list_runs


router = APIRouter(prefix="/runs", tags=["runs"])

dispatcher = RunDispatcherService()
worker_service = RunWorkerService()


@router.post("")
def create_run_api(
    req: CreateRunRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return create_run(
        db,
        user["id"],
        req.strategy_id,
        req.strategy_version_id,
        req.run_type,
        req.executor_type,
        req.request_payload,
        max_attempts=req.max_attempts,
    )


@router.get("")
def list_runs_api(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return list_runs(db, user["id"])


@router.get("/{run_id}")
def get_run_api(
    run_id: str,
    db: Session = Depends(get_db),
):
    run = get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/enqueue")
def enqueue_run_api(
    run_id: str,
    db: Session = Depends(get_db),
):
    try:
        return dispatcher.dispatch_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{run_id}/cancel")
def cancel_run_api(
    run_id: str,
    db: Session = Depends(get_db),
):
    try:
        return dispatcher.cancel_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/admin/recover-stale")
def recover_stale_runs_api(
    db: Session = Depends(get_db),
):
    try:
        return worker_service.recover_stale_runs(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc