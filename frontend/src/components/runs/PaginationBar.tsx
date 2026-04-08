interface PaginationBarProps {
  page: number;
  pageSize: number;
  total: number;
  hasNext: boolean;
  onPageChange: (page: number) => void;
}

export function PaginationBar({ page, pageSize, total, hasNext, onPageChange }: PaginationBarProps) {
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <div className="flex flex-col gap-4 rounded-3xl border border-slate-800 bg-slate-900/70 px-5 py-4 text-sm text-slate-300 shadow-2xl shadow-slate-950/30 sm:flex-row sm:items-center sm:justify-between">
      <p>
        Showing <span className="font-semibold text-white">{start}</span> to <span className="font-semibold text-white">{end}</span> of{' '}
        <span className="font-semibold text-white">{total}</span> runs
      </p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="rounded-xl border border-slate-700 px-4 py-2 transition enabled:hover:border-cyan-500/50 enabled:hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Previous
        </button>
        <span className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-2 text-white">Page {page}</span>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={!hasNext}
          className="rounded-xl border border-slate-700 px-4 py-2 transition enabled:hover:border-cyan-500/50 enabled:hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
