"use client";

import { useEffect, useState } from "react";
import DashboardShell from "@/components/DashboardShell";
import { SkeletonTable, EmptyBlock, ErrorBlock } from "@/components/DataStates";
import { DataTable, PaginationBar, StatusPill } from "@/components/DataTable";
import { api, ApiError } from "@/lib/api";

const LIMIT = 10;

export default function SettlementsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [count, setCount] = useState(0);
  const [skip, setSkip] = useState(0);
  const [unavailable, setUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await api.settlements(LIMIT, skip);
      setItems(res.items);
      setCount(res.count);
      setUnavailable(!!res.unavailable);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load settlements.");
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
      {loading && <SkeletonTable cols={4} />}
      {!loading && error && <ErrorBlock message={error} onRetry={load} />}
      {!loading && !error && unavailable && (
        <EmptyBlock label="Settlements aren't enabled for this Razorpay account yet. Contact Razorpay to enable the Settlements API, or check API key permissions." />
      )}
      {!loading && !error && !unavailable && items.length === 0 && <EmptyBlock label="No settlements yet." />}
      {!loading && !error && !unavailable && items.length > 0 && (
        <>
          <DataTable
            columns={["id", "amount", "fees", "status", "settled_at"]}
            rows={items}
            renderCell={(row, col) => {
              if (col === "amount" || col === "fees") return `₹${row[col].toFixed(2)}`;
              if (col === "status") return <StatusPill status={row.status} />;
              if (col === "settled_at") return new Date(row.settled_at).toLocaleString();
              if (col === "id") return <span className="font-mono text-xs">{row.id.slice(0, 12)}…</span>;
              return row[col] ?? "—";
            }}
          />
          <PaginationBar skip={skip} limit={LIMIT} count={count} onPrev={() => setSkip(Math.max(0, skip - LIMIT))} onNext={() => setSkip(skip + LIMIT)} />
        </>
      )}
    </DashboardShell>
  );
}
