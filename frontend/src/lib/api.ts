import type {
  CreateRunRequest,
  CreateStrategyRequest,
  CreateStrategyResponse,
  CreateStrategyVersionRequest,
  CreateStrategyVersionResponse,
  RunActionResponse,
  RunComparisonChartResponse,
  RunComparisonResponse,
  RunDashboardListResponse,
  RunDashboardResponse,
  RunResponse,
  RunsDashboardQuery,
  StrategyDashboardResponse,
  StrategyListItem
} from '../types/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {})
    },
    ...init
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

function buildQueryString(query: Record<string, string | number | undefined | null>): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    params.set(key, String(value));
  });
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

export async function fetchRunsDashboard(query: RunsDashboardQuery): Promise<RunDashboardListResponse> {
  return request<RunDashboardListResponse>(
    `/api/runs/dashboard${buildQueryString(query as Record<string, string | number | null | undefined>)}`
  );
}

export async function fetchRunDashboard(runId: string): Promise<RunDashboardResponse> {
  return request<RunDashboardResponse>(`/api/runs/${runId}/dashboard`);
}

export async function fetchStrategies(): Promise<StrategyListItem[]> {
  return request<StrategyListItem[]>('/api/strategies');
}

export async function fetchStrategyDashboard(strategyId: string): Promise<StrategyDashboardResponse> {
  return request<StrategyDashboardResponse>(`/api/strategies/${strategyId}/dashboard`);
}

export async function fetchRunComparison(runIds: string[]): Promise<RunComparisonResponse> {
  return request<RunComparisonResponse>(
    `/api/runs/compare${buildQueryString({ run_ids: runIds.join(',') })}`
  );
}

export async function fetchRunComparisonChart(runIds: string[]): Promise<RunComparisonChartResponse> {
  return request<RunComparisonChartResponse>(
    `/api/runs/compare/chart${buildQueryString({ run_ids: runIds.join(',') })}`
  );
}

export async function createRun(payload: CreateRunRequest): Promise<RunResponse> {
  return request<RunResponse>('/api/runs', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function createStrategy(payload: CreateStrategyRequest): Promise<CreateStrategyResponse> {
  return request<CreateStrategyResponse>('/api/strategies', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function createStrategyVersion(
  strategyId: string,
  payload: CreateStrategyVersionRequest
): Promise<CreateStrategyVersionResponse> {
  return request<CreateStrategyVersionResponse>(`/api/strategies/${strategyId}/versions`, {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function enqueueRun(runId: string): Promise<RunActionResponse> {
  return request<RunActionResponse>(`/api/runs/${runId}/enqueue`, {
    method: 'POST'
  });
}