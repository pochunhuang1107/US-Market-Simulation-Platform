import { useEffect, useState } from 'react';

import { useAppAuth } from '../../auth/AppAuthProvider';
import { clearAccessToken, getDevelopmentAccessToken } from '../../lib/authToken';

interface AuthRequiredStateProps {
  errorMessage?: string | null;
  loading?: boolean;
  onRetry?: () => void;
  returnTo?: string;
}

export function AuthRequiredState({
  errorMessage,
  loading = false,
  onRetry,
  returnTo
}: AuthRequiredStateProps) {
  const auth = useAppAuth();
  const [hasSavedToken, setHasSavedToken] = useState(() => Boolean(getDevelopmentAccessToken()));
  const isSignedInAuth0Error = auth.isAuth0Mode && auth.isAuthenticated && Boolean(errorMessage);
  const title = 'Sign in to continue';
  const intro = isSignedInAuth0Error
    ? 'Your Auth0 account is signed in, but it has not been provisioned for this workspace yet.'
    : auth.isAuth0Mode
      ? 'This beta workspace requires Auth0 sign-in before the research tools can load.'
      : 'The API needs a local development identity before it can load account entitlements.';
  const guidance = isSignedInAuth0Error
    ? 'If access was just granted, retry the account check. Otherwise, sign out and use the beta account that was provisioned for this workspace.'
    : auth.isAuth0Mode
      ? 'Use the beta account that was invited or provisioned for this workspace.'
      : 'For local development, run the backend with dev auth enabled. Saved manual tokens are only local testing helpers.';

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
            <h2 className="mt-2 text-2xl font-semibold app-title">{title}</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 app-text-muted">
              {intro}
            </p>
            <p className="mt-2 max-w-2xl text-sm leading-6 app-text-muted">{guidance}</p>

            {errorMessage ? (
              <div className="app-alert-warning mt-5 rounded-2xl px-4 py-3 text-sm">
                <p className="text-xs font-semibold uppercase tracking-[0.18em]">API detail</p>
                <p className="mt-1 break-words">{errorMessage}</p>
              </div>
            ) : null}

            <div className="mt-6 flex flex-wrap items-center gap-3">
              {auth.isAuth0Mode && !auth.isAuthenticated ? (
                <button
                  type="button"
                  onClick={() => {
                    void auth.login(returnTo);
                  }}
                  disabled={auth.isLoading}
                  className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {auth.isLoading ? 'Checking...' : 'Sign in with Auth0'}
                </button>
              ) : null}

              {onRetry ? (
                <button
                  type="button"
                  onClick={onRetry}
                  disabled={loading}
                  className="app-button-primary rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading ? 'Retrying...' : 'Retry account check'}
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
                  Clear local token
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
