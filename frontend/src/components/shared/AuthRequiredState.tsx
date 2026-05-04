import { useEffect, useState } from 'react';

import { useAppAuth } from '../../auth/AppAuthProvider';
import { clearAccessToken, getDevelopmentAccessToken } from '../../lib/authToken';

interface AuthRequiredStateProps {
  errorMessage?: string | null;
  loading?: boolean;
  onRetry?: () => void;
}

export function AuthRequiredState({
  errorMessage,
  loading = false,
  onRetry
}: AuthRequiredStateProps) {
  const auth = useAppAuth();
  const [hasSavedToken, setHasSavedToken] = useState(() => Boolean(getDevelopmentAccessToken()));

  useEffect(() => {
    setHasSavedToken(Boolean(getDevelopmentAccessToken()));
  }, [errorMessage]);

  function handleClearToken() {
    clearAccessToken();
    setHasSavedToken(false);
  }

  return (
    <section className="mx-auto flex min-h-[58vh] w-full max-w-3xl items-center justify-center py-10">
      <div className="app-card w-full rounded-3xl border p-8 app-shadow-soft">
        <div className="flex flex-col gap-6 md:flex-row md:items-start">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border app-surface-soft app-accent">
            <span className="text-xl font-semibold" aria-hidden="true">
              !
            </span>
          </div>

          <div className="min-w-0 flex-1">
            <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.26em]">
              Authentication
            </p>
            <h2 className="mt-2 text-2xl font-semibold app-title">Sign-in required</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 app-text-muted">
              This beta environment requires an authenticated account.
            </p>
            {auth.isAuth0Mode ? (
              <p className="mt-2 max-w-2xl text-sm leading-6 app-text-muted">
                Sign in with your beta account to continue. If access was just granted, retry after signing in.
              </p>
            ) : (
              <p className="mt-2 max-w-2xl text-sm leading-6 app-text-muted">
                If you are testing locally, use <code className="app-code rounded px-1.5 py-0.5">ENV=local</code>{' '}
                and <code className="app-code rounded px-1.5 py-0.5">AUTH_MODE=dev</code>.
              </p>
            )}

            {errorMessage ? (
              <div className="app-alert-warning mt-5 rounded-2xl px-4 py-3 text-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.18em]">Backend response</p>
                <p className="mt-1 break-words">{errorMessage}</p>
              </div>
            ) : null}

            <div className="mt-6 flex flex-wrap items-center gap-3">
              {auth.isAuth0Mode && !auth.isAuthenticated ? (
                <button
                  type="button"
                  onClick={() => {
                    void auth.login();
                  }}
                  disabled={auth.isLoading}
                  className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {auth.isLoading ? 'Checking...' : 'Sign in'}
                </button>
              ) : null}

              {auth.isAuth0Mode && auth.isAuthenticated ? (
                <button
                  type="button"
                  onClick={() => {
                    void auth.logout();
                  }}
                  className="app-button-secondary rounded-xl px-4 py-2 text-sm font-semibold transition"
                >
                  Sign out
                </button>
              ) : null}

              {hasSavedToken ? (
                <button
                  type="button"
                  onClick={handleClearToken}
                  className="app-button-secondary rounded-xl px-4 py-2 text-sm font-semibold transition"
                >
                  Clear saved token
                </button>
              ) : null}

              {onRetry ? (
                <button
                  type="button"
                  onClick={onRetry}
                  disabled={loading}
                  className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading ? 'Retrying...' : 'Retry'}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
