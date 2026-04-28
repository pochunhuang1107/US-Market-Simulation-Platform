export type Nullable<T> = T | null;

export interface StrategyListItem {
  id: string;
  user_id: string;
  name: string;
  description: Nullable<string>;
  strategy_type: string;
  visibility: string;
  status: string;
  current_version_id: Nullable<string>;
  created_at: string;
  updated_at: string;
}

export interface RunDashboardListItem {
  run_id: string;
  strategy_id: Nullable<string>;
  strategy_version_id: Nullable<string>;
  strategy_name: Nullable<string>;
  strategy_version_number: Nullable<number>;
  status: string;
  run_type: string;
  executor_type: string;
  created_at: string;
  finished_at: Nullable<string>;
  progress_pct: number;
  progress_message: Nullable<string>;
  artifact_storage_type: string;
  has_artifacts: boolean;
  total_return_pct: Nullable<number>;
  benchmark_return_pct: Nullable<number>;
  alpha_vs_benchmark_pct: Nullable<number>;
  cagr_pct: Nullable<number>;
  sharpe_ratio: Nullable<number>;
  max_drawdown_pct: Nullable<number>;
  trade_count: Nullable<number>;
  win_rate_pct: Nullable<number>;
}

export interface RunDashboardListResponse {
  items: RunDashboardListItem[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
}

export type RunSortBy = 'created_at' | 'finished_at' | 'status';
export type RunSortOrder = 'asc' | 'desc';

export interface RunsDashboardQuery {
  status?: string | string[];
  executor_type?: string;
  run_type?: string;
  strategy_id?: string;
  page?: number;
  page_size?: number;
  sort_by?: RunSortBy;
  sort_order?: RunSortOrder;
}

export interface RunExecutionSummary {
  duration_seconds: Nullable<number>;
  attempt_count: number;
  max_attempts: number;
  progress_pct: number;
  progress_message: Nullable<string>;
  is_terminal: boolean;
}

export interface RunArtifactSummary {
  artifact_dir: Nullable<string>;
  artifact_root_uri: Nullable<string>;
  artifact_storage_type: string;
  manifest: Nullable<Record<string, string>>;
  download_urls: Nullable<Record<string, string>>;
}

export interface RunResponse {
  id: string;
  user_id: string;
  strategy_id: Nullable<string>;
  strategy_version_id: Nullable<string>;
  strategy_name: Nullable<string>;
  strategy_version_number: Nullable<number>;
  run_type: string;
  executor_type: string;
  status: string;
  request_payload: Record<string, unknown>;
  summary_json: Nullable<Record<string, unknown>>;
  artifact_manifest_json: Nullable<Record<string, string>>;
  artifact_dir: Nullable<string>;
  artifact_storage_type: string;
  artifact_root_uri: Nullable<string>;
  error_message: Nullable<string>;
  is_daily_tracking_run: boolean;
  parent_run_id: Nullable<string>;
  queued_at: Nullable<string>;
  started_at: Nullable<string>;
  heartbeat_at: Nullable<string>;
  leased_until: Nullable<string>;
  finished_at: Nullable<string>;
  attempt_count: number;
  max_attempts: number;
  worker_id: Nullable<string>;
  progress_pct: number;
  progress_message: Nullable<string>;
  duration_seconds: Nullable<number>;
  artifacts: Nullable<Record<string, string>>;
  artifact_download_urls: Nullable<Record<string, string>>;
  is_terminal: Nullable<boolean>;
  execution: Nullable<RunExecutionSummary>;
  artifact_summary: Nullable<RunArtifactSummary>;
  created_at: string;
  updated_at: string;
}

export interface EquityCurvePoint {
  date: string;
  strategy_equity: number;
  benchmark_equity: Nullable<number>;
}

export interface DrawdownCurvePoint {
  date: string;
  strategy_drawdown_pct: number;
  benchmark_drawdown_pct: Nullable<number>;
}

export interface MonthlyReturnPoint {
  month: string;
  return_pct: number;
}

export interface SleeveEquityPoint {
  date: string;
  core_equity: Nullable<number>;
  overlay_equity: Nullable<number>;
}

export interface SleeveWeightPoint {
  date: string;
  core_weight_pct: Nullable<number>;
  overlay_weight_pct: Nullable<number>;
}

export interface TradeMarkerPoint {
  date: string;
  side: string;
  shares: Nullable<number>;
  price: Nullable<number>;
  reason: Nullable<string>;
}

export interface RunChartDataResponse {
  run_id: string;
  equity_curve: EquityCurvePoint[];
  drawdown_curve: DrawdownCurvePoint[];
  monthly_returns: MonthlyReturnPoint[];
  sleeve_equity_curve: SleeveEquityPoint[];
  sleeve_weight_curve: SleeveWeightPoint[];
  trade_markers: TradeMarkerPoint[];
}

export interface RunDashboardResponse {
  run: RunResponse;
  chart_data: RunChartDataResponse;
}

export interface SweepVariantDetailResponse {
  run: RunResponse;
  variant: Record<string, unknown>;
  rank: number;
  ranking_metric: Nullable<string>;
  chart_data: Nullable<RunChartDataResponse>;
}

export interface RunComparisonSummary {
  run_id: string;
  strategy_id: Nullable<string>;
  strategy_version_id: Nullable<string>;
  strategy_name: Nullable<string>;
  strategy_version_number: Nullable<number>;
  status: string;
  total_return_pct: Nullable<number>;
  benchmark_return_pct: Nullable<number>;
  alpha_vs_benchmark_pct: Nullable<number>;
  cagr_pct: Nullable<number>;
  sharpe_ratio: Nullable<number>;
  max_drawdown_pct: Nullable<number>;
  benchmark_max_drawdown_pct: Nullable<number>;
  trade_count: Nullable<number>;
  win_rate_pct: Nullable<number>;
}

export interface RunComparisonResponse {
  runs: RunComparisonSummary[];
  metadata: RunComparisonMetadata;
}

export interface RunComparisonWindow {
  run_id: string;
  start_date: Nullable<string>;
  end_date: Nullable<string>;
}

export interface RunComparisonMetadata {
  run_windows: RunComparisonWindow[];
  overlap_start: Nullable<string>;
  overlap_end: Nullable<string>;
  has_common_overlap: boolean;
  window_mode: 'FULL_PERIOD_METRICS' | 'COMMON_OVERLAP_METRICS';
  warning_message: Nullable<string>;
}

export interface RunComparisonCurvePoint {
  date: string;
  value: number;
}

export interface RunComparisonCurve {
  run_id: string;
  label: string;
  benchmark_label: Nullable<string>;
  points: RunComparisonCurvePoint[];
}

export interface RunComparisonChartResponse {
  strategy_curves: RunComparisonCurve[];
  benchmark_curves: RunComparisonCurve[];
  strategy_drawdown_curves: RunComparisonCurve[];
  benchmark_drawdown_curves: RunComparisonCurve[];
  chart_window_mode: 'FULL_PERIOD' | 'COMMON_OVERLAP';
  chart_overlap_start: Nullable<string>;
  chart_overlap_end: Nullable<string>;
}

export interface StrategyVersionSummary {
  id: string;
  strategy_id: string;
  version_number: number;
  config_json: Record<string, unknown>;
  config_hash: string;
  change_note: Nullable<string>;
  created_by_user_id: string;
  created_at: string;
  is_current: boolean;
}

export interface StrategyLatestPerformance {
  run_id: string;
  finished_at: Nullable<string>;
  total_return_pct: Nullable<number>;
  benchmark_return_pct: Nullable<number>;
  alpha_vs_benchmark_pct: Nullable<number>;
  cagr_pct: Nullable<number>;
  sharpe_ratio: Nullable<number>;
  max_drawdown_pct: Nullable<number>;
  benchmark_max_drawdown_pct: Nullable<number>;
  trade_count: Nullable<number>;
  win_rate_pct: Nullable<number>;
}

export interface StrategyDashboardResponse {
  strategy: StrategyListItem;
  versions: StrategyVersionSummary[];
  associated_runs: RunDashboardListItem[];
  total_runs: number;
  latest_run_id: Nullable<string>;
  latest_finished_at: Nullable<string>;
  latest_performance: Nullable<StrategyLatestPerformance>;
}

export type RunType = 'SIMULATION' | 'PORTFOLIO' | 'COMPARISON' | 'PARAMETER_SWEEP';

export interface CreateRunRequest {
  strategy_id?: string | null;
  strategy_version_id?: string | null;
  parent_run_id?: string | null;
  draft_config?: Record<string, unknown> | null;
  run_type: RunType;
  executor_type: string;
  request_payload: Record<string, unknown>;
  max_attempts: number;
}

export interface RunActionResponse {
  run_id: string;
  status: string;
  message: string;
}

export interface CreateStrategyRequest {
  name: string;
  description?: string | null;
  strategy_type: string;
  config: Record<string, unknown>;
}

export interface CreateStrategyResponse {
  strategy_id: string;
  version_id: string;
}

export interface CreateStrategyVersionRequest {
  config: Record<string, unknown>;
  change_note?: string | null;
}

export interface CreateStrategyVersionResponse {
  strategy_id: string;
  version_id: string;
}

export interface SaveDraftRunAsStrategyRequest {
  name: string;
  description?: string | null;
  strategy_type?: string;
}

export interface SaveDraftRunAsStrategyResponse {
  run_id: string;
  strategy_id: string;
  version_id: string;
}

export interface PromoteSweepVariantRequest {
  name?: string | null;
  description?: string | null;
  change_note?: string | null;
}

export interface PromoteSweepVariantResponse {
  run_id: string;
  variant_id: string;
  strategy_id: string;
  version_id: string;
}

export interface StrategyBuilderContext {
  strategy_id?: string | null;
  base_version_id?: string | null;
  mode?: string | null;
  current_config?: Record<string, unknown> | null;
}

export interface StrategyBuilderGenerateRequest {
  prompt: string;
  context?: StrategyBuilderContext | null;
}

export type StrategyBuilderResponseType =
  | 'ANSWER'
  | 'CREATE_DRAFT'
  | 'UPDATE_DRAFT'
  | 'VALIDATION_ERROR';

export type StrategyBuilderAnswerType =
  | 'SUPPORTED_SYMBOLS'
  | 'DATA_COVERAGE'
  | 'PLAN_LIMITS'
  | 'GENERAL';

export interface StrategyBuilderAnswerData {
  answer_type: StrategyBuilderAnswerType;
  supported_symbols: string[];
  supported_data_start?: string | null;
  supported_data_end?: string | null;
  max_backtest_years?: number | null;
}

export type StrategyBuilderValidationType =
  | 'UNSUPPORTED_SYMBOL'
  | 'DATA_COVERAGE'
  | 'PLAN_LIMIT'
  | 'INVALID_DATE_FORMAT'
  | 'UNSUPPORTED_EDIT'
  | 'GENERAL';

export interface StrategyBuilderValidationData {
  validation_type: StrategyBuilderValidationType;
  unsupported_symbols: string[];
  supported_data_start?: string | null;
  supported_data_end?: string | null;
  max_backtest_years?: number | null;
  suggested_action?: string | null;
}

export type StrategyBuilderGuidanceType =
  | 'NO_CHANGE'
  | 'UNSUPPORTED_EDIT_TARGET'
  | 'GENERAL_GUIDANCE';

export interface StrategyBuilderGuidanceData {
  guidance_type: StrategyBuilderGuidanceType;
  suggested_actions: string[];
}

export interface StrategyBuilderGenerateResponse {
  response_type: StrategyBuilderResponseType;
  message: string;
  config?: Record<string, unknown> | null;
  summary?: string | null;
  warnings: string[];
  assumptions: string[];
  changes: string[];
  answer_data?: StrategyBuilderAnswerData | null;
  validation_data?: StrategyBuilderValidationData | null;
  guidance_data?: StrategyBuilderGuidanceData | null;
}

export interface MeUserResponse {
  id: string;
  email: string | null;
  display_name: string | null;
  status: string;
}

export interface MePlanResponse {
  code: string;
  name: string;
  monthly_price_usd: number;
}

export interface MeFeatureFlagsResponse {
  allow_portfolio_runs: boolean;
  allow_comparison_runs: boolean;
  allow_parameter_sweeps: boolean;
  allow_ai_builder: boolean;
  allow_strategy_history: boolean;
}

export interface MeUsageLimitsResponse {
  daily_free_runs: number;
  max_saved_strategies: number;
  max_tracked_strategies: number;
  builder_prompt_daily_limit: number;
  builder_prompt_max_chars: number;
  max_backtest_years: number;
  max_comparison_runs: number;
}

export interface MeUsageResponse {
  runs_created_today: number;
  daily_runs_remaining: number;
  saved_strategies: number;
  saved_strategies_remaining: number;
  tracked_strategies: number;
  tracked_strategies_remaining: number;
  builder_prompts_used_today: number;
  builder_prompts_remaining_today: number;
}

export interface MeEntitlementsResponse {
  user: MeUserResponse;
  plan: MePlanResponse;
  features: MeFeatureFlagsResponse;
  limits: MeUsageLimitsResponse;
  usage: MeUsageResponse;
}
