import { createContext, useContext, useEffect, useLayoutEffect, useMemo, type ReactNode } from 'react';
import { Auth0Provider, useAuth0 } from '@auth0/auth0-react';

import {
  AccessTokenUnavailableError,
  getDevelopmentAccessToken,
  resetAccessTokenProvider,
  setAccessTokenProvider
} from '../lib/authToken';

type AuthProviderMode = 'auth0' | 'dev';
type Auth0CacheLocation = 'memory' | 'localstorage';

interface AppAuthContextValue {
  mode: AuthProviderMode;
  isAuth0Mode: boolean;
  isConfigured: boolean;
  isLoading: boolean;
  isAuthenticated: boolean;
  userLabel: string | null;
  login: () => Promise<void>;
  logout: () => Promise<void>;
}

const rawAuthProvider = import.meta.env.VITE_AUTH_PROVIDER?.trim().toLowerCase();
const authProviderMode: AuthProviderMode = rawAuthProvider === 'auth0' ? 'auth0' : 'dev';

const auth0Domain = import.meta.env.VITE_AUTH0_DOMAIN?.trim() ?? '';
const auth0ClientId = import.meta.env.VITE_AUTH0_CLIENT_ID?.trim() ?? '';
const auth0Audience = import.meta.env.VITE_AUTH0_AUDIENCE?.trim() ?? '';
const rawAuth0CacheLocation = import.meta.env.VITE_AUTH0_CACHE_LOCATION?.trim().toLowerCase();
const auth0CacheLocation: Auth0CacheLocation = rawAuth0CacheLocation === 'localstorage' ? 'localstorage' : 'memory';
const auth0UseRefreshTokens = import.meta.env.VITE_AUTH0_USE_REFRESH_TOKENS?.trim().toLowerCase() === 'true';

function getRedirectUri(): string {
  const configuredRedirectUri = import.meta.env.VITE_AUTH0_REDIRECT_URI?.trim();
  if (configuredRedirectUri) return configuredRedirectUri;

  if (typeof window === 'undefined') return '';
  return window.location.origin;
}

function getReturnToPath(): string {
  if (typeof window === 'undefined') return '/';
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

const defaultContextValue: AppAuthContextValue = {
  mode: authProviderMode,
  isAuth0Mode: authProviderMode === 'auth0',
  isConfigured: authProviderMode !== 'auth0' || Boolean(auth0Domain && auth0ClientId && auth0Audience),
  isLoading: false,
  isAuthenticated: false,
  userLabel: null,
  login: async () => undefined,
  logout: async () => undefined
};

const AppAuthContext = createContext<AppAuthContextValue>(defaultContextValue);

export function useAppAuth(): AppAuthContextValue {
  return useContext(AppAuthContext);
}

function formatTokenError(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : 'Unable to acquire an Auth0 access token.';
}

function DevAuthProvider({ children }: { children: ReactNode }) {
  const value = useMemo<AppAuthContextValue>(
    () => ({
      ...defaultContextValue,
      mode: 'dev',
      isAuth0Mode: false,
      isConfigured: true
    }),
    []
  );

  useEffect(() => {
    resetAccessTokenProvider();
  }, []);

  return <AppAuthContext.Provider value={value}>{children}</AppAuthContext.Provider>;
}

function Auth0RuntimeProvider({ children }: { children: ReactNode }) {
  const {
    getAccessTokenSilently,
    isAuthenticated,
    isLoading,
    loginWithRedirect,
    logout,
    user
  } = useAuth0();

  useLayoutEffect(() => {
    if (isLoading) {
      setAccessTokenProvider(() => {
        throw new AccessTokenUnavailableError('loading', 'Restoring session...');
      });
      return () => {
        resetAccessTokenProvider();
      };
    }

    if (!isAuthenticated) {
      setAccessTokenProvider(() => {
        const developmentToken = getDevelopmentAccessToken();
        if (developmentToken) return developmentToken;

        throw new AccessTokenUnavailableError('unauthenticated', 'Sign in required.');
      });
      return () => {
        resetAccessTokenProvider();
      };
    }

    setAccessTokenProvider(async () => {
      try {
        return await getAccessTokenSilently({
          authorizationParams: {
            audience: auth0Audience
          }
        });
      } catch (tokenError) {
        const developmentToken = getDevelopmentAccessToken();
        if (developmentToken) return developmentToken;

        throw new AccessTokenUnavailableError(
          'failed',
          formatTokenError(tokenError)
        );
      }
    });

    return () => {
      resetAccessTokenProvider();
    };
  }, [getAccessTokenSilently, isAuthenticated, isLoading]);

  const value = useMemo<AppAuthContextValue>(
    () => ({
      mode: 'auth0',
      isAuth0Mode: true,
      isConfigured: true,
      isLoading,
      isAuthenticated,
      userLabel: user?.name ?? user?.email ?? null,
      login: async () => {
        await loginWithRedirect({
          appState: {
            returnTo: getReturnToPath()
          },
          authorizationParams: {
            audience: auth0Audience
          }
        });
      },
      logout: async () => {
        await logout({
          logoutParams: {
            returnTo: typeof window === 'undefined' ? undefined : window.location.origin
          }
        });
      }
    }),
    [isAuthenticated, isLoading, loginWithRedirect, logout, user?.email, user?.name]
  );

  return <AppAuthContext.Provider value={value}>{children}</AppAuthContext.Provider>;
}

function Auth0ConfigurationProvider() {
  useEffect(() => {
    setAccessTokenProvider(() => null);
    return () => {
      resetAccessTokenProvider();
    };
  }, []);

  return (
    <AppAuthContext.Provider value={{ ...defaultContextValue, mode: 'auth0', isAuth0Mode: true, isConfigured: false }}>
      <Auth0ConfigurationError />
    </AppAuthContext.Provider>
  );
}

function Auth0ConfigurationError() {
  return (
    <div className="app-shell min-h-screen">
      <main className="mx-auto flex min-h-screen max-w-3xl items-center px-6 py-10">
        <section className="app-card w-full rounded-3xl border p-8 app-shadow-soft">
          <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.26em]">
            Authentication
          </p>
          <h1 className="mt-2 text-2xl font-semibold app-title">Auth0 is not configured</h1>
          <p className="mt-3 text-sm leading-6 app-text-muted">
            Set <code className="app-code rounded px-1.5 py-0.5">VITE_AUTH0_DOMAIN</code>,{' '}
            <code className="app-code rounded px-1.5 py-0.5">VITE_AUTH0_CLIENT_ID</code>, and{' '}
            <code className="app-code rounded px-1.5 py-0.5">VITE_AUTH0_AUDIENCE</code>, or use{' '}
            <code className="app-code rounded px-1.5 py-0.5">VITE_AUTH_PROVIDER=dev</code> for local
            development.
          </p>
        </section>
      </main>
    </div>
  );
}

export function AppAuthProvider({ children }: { children: ReactNode }) {
  if (authProviderMode !== 'auth0') {
    return <DevAuthProvider>{children}</DevAuthProvider>;
  }

  if (!auth0Domain || !auth0ClientId || !auth0Audience) {
    return <Auth0ConfigurationProvider />;
  }

  return (
    <Auth0Provider
      domain={auth0Domain}
      clientId={auth0ClientId}
      cacheLocation={auth0CacheLocation}
      useRefreshTokens={auth0UseRefreshTokens}
      authorizationParams={{
        audience: auth0Audience,
        redirect_uri: getRedirectUri()
      }}
      onRedirectCallback={(appState) => {
        const returnTo = appState?.returnTo ?? '/';
        window.history.replaceState({}, document.title, returnTo);
      }}
    >
      <Auth0RuntimeProvider>{children}</Auth0RuntimeProvider>
    </Auth0Provider>
  );
}
