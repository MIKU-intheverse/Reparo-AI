"use client";

export function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    captured: "border-emerald/50 bg-emerald/20 text-emerald-200",
    paid: "border-emerald/50 bg-emerald/20 text-emerald-200",
    processed: "border-emerald/50 bg-emerald/20 text-emerald-200",
    won: "border-emerald/50 bg-emerald/20 text-emerald-200",
    failed: "border-burgundy-light/50 bg-burgundy-dark/30 text-gold-bright",
    lost: "border-burgundy-light/50 bg-burgundy-dark/30 text-gold-bright",
    open: "border-gold/40 bg-gold/10 text-gold-bright",
    under_review: "border-gold/40 bg-gold/10 text-gold-bright",
    created: "border-gold-dim/40 bg-surface text-parchmentdim",
    authorized: "border-gold/40 bg-gold/10 text-gold-bright",
    refunded: "border-gold-dim/40 bg-surface text-parchmentdim",
  };
  return (
    <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${map[status] || "border-gold-dim/40 bg-surface text-parchmentdim"}`}>
      {status}
    </span>
  );
}

export function DataTable({
  columns,
  rows,
  renderCell,
}: {
  columns: string[];
  rows: any[];
  renderCell: (row: any, col: string) => React.ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded border border-gold-dim/20">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-gold-dim/20 bg-surface/60 text-[11px] tracking-widest text-parchmentdim">
            {columns.map((c) => (
              <th key={c} className="px-4 py-3 font-normal">
                {c.toUpperCase()}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id || i} className="border-b border-gold-dim/10 text-parchment transition hover:bg-surface/40">
              {columns.map((c) => (
                <td key={c} className="px-4 py-3">
                  {renderCell(row, c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PaginationBar({
  skip,
  limit,
  count,
  onPrev,
  onNext,
}: {
  skip: number;
  limit: number;
  count: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="mt-4 flex items-center justify-between text-xs text-parchmentdim">
      <span>
        Showing {Math.min(skip + 1, count)}–{Math.min(skip + limit, count)} of {count}
      </span>
      <div className="flex gap-2">
        <button
          disabled={skip === 0}
          onClick={onPrev}
          className="rounded-sm border border-gold-dim/30 px-3 py-1.5 tracking-widest transition hover:border-gold/50 hover:text-gold-bright disabled:opacity-40"
        >
          PREV
        </button>
        <button
          disabled={skip + limit >= count}
          onClick={onNext}
          className="rounded-sm border border-gold-dim/30 px-3 py-1.5 tracking-widest transition hover:border-gold/50 hover:text-gold-bright disabled:opacity-40"
        >
          NEXT
        </button>
      </div>
    </div>
  );
}
