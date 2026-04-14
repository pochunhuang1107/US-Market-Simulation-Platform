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
  status?: string;
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
}

export interface RunComparisonCurvePoint {
  date: string;
  value: number;
}

export interface RunComparisonCurve {
  run_id: string;
  label: string;
  points: RunComparisonCurvePoint[];
}

export interface RunComparisonChartResponse {
  strategy_curves: RunComparisonCurve[];
  benchmark_curves: RunComparisonCurve[];
  strategy_drawdown_curves: RunComparisonCurve[];
  benchmark_drawdown_curves: RunComparisonCurve[];
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
  strategy_id: string;
  strategy_version_id?: string | null;
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

export interface StrategyBuilderGenerateResponse {
  config: Record<string, unknown>;
  summary: string;
  warnings: string[];
  changes: string[];
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
}

export interface MeUsageResponse {
  runs_created_today: number;
  daily_runs_remaining: number;
  saved_strategies: number;
  saved_strategies_remaining: number;
  tracked_strategies: number;
  tracked_strategies_remaining: number;
}

export interface MeEntitlementsResponse {
  user: MeUserResponse;
  plan: MePlanResponse;
  features: MeFeatureFlagsResponse;
  limits: MeUsageLimitsResponse;
  usage: MeUsageResponse;
}