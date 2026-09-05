"use client";

import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-parchmentdim">
      <RefreshCw className="h-4 w-4 animate-spin text-gold" />
      <span className="text-sm tracking-wide">{label}</span>
    </div>
  );
}

export function EmptyBlock({ label = "No data available yet." }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-parchmentdim">
      <Inbox className="h-6 w-6 text-gold-dim" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded border border-burgundy-light/40 bg-burgundy-dark/20 py-12 text-center">
      <AlertTriangle className="h-6 w-6 text-gold-bright" />
      <p className="max-w-md text-sm text-parchmentdim">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 rounded-sm border border-gold/40 px-4 py-1.5 text-xs tracking-widest text-gold-bright transition hover:bg-gold/10"
        >
          RETRY
        </button>
      )}
    </div>
  );
}

export function SkeletonRow() {
  return <div className="h-10 w-full animate-pulse rounded bg-surface/80" />;
}

export function SkeletonTable({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="overflow-hidden rounded border border-gold-dim/20">
      <div className="border-b border-gold-dim/20 bg-surface/60 px-4 py-3">
        <div className="h-3 w-1/3 animate-pulse rounded bg-charcoal" />
      </div>
      <div className="divide-y divide-gold-dim/10">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-6 px-4 py-3.5">
            {Array.from({ length: cols }).map((_, c) => (
              <div
                key={c}
                className="h-3.5 flex-1 animate-pulse rounded bg-surface/70"
                style={{ animationDelay: `${(r * cols + c) * 40}ms`, maxWidth: c === 0 ? "90px" : undefined }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkeletonMetricCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded border border-gold-dim/20 bg-surface/40 p-5">
          <div className="h-2.5 w-2/3 animate-pulse rounded bg-charcoal" />
          <div className="mt-3 h-6 w-1/2 animate-pulse rounded bg-surface/80" style={{ animationDelay: `${i * 60}ms` }} />
          <div className="mt-2 h-2 w-3/4 animate-pulse rounded bg-charcoal" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonChart() {
  return (
    <div className="rounded border border-gold-dim/20 bg-surface/40 p-5">
      <div className="mb-4 h-2.5 w-1/3 animate-pulse rounded bg-charcoal" />
      <div className="flex h-40 items-end gap-1.5">
        {Array.from({ length: 14 }).map((_, i) => (
          <div
            key={i}
            className="flex-1 animate-pulse rounded-t-sm bg-surface/70"
            style={{ height: `${20 + ((i * 37) % 70)}%`, animationDelay: `${i * 50}ms` }}
          />
        ))}
      </div>
    </div>
  );
}
