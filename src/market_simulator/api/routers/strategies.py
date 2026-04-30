import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from market_simulator.api.deps import get_db, get_current_user
from market_simulator.api.schemas.runs import RunDashboardListItem
from market_simulator.api.schemas.strategies import (
    CreateStrategyRequest,
    CreateStrategyVersionRequest,
    StrategyDashboardResponse,
    StrategyReferencePerformance,
    StrategyResponse,
    StrategyVersionSummary,
)
from market_simulator.db.enums import StrategyStatus
from market_simulator.repositories.runs import count_runs, list_runs
from market_simulator.repositories.strategies import (
    create_strategy,
    create_strategy_version,
    get_strategy_for_user,
    get_strategy_version,
    get_strategy_version_reference_run,
    list_strategies,
    list_strategy_versions,
    set_missing_reference_run_from_eligible_success,
    update_strategy_status_for_user,
)
from market_simulator.services.entitlements import (
    enforce_strategy_create_access,
    enforce_strategy_history_access,
)
from market_simulator.services.draft_validation import validate_backtest_window
from market_simulator.services.strategy_version_identity import (
    normalize_strategy_version_identity_fields,
    validate_strategy_version_identity,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


def hash_config(config):
    normalized = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


def _run_source_metadata(run) -> dict:
    payload = run.request_payload or {}
    source = payload.get("source")
    if source != "sweep_variant_save":
        return {
            "source": None,
            "source_sweep_run_id": None,
            "source_variant_id": None,
            "source_variant_rank": None,
            "source_ranking_metric": None,
        }

    source_variant_rank = payload.get("source_variant_rank")
    return {
        "source": "sweep_variant_save",
        "source_sweep_run_id": payload.get("source_sweep_run_id"),
        "source_variant_id": payload.get("source_variant_id"),
        "source_variant_rank": source_variant_rank if isinstance(source_variant_rank, int) else None,
        "source_ranking_metric": payload.get("source_ranking_metric"),
    }


def _performance_from_run(run) -> StrategyReferencePerformance:
    summary_json = run.summary_json or {}
    return StrategyReferencePerformance(
        run_id=str(run.id),
        **_run_source_metadata(run),
        finished_at=run.finished_at,
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
    entitlements = enforce_strategy_history_access(db, user["id"])

    strategy = get_strategy_for_user(db, strategy_id, user["id"])
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    normalized_config = normalize_strategy_version_identity_fields(
        strategy_name=strategy.name,
        config=req.config,
    )
    current_version = (
        get_strategy_version(db, strategy.current_version_id)
        if strategy.current_version_id is not None
        else None
    )
    if current_version is not None:
        try:
            validate_strategy_version_identity(
                current_config=current_version.config_json,
                new_config=normalized_config,
            )
            validate_backtest_window(
                config=normalized_config,
                max_backtest_years=entitlements.max_backtest_years,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    version = create_strategy_version(
        db,
        strategy.id,
        normalized_config,
        hash_config(normalized_config),
        user["id"],
        change_note=req.change_note,
    )

    return {
        "strategy_id": str(strategy.id),
        "version_id": str(version.id),
    }


@router.get("")
def list_strategies_api(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return list_strategies(db, user["id"], include_archived=include_archived)


@router.post("/{strategy_id}/archive", response_model=StrategyResponse)
def archive_strategy_api(
    strategy_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    strategy = update_strategy_status_for_user(
        db,
        strategy_id,
        user["id"],
        StrategyStatus.ARCHIVED,
    )
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    return strategy


@router.post("/{strategy_id}/restore", response_model=StrategyResponse)
def restore_strategy_api(
    strategy_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    strategy = update_strategy_status_for_user(
        db,
        strategy_id,
        user["id"],
        StrategyStatus.ACTIVE,
    )
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    return strategy


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
        include_derived_results=False,
    )
    recent_runs = list_runs(
        db,
        user["id"],
        strategy_id=strategy_id,
        include_derived_results=False,
        offset=0,
        limit=100,
    )

    associated_runs = []
    for run in recent_runs:
        summary_json = run.summary_json or {}
        source_metadata = _run_source_metadata(run)

        associated_runs.append(
            RunDashboardListItem(
                run_id=str(run.id),
                strategy_id=str(run.strategy_id) if run.strategy_id else None,
                strategy_version_id=str(run.strategy_version_id) if run.strategy_version_id else None,
                strategy_name=run.strategy.name if run.strategy else None,
                strategy_version_number=(
                    run.strategy_version.version_number if run.strategy_version else None
                ),
                **source_metadata,
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

    repaired_any_reference = False
    for version in versions:
        if version.reference_run_id is None:
            repaired_reference_run = set_missing_reference_run_from_eligible_success(
                db,
                version_id=version.id,
                user_id=user["id"],
            )
            if repaired_reference_run is not None:
                repaired_any_reference = True

    if repaired_any_reference:
        versions = list_strategy_versions(db, strategy_id)

    reference_runs_by_version_id = {}
    for version in versions:
        reference_runs_by_version_id[str(version.id)] = get_strategy_version_reference_run(
            db,
            version_id=version.id,
            user_id=user["id"],
        )

    current_version = next(
        (version for version in versions if version.id == strategy.current_version_id),
        versions[0] if versions else None,
    )
    reference_run = (
        reference_runs_by_version_id.get(str(current_version.id))
        if current_version is not None
        else None
    )

    reference_run_id = str(reference_run.id) if reference_run is not None else None
    reference_finished_at = reference_run.finished_at if reference_run is not None else None
    reference_performance = _performance_from_run(reference_run) if reference_run is not None else None

    return StrategyDashboardResponse(
        strategy=StrategyResponse.model_validate(strategy),
        versions=[
            StrategyVersionSummary.model_validate(version).model_copy(
                update={
                    "is_current": version.id == strategy.current_version_id,
                    "reference_performance": (
                        _performance_from_run(reference_runs_by_version_id[str(version.id)])
                        if reference_runs_by_version_id[str(version.id)] is not None
                        else None
                    ),
                }
            )
            for version in versions
        ],
        associated_runs=associated_runs,
        total_runs=total_runs,
        reference_run_id=reference_run_id,
        reference_finished_at=reference_finished_at,
        reference_performance=reference_performance,
        latest_run_id=reference_run_id,
        latest_finished_at=reference_finished_at,
        latest_performance=reference_performance,
    )
