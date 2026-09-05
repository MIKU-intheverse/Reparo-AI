"use client";

import { useEffect, useState } from "react";
import DashboardShell from "@/components/DashboardShell";
import { SkeletonTable, EmptyBlock, ErrorBlock } from "@/components/DataStates";
import { DataTable, PaginationBar, StatusPill } from "@/components/DataTable";
import { api, ApiError } from "@/lib/api";

const LIMIT = 10;

export default function RefundsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [count, setCount] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await api.refunds(LIMIT, skip);
      setItems(res.items);
      setCount(res.count);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load refunds.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skip]);

  return (
    <DashboardShell>
      {loading && <SkeletonTable cols={6} />}
      {!loading && error && <ErrorBlock message={error} onRetry={load} />}
      {!loading && !error && items.length === 0 && <EmptyBlock label="No refunds have been issued." />}
      {!loading && !error && items.length > 0 && (
        <>
          <DataTable
            columns={["id", "payment_id", "amount", "status", "created_at"]}
            rows={items}
            renderCell={(row, col) => {
              if (col === "amount") return `₹${row.amount.toFixed(2)}`;
              if (col === "status") return <StatusPill status={row.status} />;
              if (col === "created_at") return new Date(row.created_at).toLocaleString();
              if (col === "id" || col === "payment_id") return <span className="font-mono text-xs">{String(row[col]).slice(0, 12)}…</span>;
              return row[col] ?? "—";
            }}
          />
          <PaginationBar skip={skip} limit={LIMIT} count={count} onPrev={() => setSkip(Math.max(0, skip - LIMIT))} onNext={() => setSkip(skip + LIMIT)} />
        </>
      )}
    </DashboardShell>
  );
}
