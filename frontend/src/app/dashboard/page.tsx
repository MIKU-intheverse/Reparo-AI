"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Radar, ChevronRight, FastForward } from "lucide-react";
import DashboardShell from "@/components/DashboardShell";
import { MetricCard } from "@/components/Metrics";
import { SkeletonMetricCards, SkeletonTable, ErrorBlock, EmptyBlock } from "@/components/DataStates";
import { RecoveryStatusPill, CategoryTag } from "@/components/RecoveryStatus";
import { CaseDetailPanel } from "@/components/CaseDetailPanel";
import { api, ApiError, getEnvironment } from "@/lib/api";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "priority", label: "High Priority" },
  { key: "failed", label: "Failed" },
  { key: "pending_approval", label: "Awaiting Approval" },
  { key: "waiting", label: "Waiting / Follow-up" },
  { key: "retrying", label: "Retrying" },
  { key: "recovered", label: "Recovered" },
  { key: "exhausted", label: "Exhausted" },
  { key: "suppressed", label: "Suppressed" },
  { key: "security_hold", label: "Security Hold" },
];

export default function RecoveryConsolePage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [cases, setCases] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedCase, setSelectedCase] = useState<string | null>(null);
  const [lastScan, setLastScan] = useState<Date | null>(null);
  const [advancing, setAdvancing] = useState(false);
  const [isTest, setIsTest] = useState(false);

  useEffect(() => {
    setIsTest(getEnvironment() === "test");
  }, []);

  async function fastForward(hours: number) {
    setAdvancing(true);
    setError(null);
    try {
      await api.recoveryAdvance(hours);
      await api.recoveryScan();
      setLastScan(new Date());
      await loadAll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not advance the sandbox clock.");
    } finally {
      setAdvancing(false);
    }
  }

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const priority = filter === "priority";
      const statusParam = filter === "all" || filter === "priority" ? undefined : filter;
      const [m, c] = await Promise.all([api.recoveryMetrics(), api.recoveryCases(statusParam, priority)]);
      setMetrics(m);
      setCases(c.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the recovery console.");
    } finally {
      setLoading(false);
    }
  }

  async function runScan() {
    setScanning(true);
    setError(null);
    try {
      await api.recoveryScan();
      setLastScan(new Date());
      await loadAll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Recovery scan failed.");
    } finally {
      setScanning(false);
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  return (
    <DashboardShell>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-parchmentdim">
          {lastScan ? `Last scan: ${lastScan.toLocaleTimeString()}` : "Run a scan to detect revenue at risk."}
        </p>
        <div className="flex flex-wrap gap-2">
          {isTest && (
            <button
              onClick={() => fastForward(24)}
              disabled={advancing || scanning}
              title="Test Mode: simulate 24 hours passing, then scan, so scheduled retries come due"
              className="flex items-center gap-2 rounded-sm border border-[#00697C]/50 px-3 py-1.5 text-xs tracking-widest text-[#5fd0d0] transition hover:bg-[#00697C]/15 disabled:opacity-60"
            >
              <FastForward className={`h-3.5 w-3.5 ${advancing ? "animate-pulse" : ""}`} /> {advancing ? "ADVANCING…" : "+24H & SCAN"}
            </button>
          )}
          <button
            onClick={loadAll}
            className="flex items-center gap-2 rounded-sm border border-gold-dim/30 px-3 py-1.5 text-xs tracking-widest text-parchmentdim transition hover:border-gold/50 hover:text-gold-bright"
          >
            <RefreshCw className="h-3.5 w-3.5" /> REFRESH
          </button>
          <button
            onClick={runScan}
            disabled={scanning}
            className="flex items-center gap-2 rounded-sm border border-gold/50 bg-burgundy px-4 py-1.5 text-xs font-semibold tracking-widest text-parchment transition hover:bg-burgundy-light disabled:opacity-60"
          >
            <Radar className={`h-3.5 w-3.5 ${scanning ? "animate-spin" : ""}`} /> {scanning ? "SCANNING…" : "RUN RECOVERY SCAN"}
          </button>
        </div>
      </div>

      {loading && !metrics && <SkeletonMetricCards count={5} />}
      {!loading && error && <ErrorBlock message={error} onRetry={loadAll} />}

      {metrics && (
        <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4 2xl:grid-cols-7">
          <MetricCard label="REVENUE AT RISK" value={`₹${metrics.revenue_at_risk.toLocaleString()}`} tone="danger" sublabel={`${metrics.total_failed_payments} case(s) detected`} />
          <MetricCard label="RECOVERED" value={`₹${metrics.recovered_amount.toLocaleString()}`} tone="emerald" />
          <MetricCard label="RECOVERY RATE" value={`${metrics.recovery_rate}%`} tone="teal" sublabel={`Max ${metrics.max_retries} retries/case`} />
          <MetricCard label="ACTIVE CASES" value={String(metrics.active_recovery_cases)} tone="teal" />
          <MetricCard label="AWAITING APPROVAL" value={String(metrics.awaiting_approval)} tone="gold" />
          <MetricCard label="SECURITY HOLDS" value={String(metrics.security_holds ?? 0)} tone={metrics.security_holds > 0 ? "danger" : "default"} sublabel="suspected card testing" />
          <MetricCard label="PENDING FOLLOW-UPS" value={String(metrics.pending_followups)} tone="teal" sublabel={`${metrics.communications_sent} message(s) sent`} />
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-full border px-3 py-1.5 text-[11px] tracking-widest ${
              filter === f.key ? "border-gold bg-gold/10 text-gold-bright" : "border-gold-dim/30 text-parchmentdim"
            }`}
          >
            {f.label.toUpperCase()}
          </button>
        ))}
      </div>

      {loading && <SkeletonTable cols={7} />}
      {!loading && !error && cases.length === 0 && (
        <EmptyBlock label="No revenue-at-risk cases in this view. Run a recovery scan to detect failed payments." />
      )}

      {!loading && !error && cases.length > 0 && (
        <div className="space-y-2">
          {cases.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelectedCase(c.id)}
              className="flex w-full items-center justify-between gap-4 rounded border border-gold-dim/20 bg-surface/40 p-4 text-left transition hover:border-gold/40 hover:bg-surface/60"
            >
              <div className="flex min-w-0 flex-1 items-center gap-4">
                <div className="min-w-0">
                  <p className="truncate text-sm text-parchment">{c.customer_email || "Unknown customer"}</p>
                  <p className="truncate font-mono text-[11px] text-parchmentdim">{c.payment_id.slice(0, 18)}…</p>
                </div>
                <CategoryTag category={c.category} />
                <span className="hidden text-xs text-parchmentdim md:inline">{c.failure_reason_raw || "unknown reason"}</span>
              </div>
              <div className="flex shrink-0 items-center gap-5">
                <div className="text-right">
                  <p className="font-display text-sm text-gold-bright">₹{c.amount.toFixed(2)}</p>
                  <p className="text-[10px] text-parchmentdim">{Math.round(c.recovery_probability * 100)}% recoverable</p>
                </div>
                <div className="hidden text-right text-[10px] text-parchmentdim sm:block">
                  <p>Retries {c.retry_count}/{c.max_retries}</p>
                  <p className="capitalize">{c.recommended_action.replaceAll("_", " ")}</p>
                </div>
                <RecoveryStatusPill status={c.status} />
                <ChevronRight className="h-4 w-4 text-parchmentdim" />
              </div>
            </button>
          ))}
        </div>
      )}

      {selectedCase && (
        <CaseDetailPanel caseId={selectedCase} onClose={() => setSelectedCase(null)} onChanged={loadAll} />
      )}
    </DashboardShell>
  );
}
