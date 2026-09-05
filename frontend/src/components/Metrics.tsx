"use client";

export function MetricCard({
  label,
  value,
  sublabel,
  tone = "default",
}: {
  label: string;
  value: string;
  sublabel?: string;
  tone?: "default" | "gold" | "danger" | "emerald" | "teal";
}) {
  const toneClass =
    tone === "gold"
      ? "text-gold-bright"
      : tone === "danger"
      ? "text-burgundy-light"
      : tone === "emerald"
      ? "text-emerald-300"
      : tone === "teal"
      ? "text-[#5fd0d0]"
      : "text-parchment";

  const borderClass = tone === "teal" ? "border-[#00697C]/30" : "border-gold-dim/20";

  return (
    <div className={`rounded border ${borderClass} bg-surface/40 p-5`}>
      <p className="text-[11px] tracking-widest text-parchmentdim">{label}</p>
      <p className={`font-display mt-2 text-2xl ${toneClass}`}>{value}</p>
      {sublabel && <p className="mt-1 text-[11px] text-parchmentdim">{sublabel}</p>}
    </div>
  );
}

export function RevenueChart({ series }: { series: { date: string; amount: number }[] }) {
  if (!series.length) return null;
  const max = Math.max(...series.map((s) => s.amount), 1);

  return (
    <div className="rounded border border-gold-dim/20 bg-surface/40 p-5">
      <p className="mb-4 text-[11px] tracking-widest text-parchmentdim">REVENUE OVER TIME</p>
      <div className="flex h-40 items-end gap-1.5">
        {series.map((s) => (
          <div key={s.date} className="group relative flex-1">
            <div
              className="w-full rounded-t-sm bg-gradient-to-t from-burgundy to-gold transition group-hover:opacity-80"
              style={{ height: `${Math.max((s.amount / max) * 100, 3)}%` }}
            />
            <div className="pointer-events-none absolute -top-8 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-charcoal px-2 py-1 text-[10px] text-parchment group-hover:block">
              ₹{s.amount.toFixed(0)}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between text-[10px] text-parchmentdim">
        <span>{series[0]?.date}</span>
        <span>{series[series.length - 1]?.date}</span>
      </div>
    </div>
  );
}

export function MethodBreakdown({ items }: { items: { method: string; count: number }[] }) {
  if (!items.length) return null;
  const total = items.reduce((a, b) => a + b.count, 0) || 1;
  const colors: Record<string, string> = {
    card: "bg-gold",
    upi: "bg-emerald",
    netbanking: "bg-burgundy-light",
    wallet: "bg-gold-dim",
  };
  return (
    <div className="rounded border border-gold-dim/20 bg-surface/40 p-5">
      <p className="mb-4 text-[11px] tracking-widest text-parchmentdim">PAYMENT METHODS</p>
      <div className="space-y-3">
        {items.map((i) => (
          <div key={i.method}>
            <div className="mb-1 flex justify-between text-xs text-parchmentdim">
              <span className="capitalize">{i.method}</span>
              <span>{i.count}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-charcoal">
              <div
                className={`h-full rounded-full ${colors[i.method] || "bg-gold"}`}
                style={{ width: `${(i.count / total) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
