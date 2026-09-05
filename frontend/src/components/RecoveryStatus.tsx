"use client";

const STATUS_STYLE: Record<string, string> = {
  failed: "border-burgundy-light/50 bg-burgundy-dark/30 text-gold-bright",
  analyzing: "border-gold-dim/40 bg-surface text-parchmentdim",
  pending_approval: "border-gold/50 bg-gold/10 text-gold-bright",
  approved: "border-[#00697C]/50 bg-[#00697C]/15 text-[#66c9d6]",
  waiting: "border-[#00697C]/50 bg-[#00697C]/15 text-[#66c9d6]",
  retrying: "border-[#008080]/50 bg-[#008080]/15 text-[#5fd0d0]",
  verifying: "border-[#008080]/50 bg-[#008080]/15 text-[#5fd0d0]",
  recovered: "border-emerald/50 bg-emerald/20 text-emerald-200",
  rejected: "border-gold-dim/40 bg-surface text-parchmentdim",
  suppressed: "border-gold-dim/40 bg-surface text-parchmentdim",
  exhausted: "border-burgundy-light/40 bg-burgundy-dark/20 text-gold-bright",
  expired: "border-gold-dim/40 bg-surface text-parchmentdim",
  manual_review: "border-gold-dim/40 bg-surface text-parchmentdim",
};

export function RecoveryStatusPill({ status }: { status: string }) {
  return (
    <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${STATUS_STYLE[status] || STATUS_STYLE.failed}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

export function CategoryTag({ category }: { category: string }) {
  const label = category.replaceAll("_", " ");
  return <span className="rounded-full border border-gold-dim/30 px-2 py-0.5 text-[10px] uppercase tracking-wider text-parchmentdim">{label}</span>;
}
