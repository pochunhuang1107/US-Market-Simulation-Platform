from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import hashlib
import json
from pathlib import Path

from market_simulator.api.deps import get_current_user, get_db
from market_simulator.api.schemas.runs import (
    CreateRunRequest,
    PromoteSweepVariantRequest,
    PromoteSweepVariantResponse,
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
    SweepVariantDetailResponse,
)
from market_simulator.db.enums import RunStatus
from market_simulator.models.strategy_v2 import StrategyV2
from market_simulator.platform.services.artifact_store import build_artifact_store
from market_simulator.platform.services.parameter_sweep import (
    ParameterSweepError,
    build_sweep_request,
)
from market_simulator.platform.services.run_chart_service import RunChartService
from market_simulator.platform.services.run_comparison_service import RunComparisonService
from market_simulator.platform.services.run_dispatcher_service import RunDispatcherService
from market_simulator.platform.services.run_worker_service import RunWorkerService
from market_simulator.repositories.runs import (
    count_runs,
    create_run,
    find_saved_sweep_variant_run,
    find_duplicate_active_run,
    get_run_for_user,
    link_run_to_strategy_version,
    list_runs,
    mark_run_succeeded,
)
from market_simulator.repositories.strategies import (
    create_strategy,
    create_strategy_version,
    get_strategy_for_user,
    get_strategy_version,
    set_strategy_version_reference_run,
)
from market_simulator.services.draft_validation import validate_backtest_window, validate_draft_config
from market_simulator.services.strategy_version_identity import (
    normalize_strategy_version_identity_fields,
    validate_strategy_version_identity,
)
from market_simulator.services.entitlements import (
    enforce_comparison_run_limit,
    enforce_run_create_access,
    enforce_strategy_history_access,
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
    for key, value in _run_source_metadata(run).items():
        setattr(response, key, value)
    return response


def _hash_config(config: dict) -> str:
    normalized = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode()).hexdigest()


def _short_run_id(run_id: str) -> str:
    return str(run_id).split("-")[0]


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


def _strategy_name_from_config(config: dict, variant_name: str | None = None) -> str:
    name = config.get("name") or variant_name or "Strategy"
    return f"{str(name).strip() or 'Strategy'} - Sweep best"


def _sweep_origin(run) -> str:
    request_payload = run.request_payload or {}
    explicit_origin = request_payload.get("sweep_origin")
    if explicit_origin in {"STANDALONE", "SAVED_STRATEGY"}:
        return explicit_origin

    if isinstance(request_payload.get("base_config"), dict):
        return "STANDALONE"

    return "SAVED_STRATEGY" if run.strategy_id is not None else "STANDALONE"


def _sweep_origin_strategy_id(run) -> str | None:
    request_payload = run.request_payload or {}
    origin_strategy_id = request_payload.get("sweep_origin_strategy_id")
    if isinstance(origin_strategy_id, str) and origin_strategy_id.strip():
        return origin_strategy_id

    return str(run.strategy_id) if run.strategy_id is not None else None


def _find_sweep_variant(run, variant_id: str) -> dict | None:
    summary_json = run.summary_json or {}
    results = summary_json.get("results")
    if isinstance(results, list):
        for result in results:
            if isinstance(result, dict) and str(result.get("variant_id")) == str(variant_id):
                return result

    best_variant = summary_json.get("best_variant")
    if isinstance(best_variant, dict) and str(best_variant.get("variant_id")) == str(variant_id):
        return best_variant

    return None


def _sweep_variant_rank(run, variant_id: str) -> int | None:
    results = (run.summary_json or {}).get("results")
    if not isinstance(results, list):
        return None

    for index, result in enumerate(results, start=1):
        if isinstance(result, dict) and str(result.get("variant_id")) == str(variant_id):
            return index

    return None


def _reconstruct_sweep_variant_config(run, variant_id: str) -> dict | None:
    fallback_base_config = None
    if run.strategy_version is not None:
        fallback_base_config = run.strategy_version.config_json

    try:
        request = build_sweep_request(
            run.request_payload or {},
            fallback_base_config=fallback_base_config,
        )
    except ParameterSweepError:
        return None

    for variant in request["variants"]:
        if str(variant.get("variant_id")) == str(variant_id):
            return variant.get("config")

    return None


def _get_sweep_variant_config(run, variant: dict, variant_id: str) -> dict:
    config = variant.get("config")
    if not isinstance(config, dict):
        config = _reconstruct_sweep_variant_config(run, variant_id)

    if not isinstance(config, dict):
        raise HTTPException(
            status_code=400,
            detail="Selected sweep variant does not include a saveable strategy config.",
        )

    try:
        StrategyV2.model_validate(config)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Selected sweep variant config is not a valid Strategy V2 config.",
        ) from exc

    return config


def _variant_artifact_manifest(variant: dict) -> dict[str, str] | None:
    artifact_dir = variant.get("artifact_dir")
    if not isinstance(artifact_dir, str) or not artifact_dir.strip():
        return None

    variant_dir = Path(artifact_dir)
    manifest = {
        "summary": str(variant_dir / "summary.json"),
        "sleeve_summary": str(variant_dir / "sleeve_summary.json"),
        "yearly_report": str(variant_dir / "yearly_report.csv"),
        "trade_log": str(variant_dir / "trade_log.csv"),
        "timeline": str(variant_dir / "timeline.csv"),
        "events": str(variant_dir / "events.csv"),
        "monthly_returns": str(variant_dir / "monthly_returns.csv"),
        "report_bundle": str(variant_dir / "report_bundle.json"),
    }

    required = ["timeline", "monthly_returns", "trade_log"]
    if not all(Path(manifest[key]).exists() for key in required):
        return None

    return manifest


def _sweep_variant_summary_json(variant: dict, variant_id: str) -> dict:
    excluded_keys = {"config", "artifact_dir"}
    summary = {
        key: value
        for key, value in variant.items()
        if key not in excluded_keys
    }
    summary["source"] = "sweep_variant_save"
    summary["variant_id"] = str(summary.get("variant_id") or variant_id)
    return summary


def _create_sweep_variant_result_run(
    db: Session,
    *,
    user_id: str,
    sweep_run,
    variant_id: str,
    variant: dict,
    rank: int | None,
    ranking_metric: str | None,
    strategy_id,
    strategy_version_id,
    config: dict,
):
    manifest = _variant_artifact_manifest(variant) or {}
    variant_artifact_dir = variant.get("artifact_dir")
    artifact_dir = (
        variant_artifact_dir
        if isinstance(variant_artifact_dir, str) and variant_artifact_dir.strip()
        else f"{sweep_run.artifact_dir or 'data/local_artifacts/runs'}/{sweep_run.id}/variants/{variant_id}"
    )

    run = create_run(
        db,
        user_id,
        strategy_id,
        strategy_version_id,
        "SIMULATION",
        "SIMULATION_EXECUTOR",
        {
            "source": "sweep_variant_save",
            "source_sweep_run_id": str(sweep_run.id),
            "source_variant_id": variant_id,
            "source_variant_rank": rank,
            "source_ranking_metric": ranking_metric,
            "draft_config": config,
        },
        max_attempts=1,
        parent_run_id=sweep_run.id,
    )
    run.status = RunStatus.RUNNING
    db.commit()
    db.refresh(run)

    return mark_run_succeeded(
        db,
        run,
        summary_json=_sweep_variant_summary_json(variant, variant_id),
        artifact_dir=artifact_dir,
        artifact_manifest_json=manifest,
        artifact_storage_type=sweep_run.artifact_storage_type,
        artifact_root_uri=artifact_dir if manifest else None,
    )


def _load_variant_chart_data(variant: dict) -> dict | None:
    manifest = _variant_artifact_manifest(variant)
    if manifest is None:
        return None

    try:
        return chart_service.load_chart_data(manifest)
    except Exception:
        return None


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
        if req.strategy_version_id is not None and req.run_type in {"SIMULATION", "PARAMETER_SWEEP"}:
            version = get_strategy_version(db, req.strategy_version_id)
            if version is not None:
                try:
                    validate_backtest_window(
                        config=version.config_json,
                        max_backtest_years=entitlements.max_backtest_years,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    if req.run_type == "PARAMETER_SWEEP":
        fallback_base_config = None
        if not isinstance(request_payload.get("base_config"), dict):
            if req.draft_config is not None:
                fallback_base_config = req.draft_config
            elif req.strategy_version_id is not None:
                version = get_strategy_version(db, req.strategy_version_id)
                if version is not None:
                    fallback_base_config = version.config_json

        try:
            build_sweep_request(
                request_payload,
                fallback_base_config=fallback_base_config,
            )
        except ParameterSweepError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if req.strategy_id is not None:
            request_payload.setdefault("sweep_origin", "SAVED_STRATEGY")
            request_payload.setdefault("sweep_origin_strategy_id", req.strategy_id)
            if req.strategy_version_id is not None:
                request_payload.setdefault("sweep_origin_strategy_version_id", req.strategy_version_id)
        else:
            request_payload.setdefault("sweep_origin", "STANDALONE")

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
    include_derived_results: bool = Query(default=False),
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
        include_derived_results=include_derived_results,
    )

    runs = list_runs(
        db,
        user["id"],
        status=status,
        executor_type=executor_type,
        run_type=run_type,
        strategy_id=strategy_id,
        include_derived_results=include_derived_results,
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
    include_derived_results: bool = Query(default=False),
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
        include_derived_results=include_derived_results,
    )

    runs = list_runs(
        db,
        user["id"],
        status=params.status or None,
        executor_type=params.executor_type,
        run_type=params.run_type,
        strategy_id=params.strategy_id,
        include_derived_results=include_derived_results,
        offset=(params.page - 1) * params.page_size,
        limit=params.page_size,
        sort_by=params.sort_by,
        sort_order=params.sort_order,
    )

    items = []
    for run in runs:
        summary_json = run.summary_json or {}
        source_metadata = _run_source_metadata(run)

        items.append(
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
    set_strategy_version_reference_run(
        db,
        version_id=version.id,
        run_id=run.id,
        user_id=user["id"],
    )

    return SaveDraftRunAsStrategyResponse(
        run_id=str(run.id),
        strategy_id=str(strategy.id),
        version_id=str(version.id),
    )


@router.post(
    "/{run_id}/sweep/variants/{variant_id}/promote",
    response_model=PromoteSweepVariantResponse,
)
def promote_sweep_variant_api(
    run_id: str,
    variant_id: str,
    req: PromoteSweepVariantRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    run = get_run_for_user(db, run_id, user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.run_type != "PARAMETER_SWEEP":
        raise HTTPException(status_code=400, detail="Only parameter sweep runs can promote variants")

    if run.status != "SUCCEEDED":
        raise HTTPException(
            status_code=400,
            detail="Only succeeded parameter sweep runs can promote variants",
        )

    variant = _find_sweep_variant(run, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Sweep variant not found")

    config = _get_sweep_variant_config(run, variant, variant_id)
    rank = _sweep_variant_rank(run, variant_id)

    change_note = (
        req.change_note
        or f"Promoted from parameter sweep run {_short_run_id(str(run.id))}, rank #{rank or 'unknown'}."
    )

    sweep_origin = _sweep_origin(run)

    if sweep_origin == "SAVED_STRATEGY":
        entitlements = enforce_strategy_history_access(db, user["id"])
        origin_strategy_id = _sweep_origin_strategy_id(run)
        if origin_strategy_id is None:
            raise HTTPException(status_code=404, detail="Strategy not found")

        strategy = get_strategy_for_user(db, origin_strategy_id, user["id"])
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if run.strategy_version is not None:
            config = normalize_strategy_version_identity_fields(
                strategy_name=strategy.name,
                config=config,
            )
            try:
                validate_strategy_version_identity(
                    current_config=run.strategy_version.config_json,
                    new_config=config,
                )
                validate_backtest_window(
                    config=config,
                    max_backtest_years=entitlements.max_backtest_years,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        derived_run = None
    else:
        existing_saved_run = find_saved_sweep_variant_run(
            db,
            user_id=user["id"],
            sweep_run_id=run.id,
            variant_id=variant_id,
        )
        if existing_saved_run is not None:
            set_strategy_version_reference_run(
                db,
                version_id=existing_saved_run.strategy_version_id,
                run_id=existing_saved_run.id,
                user_id=user["id"],
            )
            return PromoteSweepVariantResponse(
                run_id=str(run.id),
                variant_id=variant_id,
                strategy_id=str(existing_saved_run.strategy_id),
                version_id=str(existing_saved_run.strategy_version_id),
                derived_run_id=str(existing_saved_run.id),
            )

        enforce_strategy_create_access(db, user["id"])
        strategy = create_strategy(
            db,
            user["id"],
            req.name or _strategy_name_from_config(config, variant.get("variant_name")),
            req.description,
            "SIMULATION",
        )

    version = create_strategy_version(
        db,
        strategy.id,
        config,
        _hash_config(config),
        user["id"],
        change_note=change_note,
    )

    if sweep_origin == "STANDALONE":
        ranking_metric = (run.summary_json or {}).get("ranking_metric")
        derived_run = _create_sweep_variant_result_run(
            db,
            user_id=user["id"],
            sweep_run=run,
            variant_id=variant_id,
            variant=variant,
            rank=rank,
            ranking_metric=ranking_metric if isinstance(ranking_metric, str) else None,
            strategy_id=strategy.id,
            strategy_version_id=version.id,
            config=config,
        )
        set_strategy_version_reference_run(
            db,
            version_id=version.id,
            run_id=derived_run.id,
            user_id=user["id"],
        )
    else:
        ranking_metric = (run.summary_json or {}).get("ranking_metric")
        variant_config = normalize_strategy_version_identity_fields(
            strategy_name=strategy.name,
            config=_get_sweep_variant_config(run, variant, variant_id),
        )
        if _hash_config(config) == _hash_config(variant_config):
            derived_run = _create_sweep_variant_result_run(
                db,
                user_id=user["id"],
                sweep_run=run,
                variant_id=variant_id,
                variant=variant,
                rank=rank,
                ranking_metric=ranking_metric if isinstance(ranking_metric, str) else None,
                strategy_id=strategy.id,
                strategy_version_id=version.id,
                config=config,
            )
            set_strategy_version_reference_run(
                db,
                version_id=version.id,
                run_id=derived_run.id,
                user_id=user["id"],
            )

    return PromoteSweepVariantResponse(
        run_id=str(run.id),
        variant_id=variant_id,
        strategy_id=str(strategy.id),
        version_id=str(version.id),
        derived_run_id=str(derived_run.id) if derived_run is not None else None,
    )


@router.get(
    "/{run_id}/sweep/variants/{variant_id}",
    response_model=SweepVariantDetailResponse,
)
def get_sweep_variant_detail_api(
    run_id: str,
    variant_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    run = get_run_for_user(db, run_id, user["id"])
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.run_type != "PARAMETER_SWEEP":
        raise HTTPException(status_code=400, detail="Only parameter sweep runs have variants")

    variant = _find_sweep_variant(run, variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Sweep variant not found")

    config = _get_sweep_variant_config(run, variant, variant_id)
    variant = {**variant, "config": config}
    rank = _sweep_variant_rank(run, variant_id)
    ranking_metric = (run.summary_json or {}).get("ranking_metric")
    saved_run = None
    if _sweep_origin(run) == "STANDALONE":
        saved_run = find_saved_sweep_variant_run(
            db,
            user_id=user["id"],
            sweep_run_id=run.id,
            variant_id=variant_id,
        )

    return SweepVariantDetailResponse(
        run=_build_run_response(run),
        variant=variant,
        rank=rank or 0,
        ranking_metric=ranking_metric if isinstance(ranking_metric, str) else None,
        sweep_origin=_sweep_origin(run),
        saved_strategy_id=str(saved_run.strategy_id) if saved_run is not None else None,
        saved_version_id=str(saved_run.strategy_version_id) if saved_run is not None else None,
        saved_run_id=str(saved_run.id) if saved_run is not None else None,
        chart_data=_load_variant_chart_data(variant),
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

    if (run.request_payload or {}).get("source") == "sweep_variant_save" and not run.artifact_manifest_json:
        return RunDashboardResponse(
            run=run_response,
            chart_data=RunChartDataResponse(
                run_id=str(run.id),
                equity_curve=[],
                drawdown_curve=[],
                monthly_returns=[],
                sleeve_equity_curve=[],
                sleeve_weight_curve=[],
                trade_markers=[],
            ),
        )

    if not run.artifact_manifest_json:
        raise HTTPException(status_code=404, detail="Run artifacts not found")

    if run.run_type == "PARAMETER_SWEEP":
        return RunDashboardResponse(
            run=run_response,
            chart_data=RunChartDataResponse(
                run_id=str(run.id),
                equity_curve=[],
                drawdown_curve=[],
                monthly_returns=[],
                sleeve_equity_curve=[],
                sleeve_weight_curve=[],
                trade_markers=[],
            ),
        )

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
