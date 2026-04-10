import { NavLink, Outlet } from 'react-router-dom';

const navItems = [
  { to: '/', label: 'Home', end: true },
  { to: '/runs', label: 'Runs', end: true },
  { to: '/strategy-builder', label: 'Builder', end: true },
  { to: '/strategies/new', label: 'Strategy', end: true },
  { to: '/runs/new', label: 'Simulation', end: true },
  { to: '/compare', label: 'Compare', end: true }
];

export function AppShell() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-4 lg:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.26em] text-cyan-300">
              US Market Strategy Platform
            </p>
            <h1 className="mt-1 text-xl font-semibold text-white">Chat-First Strategy Builder</h1>
          </div>

          <nav className="flex items-center gap-2 rounded-2xl border border-slate-800 bg-slate-900/70 p-1.5">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-xl px-4 py-2 text-sm font-medium transition ${
                    isActive
                      ? 'bg-cyan-500/15 text-cyan-300'
                      : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}