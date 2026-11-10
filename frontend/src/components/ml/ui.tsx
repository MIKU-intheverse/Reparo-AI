"use client";

import { ReactNode } from "react";

export function Card({ title, subtitle, children, className = "" }: { title?: string; subtitle?: string; children: ReactNode; className?: string }) {
  return (
    <div className={`rounded border border-gold-dim/20 bg-surface/40 p-5 ${className}`}>
      {title && <p className="text-xs tracking-widest text-parchmentdim">{title}</p>}
      {subtitle && <p className="mt-1 text-[11px] text-parchmentdim/70">{subtitle}</p>}
      <div className={title ? "mt-4" : ""}>{children}</div>
    </div>
  );
}

export function Banner({ tone = "info", children }: { tone?: "info" | "warn" | "ok"; children: ReactNode }) {
  const cls =
    tone === "warn"
      ? "border-gold-dim/50 bg-gold/10 text-parchment"
      : tone === "ok"
      ? "border-emerald/40 bg-emerald/10 text-[#bfeee0]"
      : "border-[#00697C]/40 bg-[#00586A]/10 text-parchment";
  return <div className={`rounded border px-4 py-3 text-xs leading-relaxed ${cls}`}>{children}</div>;
}

export function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded border border-gold-dim/20 bg-surface/40 p-4">
      <p className="text-[10px] tracking-widest text-parchmentdim">{label}</p>
      <p className={`mt-1 font-display text-2xl ${tone === "good" ? "text-[#3fbf9f]" : tone === "bad" ? "text-[#f0a8a5]" : "text-gold-bright"}`}>{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-parchmentdim/80">{sub}</p>}
    </div>
  );
}

export function ActionButton({ onClick, busy, children, disabled, tone = "teal" }: { onClick: () => void; busy?: boolean; children: ReactNode; disabled?: boolean; tone?: "teal" | "gold" | "red" }) {
  const cls =
    tone === "gold"
      ? "border-gold-dim/50 text-gold-bright hover:bg-gold/10"
      : tone === "red"
      ? "border-[#c0504d]/60 text-[#f0a8a5] hover:bg-[#c0504d]/15"
      : "border-[#00697C]/60 text-[#5fd0d0] hover:bg-[#00697C]/15";
  return (
    <button
      onClick={onClick}
      disabled={busy || disabled}
      className={`rounded-sm border px-3 py-2 text-[11px] font-semibold tracking-widest transition disabled:cursor-not-allowed disabled:opacity-50 ${cls}`}
    >
      {busy ? "WORKING…" : children}
    </button>
  );
}

export function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return <th className={`px-3 py-2 text-[10px] font-normal tracking-widest text-parchmentdim ${right ? "text-right" : "text-left"}`}>{children}</th>;
}
