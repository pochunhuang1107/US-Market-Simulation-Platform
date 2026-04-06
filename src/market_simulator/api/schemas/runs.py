from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, field_serializer


class CreateRunRequest(BaseModel):
    strategy_id: str
    strategy_version_id: str | None = None
    run_type: str
    executor_type: str
    request_payload: dict[str, Any]
    max_attempts: int = Field(default=3, ge=1, le=10)


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    strategy_id: UUID | None
    strategy_version_id: UUID | None

    run_type: str
    executor_type: str
    status: str

    request_payload: dict[str, Any]
    summary_json: dict[str, Any] | None
    artifact_manifest_json: dict[str, Any] | None

    artifact_dir: str | None
    artifact_storage_type: str
    artifact_root_uri: str | None

    error_message: str | None

    is_daily_tracking_run: bool
    parent_run_id: UUID | None

    queued_at: datetime | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    leased_until: datetime | None
    finished_at: datetime | None

    attempt_count: int
    max_attempts: int
    worker_id: str | None
    progress_pct: int
    progress_message: str | None

    created_at: datetime
    updated_at: datetime

    # ✅ convert UUID → string for API output
    @field_serializer(
        "id",
        "user_id",
        "strategy_id",
        "strategy_version_id",
        "parent_run_id",
    )
    def serialize_uuid(self, value: UUID | None):
        return str(value) if value is not None else None


class RunListResponse(BaseModel):
    items: list[RunResponse]


class RunActionResponse(BaseModel):
    run_id: str
    status: str
    message: str


class RecoverStaleRunsResponse(BaseModel):
    recovered_count: int
    run_ids: list[str]