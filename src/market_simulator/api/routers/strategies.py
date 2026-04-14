import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_db, get_current_user
from market_simulator.api.schemas.runs import RunDashboardListItem
from market_simulator.api.schemas.strategies import (
    CreateStrategyRequest,
    CreateStrategyVersionRequest,
    StrategyDashboardResponse,
    StrategyLatestPerformance,
    StrategyResponse,
    StrategyVersionSummary,
)
from market_simulator.repositories.runs import count_runs, list_runs
from market_simulator.repositories.strategies import (
    create_strategy,
    create_strategy_version,
    get_strategy_for_user,
    list_strategies,
    list_strategy_versions,
)
from market_simulator.services.entitlements import (
    enforce_strategy_create_access,
    enforce_strategy_history_access,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


def hash_config(config):
    normalized = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


@router.post("")
def create_strategy_api(
    req: CreateStrategyRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    enforce_strategy_create_access(db, user["id"])

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
        change_note=None,
    )

    return {"strategy_id": strategy.id, "version_id": version.id}


@router.post("/{strategy_id}/versions")
def create_strategy_version_api(
    strategy_id: str,
    req: CreateStrategyVersionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    enforce_strategy_history_access(db, user["id"])

    strategy = get_strategy_for_user(db, strategy_id, user["id"])
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    version = create_strategy_version(
        db,
        strategy.id,
        req.config,
        hash_config(req.config),
        user["id"],
        change_note=req.change_note,
    )

    return {
        "strategy_id": str(strategy.id),
        "version_id": str(version.id),
    }


@router.get("")
def list_strategies_api(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return list_strategies(db, user["id"])


@router.get("/{strategy_id}/dashboard", response_model=StrategyDashboardResponse)
def get_strategy_dashboard_api(
    strategy_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    strategy = get_strategy_for_user(db, strategy_id, user["id"])
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    versions = list_strategy_versions(db, strategy_id)

    total_runs = count_runs(
        db,
        user["id"],
        strategy_id=strategy_id,
    )
    recent_runs = list_runs(
        db,
        user["id"],
        strategy_id=strategy_id,
        offset=0,
        limit=10,
    )

    associated_runs = []
    for run in recent_runs:
        summary_json = run.summary_json or {}

        associated_runs.append(
            RunDashboardListItem(
                run_id=str(run.id),
                strategy_id=str(run.strategy_id) if run.strategy_id else None,
                strategy_version_id=str(run.strategy_version_id) if run.strategy_version_id else None,
                strategy_name=run.strategy.name if run.strategy else None,
                strategy_version_number=(
                    run.strategy_version.version_number if run.strategy_version else None
                ),
                status=str(run.status),
                run_type=str(run.run_type),
                executor_type=str(run.executor_type),
                created_at=run.created_at,
                finished_at=run.finished_at,
                progress_pct=run.progress_pct,
                progress_message=run.progress_message,
                artifact_storage_type=str(run.artifact_storage_type),
                has_artifacts=bool(run.artifact_manifest_json),
                total_return_pct=summary_json.get("total_return_pct"),
                benchmark_return_pct=summary_json.get("benchmark_return_pct"),
                alpha_vs_benchmark_pct=summary_json.get("alpha_vs_benchmark_pct"),
                cagr_pct=summary_json.get("cagr_pct"),
                sharpe_ratio=summary_json.get("sharpe_ratio"),
                max_drawdown_pct=summary_json.get("max_drawdown_pct"),
                trade_count=summary_json.get("trade_count"),
                win_rate_pct=summary_json.get("win_rate_pct"),
            )
        )

    latest_succeeded_runs = list_runs(
        db,
        user["id"],
        status="SUCCEEDED",
        strategy_id=strategy_id,
        offset=0,
        limit=1,
    )

    latest_run_id = None
    latest_finished_at = None
    latest_performance = None

    if latest_succeeded_runs:
        latest_run = latest_succeeded_runs[0]
        summary_json = latest_run.summary_json or {}

        latest_run_id = str(latest_run.id)
        latest_finished_at = latest_run.finished_at

        latest_performance = StrategyLatestPerformance(
            run_id=latest_run_id,
            finished_at=latest_finished_at,
            total_return_pct=summary_json.get("total_return_pct"),
            benchmark_return_pct=summary_json.get("benchmark_return_pct"),
            alpha_vs_benchmark_pct=summary_json.get("alpha_vs_benchmark_pct"),
            cagr_pct=summary_json.get("cagr_pct"),
            sharpe_ratio=summary_json.get("sharpe_ratio"),
            max_drawdown_pct=summary_json.get("max_drawdown_pct"),
            benchmark_max_drawdown_pct=summary_json.get("benchmark_max_drawdown_pct"),
            trade_count=summary_json.get("trade_count"),
            win_rate_pct=summary_json.get("win_rate_pct"),
        )

    return StrategyDashboardResponse(
        strategy=StrategyResponse.model_validate(strategy),
        versions=[
            StrategyVersionSummary.model_validate(version).model_copy(
                update={"is_current": version.id == strategy.current_version_id}
            )
            for version in versions
        ],
        associated_runs=associated_runs,
        total_runs=total_runs,
        latest_run_id=latest_run_id,
        latest_finished_at=latest_finished_at,
        latest_performance=latest_performance,
    )