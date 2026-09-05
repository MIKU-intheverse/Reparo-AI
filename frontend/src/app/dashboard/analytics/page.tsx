"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Activity } from "lucide-react";
import DashboardShell from "@/components/DashboardShell";
import { MetricCard, RevenueChart, MethodBreakdown } from "@/components/Metrics";
import { SkeletonMetricCards, SkeletonChart, ErrorBlock, EmptyBlock } from "@/components/DataStates";
import { api, ApiError } from "@/lib/api";

export default function OverviewPage() {
  const [data, setData] = useState<any>(null);
  const [activity, setActivity] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastSynced, setLastSynced] = useState<Date | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [res, act] = await Promise.all([api.analytics(14), api.activity(8)]);
      setData(res);
      setActivity(act.items);
      setLastSynced(new Date());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load analytics.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <DashboardShell>
      <div className="mb-6 flex items-center justify-between">
        <p className="text-xs text-parchmentdim">
          {lastSynced ? `Last updated: ${lastSynced.toLocaleTimeString()}` : ""}
        </p>
        <button
          onClick={load}
          className="flex items-center gap-2 rounded-sm border border-gold-dim/30 px-3 py-1.5 text-xs tracking-widest text-parchmentdim transition hover:border-gold/50 hover:text-gold-bright"
        >
          <RefreshCw className="h-3.5 w-3.5" /> REFRESH
        </button>
      </div>

      {loading && (
        <div className="space-y-6">
          <SkeletonMetricCards count={4} />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <SkeletonChart />
            </div>
            <SkeletonChart />
          </div>
        </div>
      )}
      {!loading && error && <ErrorBlock message={error} onRetry={load} />}

      {!loading && !error && data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <MetricCard label="TOTAL REVENUE" value={`₹${data.total_revenue.toLocaleString()}`} tone="gold" sublabel="Captured payments, 14d" />
            <MetricCard label="SUCCESS RATE" value={`${data.success_rate}%`} tone="emerald" />
            <MetricCard label="TOTAL PAYMENTS" value={String(data.total_payments)} />
            <MetricCard label="FAILED PAYMENTS" value={String(data.failed_payments)} tone="danger" />
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <RevenueChart series={data.revenue_series} />
            </div>
            <MethodBreakdown items={data.method_breakdown} />
          </div>

          <div className="rounded border border-gold-dim/20 bg-surface/40 p-5">
            <div className="mb-4 flex items-center gap-2 text-[11px] tracking-widest text-parchmentdim">
              <Activity className="h-3.5 w-3.5 text-gold" /> RECENT ACTIVITY
            </div>
            {activity.length === 0 && <EmptyBlock label="No recent activity yet." />}
            {activity.length > 0 && (
              <ul className="space-y-3">
                {activity.map((a) => (
                  <li key={a.id} className="flex items-start justify-between gap-4 border-b border-gold-dim/10 pb-3 last:border-0 last:pb-0">
                    <span className="text-sm text-parchment">{a.message}</span>
                    <span className="shrink-0 text-[11px] text-parchmentdim">{new Date(a.created_at).toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </DashboardShell>
  );
}
