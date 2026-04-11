import type { ReactNode } from 'react';

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        {eyebrow ? <p className="app-eyebrow text-xs font-semibold uppercase tracking-[0.24em]">{eyebrow}</p> : null}
        <h2 className="mt-2 text-3xl font-semibold tracking-tight app-title">{title}</h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 app-text-muted">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
    </div>
  );
}
