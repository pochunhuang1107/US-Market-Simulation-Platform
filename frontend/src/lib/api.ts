import type {
  CreateRunRequest,
  CreateStrategyRequest,
  CreateStrategyResponse,
  CreateStrategyVersionRequest,
  CreateStrategyVersionResponse,
  MeEntitlementsResponse,
  PromoteSweepVariantRequest,
  PromoteSweepVariantResponse,
  RunActionResponse,
  RunComparisonChartResponse,
  RunComparisonResponse,
  RunDashboardListResponse,
  RunDashboardResponse,
  RunProgressResponse,
  RunResponse,
  RunsDashboardQuery,
  SaveDraftRunAsStrategyRequest,
  SaveDraftRunAsStrategyResponse,
  SweepVariantDetailResponse,
  TradeEventContextResponse,
  StrategyBuilderGenerateRequest,
  StrategyBuilderGenerateResponse,
  StrategyDashboardResponse,
  StrategyListItem
} from '../types/api';
import { getAccessToken, isAccessTokenUnavailableError } from './authToken';

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

export function isUnauthorizedError(error: unknown): error is ApiRequestError {
  return error instanceof ApiRequestError && error.status === 401;
}

export function isArtifactUnavailableError(error: unknown): error is ApiRequestError {
  if (!(error instanceof ApiRequestError) || error.status !== 424) {
    return false;
  }

  const detail = (error.body as ErrorBody | null)?.detail;
  return (
    Boolean(detail) &&
    typeof detail === 'object' &&
    (detail as { code?: unknown }).code === 'ARTIFACT_UNAVAILABLE'
  );
}

export function artifactUnavailableMessage(error: ApiRequestError): string {
  const detail = (error.body as ErrorBody | null)?.detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) {
      return message;
    }
  }

  return 'Result artifacts are unavailable.';
}

function formatErrorBody(body: ErrorBody): string {
  if (typeof body.detail === 'string') return body.detail;
  if (typeof body.message === 'string') return body.message;
  if (typeof body.error === 'string') return body.error;

  if (body.detail !== undefined) {
    if (body.detail && typeof body.detail === 'object') {
      const detailMessage = (body.detail as { message?: unknown; guidance?: unknown }).message;
      const detailGuidance = (body.detail as { message?: unknown; guidance?: unknown }).guidance;
      if (typeof detailMessage === 'string' && detailMessage.trim()) {
        return typeof detailGuidance === 'string' && detailGuidance.trim()
          ? `${detailMessage} ${detailGuidance}`
          : detailMessage;
      }
    }

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
  const headers = new Headers(init?.headers);
  let token: string | null;

  try {
    token = await getAccessToken();
  } catch (error) {
    if (isAccessTokenUnavailableError(error)) {
      const status = error.reason === 'loading' ? 0 : 401;
      const reason =
        error.reason === 'loading'
          ? 'auth_loading'
          : error.reason === 'unauthenticated'
            ? 'auth_unauthenticated'
            : 'auth_token_unavailable';

      throw new ApiRequestError(error.message, status, {
        detail: error.message,
        reason
      });
    }

    throw error;
  }

  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(path, {
    ...init,
    headers
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

function buildQueryString(query: Record<string, string | number | string[] | undefined | null>): string {
  const params = new URLSearchParams();

  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== '') {
          params.append(key, item);
        }
      });
      return;
    }
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
    `/api/runs/dashboard${buildQueryString(query as Record<string, string | number | string[] | null | undefined>)}`
  );
}

export async function fetchRun(runId: string): Promise<RunResponse> {
  return request<RunResponse>(`/api/runs/${runId}`);
}

export async function fetchRunProgress(runId: string): Promise<RunProgressResponse> {
  return request<RunProgressResponse>(`/api/runs/${runId}/progress`);
}

export async function fetchRunDashboard(runId: string): Promise<RunDashboardResponse> {
  return request<RunDashboardResponse>(`/api/runs/${runId}/dashboard`);
}

export async function fetchRunTradeEvents(runId: string): Promise<TradeEventContextResponse> {
  return request<TradeEventContextResponse>(`/api/runs/${runId}/trade-events`);
}

export async function fetchSweepVariantTradeEvents(
  runId: string,
  variantId: string
): Promise<TradeEventContextResponse> {
  return request<TradeEventContextResponse>(`/api/runs/${runId}/sweep/variants/${variantId}/trade-events`);
}

export async function fetchSweepVariantDetail(
  runId: string,
  variantId: string
): Promise<SweepVariantDetailResponse> {
  return request<SweepVariantDetailResponse>(`/api/runs/${runId}/sweep/variants/${variantId}`);
}

export async function fetchStrategies(options?: { includeArchived?: boolean }): Promise<StrategyListItem[]> {
  return request<StrategyListItem[]>(
    `/api/strategies${buildQueryString({ include_archived: options?.includeArchived ? 'true' : undefined })}`
  );
}

export async function fetchStrategyDashboard(strategyId: string): Promise<StrategyDashboardResponse> {
  return request<StrategyDashboardResponse>(`/api/strategies/${strategyId}/dashboard`);
}

export async function archiveStrategy(strategyId: string): Promise<StrategyListItem> {
  return request<StrategyListItem>(`/api/strategies/${strategyId}/archive`, {
    method: 'POST'
  });
}

export async function restoreStrategy(strategyId: string): Promise<StrategyListItem> {
  return request<StrategyListItem>(`/api/strategies/${strategyId}/restore`, {
    method: 'POST'
  });
}

export async function fetchRunComparison(resultRefs: string[]): Promise<RunComparisonResponse> {
  return request<RunComparisonResponse>(
    `/api/runs/compare${buildQueryString({ results: resultRefs.join(',') })}`
  );
}

export async function fetchRunComparisonChart(resultRefs: string[]): Promise<RunComparisonChartResponse> {
  return request<RunComparisonChartResponse>(
    `/api/runs/compare/chart${buildQueryString({ results: resultRefs.join(',') })}`
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

export async function promoteSweepVariant(
  runId: string,
  variantId: string,
  payload: PromoteSweepVariantRequest
): Promise<PromoteSweepVariantResponse> {
  return request<PromoteSweepVariantResponse>(`/api/runs/${runId}/sweep/variants/${variantId}/promote`, {
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
