from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ModelSignalFallbackResponse(BaseModel):
    type: Literal["cash", "asset"]
    symbol: str | None = None


class ModelSignalRecommendedDefaultsResponse(BaseModel):
    universe: list[str]
    ranking_field: str
    top_n: int
    signal_bucket_filter: list[str]
    fallback: ModelSignalFallbackResponse
    benchmark: str


class ModelSignalCatalogItemResponse(BaseModel):
    model_version: str
    display_name: str
    description: str
    family: str
    research_status: str
    supported_universe: list[str]
    default_universe: list[str]
    ranking_field: str
    allowed_ranking_fields: list[str]
    default_top_n: int
    default_signal_bucket_filter: list[str]
    default_fallback: ModelSignalFallbackResponse
    default_benchmark: str
    label_horizon_days: int
    feature_set_version: str
    artifact_path_setting: str
    artifact_path_hint: str
    risk_notes: list[str]
    limitations: list[str]
    recommended_use: str
    recommended_defaults: ModelSignalRecommendedDefaultsResponse
    created_at: str
    updated_at: str
    enabled: bool


class ModelSignalCatalogListResponse(BaseModel):
    models: list[ModelSignalCatalogItemResponse]


class ModelSignalCurrentRowResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    date: str
    selection_rank: int


class ModelSignalManifestResponse(BaseModel):
    model_version: str
    feature_set_version: str | None = None
    label_horizon_days: int | None = None
    latest_signal_date: str | None = None
    row_count: int | None = None
    symbol_count: int | None = None
    export_created_at: str | None = None
    candidate_id: str | None = None
    status: str | None = None
    warnings: list[str]


class ModelSignalCurrentPreviewResponse(BaseModel):
    model_version: str
    latest_signal_date: str
    selected_symbols: list[str]
    selected_rows: list[ModelSignalCurrentRowResponse]
    universe_symbol_count: int
    row_count_latest_date: int
    ranking_field: str
    top_n: int
    signal_bucket_filter: list[str]
    manifest_status: str | None = None
    manifest_warnings: list[str]
    export_created_at: str | None = None
    generated_at: str | None = None
    manifest: ModelSignalManifestResponse | None = None
