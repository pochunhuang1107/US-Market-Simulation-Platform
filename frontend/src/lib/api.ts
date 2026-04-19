import type {
  CreateRunRequest,
  CreateStrategyRequest,
  CreateStrategyResponse,
  CreateStrategyVersionRequest,
  CreateStrategyVersionResponse,
  MeEntitlementsResponse,
  RunActionResponse,
  RunComparisonChartResponse,
  RunComparisonResponse,
  RunDashboardListResponse,
  RunDashboardResponse,
  RunResponse,
  RunsDashboardQuery,
  SaveDraftRunAsStrategyRequest,
  SaveDraftRunAsStrategyResponse,
  StrategyBuilderGenerateRequest,
  StrategyBuilderGenerateResponse,
  StrategyDashboardResponse,
  StrategyListItem
} from '../types/api';

type ErrorBody = {
  detail?: unknown;
  message?: unknown;
  error?: unknown;
};

export class ApiRequestError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = 'ApiRequestError';
    this.status = status;
    this.body = body;
  }
}

function formatErrorBody(body: ErrorBody): string {
  if (typeof body.detail === 'string') return body.detail;
  if (typeof body.message === 'string') return body.message;
  if (typeof body.error === 'string') return body.error;

  if (body.detail !== undefined) {
    try {
      return JSON.stringify(body.detail, null, 2);
    } catch {
      return String(body.detail);
    }
  }

  try {
    return JSON.stringify(body, null, 2);
  } catch {
    return 'Request failed.';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {})
    },
    ...init
  });

  const contentType = response.headers.get('content-type') ?? '';
  const isJson = contentType.includes('application/json');

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    let errorBody: unknown = null;

    try {
      if (isJson) {
        const body = (await response.json()) as ErrorBody;
        errorBody = body;
        detail = formatErrorBody(body);
      } else {
        const text = await response.text();
        errorBody = text;
        if (text.trim()) {
          detail = text;
        }
      }
    } catch {
      // ignore
    }

    throw new ApiRequestError(detail, response.status, errorBody);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  if (isJson) {
    return (await response.json()) as T;
  }

  return (await response.text()) as T;
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

export async function fetchMeEntitlements(): Promise<MeEntitlementsResponse> {
  return request<MeEntitlementsResponse>('/api/me/entitlements');
}

export async function fetchRunsDashboard(query: RunsDashboardQuery): Promise<RunDashboardListResponse> {
  return request<RunDashboardListResponse>(
    `/api/runs/dashboard${buildQueryString(query as Record<string, string | number | null | undefined>)}`
  );
}

export async function fetchRun(runId: string): Promise<RunResponse> {
  return request<RunResponse>(`/api/runs/${runId}`);
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

export async function saveDraftRunAsStrategy(
  runId: string,
  payload: SaveDraftRunAsStrategyRequest
): Promise<SaveDraftRunAsStrategyResponse> {
  return request<SaveDraftRunAsStrategyResponse>(`/api/runs/${runId}/save-strategy`, {
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

export async function generateStrategyDraft(
  payload: StrategyBuilderGenerateRequest
): Promise<StrategyBuilderGenerateResponse> {
  return request<StrategyBuilderGenerateResponse>('/api/strategy-builder/generate', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function enqueueRun(runId: string): Promise<RunActionResponse> {
  return request<RunActionResponse>(`/api/runs/${runId}/enqueue`, {
    method: 'POST'
  });
}