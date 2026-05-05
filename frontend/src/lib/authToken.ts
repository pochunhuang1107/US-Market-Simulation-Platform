export const ACCESS_TOKEN_STORAGE_KEY = 'market_simulator_access_token';

type MaybePromise<T> = T | Promise<T>;

export type AccessTokenProvider = () => MaybePromise<string | null>;
export type AccessTokenUnavailableReason = 'loading' | 'unauthenticated' | 'failed';

export class AccessTokenUnavailableError extends Error {
  reason: AccessTokenUnavailableReason;

  constructor(reason: AccessTokenUnavailableReason, message: string) {
    super(message);
    this.name = 'AccessTokenUnavailableError';
    this.reason = reason;
  }
}

function readStoredAccessToken(): string | null {
  if (typeof window === 'undefined') return null;

  try {
    const token = window.localStorage.getItem(ACCESS_TOKEN_STORAGE_KEY);
    return token?.trim() ? token : null;
  } catch {
    return null;
  }
}

let accessTokenProvider: AccessTokenProvider = readStoredAccessToken;

export async function getAccessToken(): Promise<string | null> {
  const token = await accessTokenProvider();
  return token?.trim() ? token : null;
}

export function isAccessTokenUnavailableError(error: unknown): error is AccessTokenUnavailableError {
  return error instanceof AccessTokenUnavailableError;
}

export function getDevelopmentAccessToken(): string | null {
  return readStoredAccessToken();
}

export function setAccessTokenProvider(provider: AccessTokenProvider): void {
  accessTokenProvider = provider;
}

export function resetAccessTokenProvider(): void {
  accessTokenProvider = readStoredAccessToken;
}

export function setAccessTokenForDevelopment(token: string | null): void {
  if (typeof window === 'undefined') return;

  if (!token?.trim()) {
    clearAccessToken();
    return;
  }

  window.localStorage.setItem(ACCESS_TOKEN_STORAGE_KEY, token);
}

export function clearAccessToken(): void {
  if (typeof window === 'undefined') return;

  window.localStorage.removeItem(ACCESS_TOKEN_STORAGE_KEY);
}
