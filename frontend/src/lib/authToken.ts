export const ACCESS_TOKEN_STORAGE_KEY = 'market_simulator_access_token';

export type AccessTokenProvider = () => string | null;

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

export function getAccessToken(): string | null {
  const token = accessTokenProvider();
  return token?.trim() ? token : null;
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
