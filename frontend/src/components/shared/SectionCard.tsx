import type { ReactNode } from 'react';

interface SectionCardProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function SectionCard({ title, subtitle, children }: SectionCardProps) {
  return (
    <section className="app-card app-shadow-soft rounded-3xl border p-5 lg:p-6">
      <div className="mb-5">
        <h3 className="app-title text-lg font-semibold">{title}</h3>
        {subtitle ? <p className="app-text-muted mt-1 text-sm">{subtitle}</p> : null}
      </div>
      {children}
    </section>
  );
}
