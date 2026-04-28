from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import hashlib
import json

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.runs import (
    CreateRunRequest,
    RecoverStaleRunsResponse,
    RunActionResponse,
    RunChartDataResponse,
    RunComparisonResponse,
    RunComparisonChartResponse,
    RunDashboardListItem,
    RunDashboardListResponse,
    RunDashboardResponse,
    RunDashboardQueryParams,
    RunListResponse,
    RunResponse,
    SaveDraftRunAsStrategyRequest,
    SaveDraftRunAsStrategyResponse,
)
from market_simulator.platform.services.artifact_store import build_artifact_store
from market_simulator.platform.services.run_chart_service import RunChartService
from market_simulator.platform.services.run_comparison_service import RunComparisonService
from market_simulator.platform.services.run_dispatcher_service import RunDispatcherService
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories.runs import (
    count_runs,
    create_run,
    find_duplicate_active_run,
    get_run_for_user,
    link_run_to_strategy_version,
    list_runs,
)
from market_simulator.repositories.strategies import (
    create_strategy,
    create_strategy_version,
    get_strategy_for_user,
    get_strategy_version,
)
from market_simulator.services.draft_validation import validate_draft_config
from market_simulator.services.entitlements import (
    enforce_comparison_run_limit,
    enforce_run_create_access,
    enforce_strategy_create_access,
)


router = APIRouter(prefix="/runs", tags=["runs"])

dispatcher = RunDispatcherService()
worker_service = RunWorkerService()
artifact_store = build_artifact_store()
chart_service = RunChartService()
comparison_service = RunComparisonService()


def _build_run_response(run) -> RunResponse:
    response = RunResponse.model_validate(run).enrich(
        artifact_url_resolver=artifact_store.generate_download_url
    )
    response.strategy_name = run.strategy.name if run.strategy else None
    response.strategy_version_number = (
        run.strategy_version.version_number if run.strategy_version else None
    )
    return response


def _hash_config(config: dict) -> str:
    normalized = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


def _validate_run_strategy_access(
    db: Session,
    *,
    user_id: str,
    strategy_id: str,
    strategy_version_id: str | None,
):
    strategy = get_strategy_for_user(db, strategy_id, user_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if strategy_version_id is not None:
        version = get_strategy_version(db, strategy_version_id)
        if version is None or str(version.strategy_id) != str(strategy.id):
            raise HTTPException(status_code=404, detail="Strategy version not found")

    return strategy


@router.post("", response_model=RunResponse)
def create_run_api(
    req: CreateRunRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    entitlements = enforce_run_create_access(db, user["id"], req.run_type)

    if req.strategy_id is not None:
        _validate_run_strategy_access(
            db,
            user_id=user["id"],
            strategy_id=req.strategy_id,
            strategy_version_id=req.strategy_version_id,
        )

    parent_run_id = None
    if req.parent_run_id is not None:
        parent_run = get_run_for_user(db, str(req.parent_run_id), user["id"])
        if parent_run is None:
            raise HTTPException(status_code=404, detail="Parent run not found")
        parent_run_id = parent_run.id

    request_payload = dict(req.request_payload or {})
    if parent_run_id is not None:
        request_payload["parent_run_id"] = str(parent_run_id)
    if req.draft_config is not None:
        try:
            validate_draft_config(
                config=req.draft_config,
                max_backtest_years=entitlements.max_backtest_years,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        request_payload["draft_config"] = req.draft_config

    duplicate_run = find_duplicate_active_run(
        db,
        user_id=user["id"],
        strategy_id=req.strategy_id,
        strategy_version_id=req.strategy_version_id,
        run_type=req.run_type,
        executor_type=req.executor_type,
        request_payload=request_payload,
    )
    if duplicate_run is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DUPLICATE_ACTIVE_RUN",
                "message": "An equivalent run is already active.",
                "existing_run_id": str(duplicate_run.id),
            },
        )

    run = create_run(
        db,
        user["id"],
        req.strategy_id,
        req.strategy_version_id,
        req.run_type,
        req.executor_type,
        request_payload,
        max_attempts=req.max_attempts,
        parent_run_id=parent_run_id,
    )
    return _build_run_response(run)


@router.get("", response_model=RunListResponse)
def list_runs_api(
    status: str | None = Query(default=None),
    executor_type: str | None = Query(default=None),
    run_type: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    offset = (page - 1) * page_size

    total = count_runs(
        db,
        user["id"],
        status=status,
        executor_type=executor_type,
        run_type=run_type,
        strategy_id=strategy_id,
    )

    runs = list_runs(
        db,
        user["id"],
        status=status,
        executor_type=executor_type,
        run_type=run_type,
        strategy_id=strategy_id,
        offset=offset,
        limit=page_size,
    )

    return RunListResponse(
        items=[_build_run_response(run) for run in runs],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + len(runs)) < total,
    )


@router.get("/dashboard", response_model=RunDashboardListResponse)
def list_runs_dashboard_api(
    status: list[str] | None = Query(default=None),
    executor_type: str | None = Query(default=None),
    run_type: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):

    params = RunDashboardQueryParams(
        status=status or [],
        executor_type=executor_type,
        run_type=run_type,
        strategy_id=strategy_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    total = count_runs(
        db,
        user["id"],
        status=params.status or None,
        executor_type=params.executor_type,
        run_type=params.run_type,
        strategy_id=params.strategy_id,
    )

    runs = list_runs(
        db,
        user["id"],
        status=params.status or None,
        executor_type=params.executor_type,
        run_type=params.run_type,
        strategy_id=params.strategy_id,
        offset=(params.page - 1) * params.page_size,
        limit=params.page_size,
        sort_by=params.sort_by,
        sort_order=params.sort_order,
    )

    items = []
    for run in runs:
        summary_json = run.summary_json or {}

        items.append(
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

    return RunDashboardListResponse(
        items=items,
        total=total,
        page=params.page,
        page_size=params.page_size,
        has_next=(params.page * params.page_size) < total,
    )


@router.get("/compare", response_model=RunComparisonResponse)
def compare_runs_api(
    run_ids: str = Query(..., description="Comma-separated run IDs"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    parsed_run_ids = [run_id.strip() for run_id in run_ids.split(",") if run_id.strip()]
    if len(parsed_run_ids) < 2:
        raise HTTPException(status_code=400, detail="At least two run IDs are required")
    enforce_comparison_run_limit(db, user["id"], len(parsed_run_ids))

    runs = []
    for run_id in parsed_run_ids:
        run = get_run_for_user(db, run_id, user["id"])
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        if run.status != "SUCCEEDED":
            raise HTTPException(status_code=400, detail=f"Run is not succeeded: {run_id}")
        runs.append(run)

    comparison = comparison_service.build_comparison(runs)
    return RunComparisonResponse(
        runs=comparison["runs"],
        metadata=comparison["metadata"],
    )


@router.get("/compare/chart", response_model=RunComparisonChartResponse)
def compare_runs_chart_api(
    run_ids: str = Query(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    parsed_run_ids = [r.strip() for r in run_ids.split(",") if r.strip()]

    if len(parsed_run_ids) < 2:
        raise HTTPException(status_code=400, detail="At least two run IDs are required")
    enforce_comparison_run_limit(db, user["id"], len(parsed_run_ids))

    runs = []
    for run_id in parsed_run_ids:
        run = get_run_for_user(db, run_id, user["id"])
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        if run.status != "SUCCEEDED":
            raise HTTPException(status_code=400, detail=f"Run not succeeded: {run_id}")
        runs.append(run)

    result = comparison_service.build_equity_curves(runs)

    return RunComparisonChartResponse(
        strategy_curves=result["strategy_curves"],
        benchmark_curves=result["benchmark_curves"],
        strategy_drawdown_curves=result["strategy_drawdown_curves"],
        benchmark_drawdown_curves=result["benchmark_drawdown_curves"],
        chart_window_mode=result["chart_window_mode"],
        chart_overlap_start=result["chart_overlap_start"],
        chart_overlap_end=result["chart_overlap_end"],
    )


@router.post("/{run_id}/save-strategy", response_model=SaveDraftRunAsStrategyResponse)
def save_draft_run_as_strategy_api(
    run_id: str,
    req: SaveDraftRunAsStrategyRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    entitlements = enforce_strategy_create_access(db, user["id"])

    run = get_run_for_user(db, run_id, user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.strategy_id is not None:
        raise HTTPException(status_code=400, detail="Run is already linked to a saved strategy")

    if run.status != "SUCCEEDED":
        raise HTTPException(
            status_code=400,
            detail="Only succeeded unsaved runs can be saved as a strategy",
        )

    draft_config = (run.request_payload or {}).get("draft_config")
    if not isinstance(draft_config, dict):
        raise HTTPException(status_code=400, detail="Run does not contain a saveable draft config")

    try:
        validate_draft_config(
            config=draft_config,
            max_backtest_years=entitlements.max_backtest_years,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        draft_config,
        _hash_config(draft_config),
        user["id"],
        change_note="Saved from run detail",
    )

    link_run_to_strategy_version(
        db,
        run,
        strategy_id=strategy.id,
        strategy_version_id=version.id,
    )

    return SaveDraftRunAsStrategyResponse(
        run_id=str(run.id),
        strategy_id=str(strategy.id),
        version_id=str(version.id),
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
    return _build_run_response(run)


@router.get("/{run_id}/dashboard", response_model=RunDashboardResponse)
def get_run_dashboard_api(
    run_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    run = get_run_for_user(db, run_id, user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run_response = _build_run_response(run)

    if run.status != "SUCCEEDED":
        raise HTTPException(status_code=400, detail="Dashboard is only available for succeeded runs")

    if not run.artifact_manifest_json:
        raise HTTPException(status_code=404, detail="Run artifacts not found")

    try:
        chart_data = chart_service.load_chart_data(run.artifact_manifest_json)
        chart_response = RunChartDataResponse(
            run_id=str(run.id),
            equity_curve=chart_data["equity_curve"],
            drawdown_curve=chart_data["drawdown_curve"],
            monthly_returns=chart_data["monthly_returns"],
            sleeve_equity_curve=chart_data["sleeve_equity_curve"],
            sleeve_weight_curve=chart_data["sleeve_weight_curve"],
            trade_markers=chart_data["trade_markers"],
        )

        return RunDashboardResponse(
            run=run_response,
            chart_data=chart_response,
        )
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing required artifact: {exc}") from exc


@router.get("/{run_id}/chart-data", response_model=RunChartDataResponse)
def get_run_chart_data_api(
    run_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    run = get_run_for_user(db, run_id, user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status != "SUCCEEDED":
        raise HTTPException(status_code=400, detail="Chart data is only available for succeeded runs")

    if not run.artifact_manifest_json:
        raise HTTPException(status_code=404, detail="Run artifacts not found")

    try:
        chart_data = chart_service.load_chart_data(run.artifact_manifest_json)
        return RunChartDataResponse(
            run_id=str(run.id),
            equity_curve=chart_data["equity_curve"],
            drawdown_curve=chart_data["drawdown_curve"],
            monthly_returns=chart_data["monthly_returns"],
            sleeve_equity_curve=chart_data["sleeve_equity_curve"],
            sleeve_weight_curve=chart_data["sleeve_weight_curve"],
            trade_markers=chart_data["trade_markers"],
        )
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing required artifact: {exc}") from exc


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


@router.get("/{run_id}/sleeve-chart")
def get_run_sleeve_chart(
    run_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    run = get_run_for_user(db, run_id, user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status != "SUCCEEDED":
        raise HTTPException(status_code=400, detail="Sleeve chart is only available for succeeded runs")

    if not run.artifact_manifest_json:
        raise HTTPException(status_code=404, detail="Run artifacts not found")

    try:
        chart_data = chart_service.load_chart_data(run.artifact_manifest_json)
        return {
            "run_id": str(run.id),
            "sleeve_equity_curve": chart_data["sleeve_equity_curve"],
        }
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing required artifact: {exc}") from exc
