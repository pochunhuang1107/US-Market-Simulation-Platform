from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_db, get_current_user
from market_simulator.api.schemas.runs import CreateRunRequest
from market_simulator.platform.services.run_execution_service import execute_run
from market_simulator.repositories.runs import create_run, list_runs, get_run


router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("")
def create_run_api(req: CreateRunRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return create_run(
        db,
        user["id"],
        req.strategy_id,
        req.strategy_version_id,
        req.run_type,
        req.executor_type,
        req.request_payload,
    )


@router.get("")
def list_runs_api(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return list_runs(db, user["id"])


@router.get("/{run_id}")
def get_run_api(run_id: str, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/execute")
def execute_run_api(run_id: str, db: Session = Depends(get_db)):
    try:
        return execute_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc