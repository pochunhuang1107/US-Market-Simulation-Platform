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
    <div className="app-card app-shadow flex flex-col gap-4 rounded-3xl border px-5 py-4 text-sm app-text-muted sm:flex-row sm:items-center sm:justify-between">
      <p>
        Showing <span className="font-semibold app-title">{start}</span> to <span className="font-semibold app-title">{end}</span> of{' '}
        <span className="font-semibold app-title">{total}</span> results
      </p>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="app-button-secondary rounded-xl px-4 py-2 transition disabled:cursor-not-allowed disabled:opacity-40"
        >
          Previous
        </button>
        <span className="app-code rounded-xl px-4 py-2 app-title">Page {page}</span>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={!hasNext}
          className="app-button-secondary rounded-xl px-4 py-2 transition disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
