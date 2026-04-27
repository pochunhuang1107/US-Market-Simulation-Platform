import type { MouseEvent } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { useTheme } from '../../theme';

const navItems = [
  { to: '/', label: 'Home', end: true },
  { to: '/runs', label: 'Run History', end: true },
  { to: '/compare', label: 'Compare', end: true },
  { to: '/strategies', label: 'Strategy Library', end: false },
  { to: '/runs/new', label: 'Advanced Run', end: true }
];

export function AppShell() {
  const { themeMode, setThemeMode } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

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

  return (
    <div className="app-shell min-h-screen">
      <header className="app-header sticky top-0 z-30 border-b backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-4 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div>
            <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.26em]">
              US Market Strategy Platform
            </p>
            <h1 className="mt-1 text-xl font-semibold app-title">Strategy Research Workspace</h1>
          </div>

          <div className="flex items-center gap-3 self-start lg:self-auto">
            <nav className="app-nav flex flex-wrap items-center gap-2 rounded-2xl border p-1.5">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={(event) => handleNavClick(event, item.to)}
                  className={({ isActive }) =>
                    `rounded-xl px-4 py-2 text-sm font-medium transition ${
                      isActive ? 'app-nav-link-active' : 'app-nav-link'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>

            <label className="app-surface-soft flex items-center gap-2 rounded-2xl border px-3 py-2 text-xs font-medium app-text-muted">
              <span className="hidden sm:inline">Theme</span>
              <select
                value={themeMode}
                onChange={(event) => setThemeMode(event.target.value as 'system' | 'dark' | 'light')}
                className="app-input rounded-xl border px-3 py-1.5 text-xs font-semibold outline-none"
                aria-label="Theme mode"
              >
                <option value="system">Auto</option>
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </label>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}
