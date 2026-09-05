"use client";

import { useEffect, useState } from "react";
import DashboardShell from "@/components/DashboardShell";
import { SkeletonTable, EmptyBlock, ErrorBlock } from "@/components/DataStates";
import { DataTable, PaginationBar, StatusPill } from "@/components/DataTable";
import { api, ApiError } from "@/lib/api";

const LIMIT = 10;
const STATUSES = ["", "captured", "failed", "created", "authorized"];

export default function PaymentsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [count, setCount] = useState(0);
  const [skip, setSkip] = useState(0);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      if (query.trim()) {
        const res = await api.search(query.trim());
        setItems(res.items);
        setCount(res.count);
      } else {
        const res = await api.payments(LIMIT, skip, status || undefined);
        setItems(res.items);
        setCount(res.count);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load payments.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skip, status]);

  return (
    <DashboardShell>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          placeholder="Search by payment id, email, phone, method…"
          className="w-72 rounded-sm border border-gold-dim/30 bg-charcoal px-3 py-2 text-sm text-parchment outline-none focus:border-gold"
        />
        <button
          onClick={load}
          className="rounded-sm border border-gold-dim/30 px-3 py-2 text-xs tracking-widest text-parchmentdim hover:border-gold/50 hover:text-gold-bright"
        >
          SEARCH
        </button>
        <div className="ml-auto flex gap-2">
          {STATUSES.map((s) => (
            <button
              key={s || "all"}
              onClick={() => {
                setStatus(s);
                setSkip(0);
                setQuery("");
              }}
              className={`rounded-full border px-3 py-1.5 text-[11px] tracking-widest ${
                status === s ? "border-gold bg-gold/10 text-gold-bright" : "border-gold-dim/30 text-parchmentdim"
              }`}
            >
              {(s || "all").toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {loading && <SkeletonTable cols={6} />}
      {!loading && error && <ErrorBlock message={error} onRetry={load} />}
      {!loading && !error && items.length === 0 && <EmptyBlock label="No payments match this view." />}

      {!loading && !error && items.length > 0 && (
        <>
          <DataTable
            columns={["id", "amount", "method", "status", "email", "created_at"]}
            rows={items}
            renderCell={(row, col) => {
              if (col === "amount") return `₹${row.amount.toFixed(2)}`;
              if (col === "status") return <StatusPill status={row.status} />;
              if (col === "created_at") return new Date(row.created_at).toLocaleString();
              if (col === "id") return <span className="font-mono text-xs">{row.id.slice(0, 12)}…</span>;
              return row[col] ?? "—";
            }}
          />
          {!query && <PaginationBar skip={skip} limit={LIMIT} count={count} onPrev={() => setSkip(Math.max(0, skip - LIMIT))} onNext={() => setSkip(skip + LIMIT)} />}
        </>
      )}
    </DashboardShell>
  );
}
