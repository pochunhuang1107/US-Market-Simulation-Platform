import type { ReactNode } from 'react';

interface SectionCardProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function SectionCard({ title, subtitle, children }: SectionCardProps) {
  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-5 shadow-2xl shadow-slate-950/40 lg:p-6">
      <div className="mb-5">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        {subtitle ? <p className="mt-1 text-sm text-slate-400">{subtitle}</p> : null}
      </div>
      {children}
    </section>
  );
}
