import type { MouseEvent } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { useAppAuth } from '../../auth/AppAuthProvider';
import { fetchMeEntitlements, isUnauthorizedError } from '../../lib/api';
import { useTheme } from '../../theme';
import { AuthRequiredState } from '../shared/AuthRequiredState';

const navItems = [
  { to: '/', label: 'Home', end: true },
  { to: '/gallery', label: 'Gallery', end: true },
  { to: '/runs', label: 'Results', end: true },
  { to: '/compare', label: 'Compare', end: true },
  { to: '/strategies', label: 'Library', end: false },
  { to: '/runs/new', label: 'Manual Run', end: true }
];

function getShortUserLabel(userLabel: string | null): string {
  const normalizedLabel = userLabel?.trim();
  if (!normalizedLabel) return 'Signed in';

  const emailName = normalizedLabel.includes('@') ? normalizedLabel.split('@')[0] : normalizedLabel;
  return emailName.split(/\s+/)[0] || normalizedLabel;
}

export function AppShell() {
  const auth = useAppAuth();
  const { themeMode, setThemeMode } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const [authRequiredMessage, setAuthRequiredMessage] = useState<string | null>(null);
  const [isRetryingAuth, setIsRetryingAuth] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const authCheckRequestIdRef = useRef(0);
  const userMenuRef = useRef<HTMLDivElement | null>(null);

  const checkAuthRequired = useCallback(async (shouldApply: () => boolean = () => true) => {
    const requestId = authCheckRequestIdRef.current + 1;
    authCheckRequestIdRef.current = requestId;
    const shouldApplyLatest = () => shouldApply() && authCheckRequestIdRef.current === requestId;

    setIsRetryingAuth(true);

    try {
      await fetchMeEntitlements();

      if (!shouldApplyLatest()) return;
      setAuthRequiredMessage(null);
    } catch (error) {
      if (!shouldApplyLatest()) return;

      if (isUnauthorizedError(error)) {
        setAuthRequiredMessage(error.message);
      } else {
        setAuthRequiredMessage(null);
      }
    } finally {
      if (shouldApplyLatest()) {
        setIsRetryingAuth(false);
      }
    }
  }, []);

  useEffect(() => {
    let isMounted = true;

    if (auth.isAuth0Mode && (auth.isLoading || !auth.isAuthenticated)) {
      authCheckRequestIdRef.current += 1;
      setAuthRequiredMessage(null);
      setIsRetryingAuth(false);
      return () => {
        isMounted = false;
      };
    }

    void checkAuthRequired(() => isMounted);

    return () => {
      isMounted = false;
    };
  }, [auth.isAuthenticated, auth.isAuth0Mode, auth.isLoading, checkAuthRequired]);

  useEffect(() => {
    if (!isUserMenuOpen) return;

    function handlePointerDown(event: globalThis.MouseEvent) {
      if (userMenuRef.current?.contains(event.target as Node)) return;
      setIsUserMenuOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsUserMenuOpen(false);
      }
    }

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isUserMenuOpen]);

  useEffect(() => {
    if (!auth.isAuthenticated) {
      setIsUserMenuOpen(false);
    }
  }, [auth.isAuthenticated]);

  function handleNavClick(event: MouseEvent<HTMLAnchorElement>, to: string) {
    if (to === '/' && (location.pathname === '/' || location.pathname === '/chat')) {
      event.preventDefault();
      navigate('/', {
        replace: location.search === '',
        state: { homeResetKey: Date.now() }
      });
      return;
    }

    if (to !== '/compare' || location.pathname !== '/compare') return;

    event.preventDefault();
    navigate('/compare', {
      replace: location.search === '',
      state: { compareResetKey: Date.now() }
    });
  }

  const authButtonLabel = auth.isLoading ? 'Checking...' : auth.isAuthenticated ? 'Sign out' : 'Sign in';
  const userInitial = auth.userLabel?.trim().charAt(0).toUpperCase() ?? '?';
  const shortUserLabel = getShortUserLabel(auth.userLabel);
  const fullUserLabel = auth.userLabel ?? 'Signed in';

  return (
    <div className="app-shell min-h-screen">
      <header className="app-header sticky top-0 z-30 border-b backdrop-blur">
        <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 px-6 py-4 lg:grid-cols-[minmax(160px,190px)_minmax(0,1fr)_auto] lg:items-center lg:gap-4 lg:px-8 xl:grid-cols-[minmax(180px,220px)_minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.22em]">US Market</p>
            <h1 className="mt-1 text-lg font-semibold app-title sm:text-xl">Research Workspace</h1>
          </div>

          <nav className="app-nav flex min-w-0 flex-wrap items-center gap-1 rounded-2xl border p-1.5 sm:gap-1.5 lg:flex-nowrap lg:justify-self-center lg:overflow-hidden">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={(event) => handleNavClick(event, item.to)}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-xl px-3 py-2 text-sm font-medium transition ${
                    isActive ? 'app-nav-link-active' : 'app-nav-link'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex min-w-0 flex-wrap items-center gap-2 lg:flex-nowrap lg:justify-end">
            <label className="app-surface-soft flex shrink-0 items-center gap-2 rounded-2xl border px-2.5 py-2 text-xs font-medium app-text-muted xl:px-3">
              <span className="hidden xl:inline">Theme</span>
              <select
                value={themeMode}
                onChange={(event) => setThemeMode(event.target.value as 'system' | 'dark' | 'light')}
                className="app-input rounded-xl border px-2.5 py-1.5 text-xs font-semibold outline-none"
                aria-label="Theme mode"
              >
                <option value="system">Auto</option>
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </label>

            {auth.isAuth0Mode ? (
              <div className="relative flex min-w-0 max-w-full items-center" ref={userMenuRef}>
                {auth.isAuthenticated ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setIsUserMenuOpen((isOpen) => !isOpen)}
                      className="app-surface-soft flex min-w-0 items-center gap-1.5 rounded-full border py-1 pl-1 pr-2 transition hover:opacity-90"
                      aria-haspopup="menu"
                      aria-expanded={isUserMenuOpen}
                    >
                      <span
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold app-button-primary"
                        aria-hidden="true"
                      >
                        {userInitial}
                      </span>
                      <span className="max-w-20 truncate text-sm font-semibold app-title xl:max-w-28" title={fullUserLabel}>
                        {shortUserLabel}
                      </span>
                      <span className="text-xs app-text-muted" aria-hidden="true">
                        ▾
                      </span>
                    </button>

                    {isUserMenuOpen ? (
                      <div
                        className="app-card absolute right-0 top-[calc(100%+0.5rem)] z-40 w-64 rounded-2xl border p-2 app-shadow-soft"
                        role="menu"
                      >
                        <div className="px-3 py-2">
                          <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] app-text-soft">
                            Signed in as
                          </p>
                          <p className="mt-1 break-words text-sm font-semibold app-title">{fullUserLabel}</p>
                        </div>
                        <div className="my-1 border-t app-divider" />
                        <button
                          type="button"
                          onClick={() => {
                            setIsUserMenuOpen(false);
                            void auth.logout();
                          }}
                          className="app-button-secondary w-full rounded-xl px-3 py-2 text-left text-sm font-semibold transition"
                          role="menuitem"
                        >
                          Sign out
                        </button>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      void auth.login();
                    }}
                    disabled={auth.isLoading}
                    className="app-button-primary shrink-0 rounded-full px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60"
                    aria-label={authButtonLabel}
                  >
                    {auth.isLoading ? 'Checking...' : 'Sign in'}
                  </button>
                )}
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8 lg:px-8">
        {auth.isAuth0Mode && !auth.isLoading && !auth.isAuthenticated ? (
          <AuthRequiredState />
        ) : authRequiredMessage ? (
          <AuthRequiredState
            errorMessage={authRequiredMessage}
            loading={isRetryingAuth}
            onRetry={() => {
              void checkAuthRequired();
            }}
          />
        ) : (
          <Outlet />
        )}
      </main>
    </div>
  );
}
