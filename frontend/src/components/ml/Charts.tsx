"use client";

import { DIM, GOLD, TEAL, TEAL_DARK, fmtHours } from "./format";

/* ---------- Reliability (calibration) diagram ---------- */
export function ReliabilityChart({
  model,
  baseline,
}: {
  model: { mean_predicted: number; observed_rate: number; count: number }[];
  baseline: { mean_predicted: number; observed_rate: number; count: number }[];
}) {
  const W = 300, H = 300, P = 36;
  const x = (v: number) => P + v * (W - P - 12);
  const y = (v: number) => H - P - v * (H - P - 12);
  const maxCount = Math.max(...model.map((b) => b.count), ...baseline.map((b) => b.count), 1);
  const r = (c: number) => 3 + 6 * Math.sqrt(c / maxCount);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[340px]" role="img" aria-label="Reliability diagram: predicted vs observed recovery rate">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={y(0)} y2={y(1)} stroke="#ffffff10" />
          <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} stroke="#ffffff10" />
          <text x={x(t)} y={H - P + 14} fontSize="9" fill={DIM} textAnchor="middle">{Math.round(t * 100)}%</text>
          <text x={P - 6} y={y(t) + 3} fontSize="9" fill={DIM} textAnchor="end">{Math.round(t * 100)}%</text>
        </g>
      ))}
      <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke={DIM} strokeDasharray="4 4" opacity="0.6" />
      <polyline fill="none" stroke={GOLD} strokeWidth="1.2" opacity="0.7" strokeDasharray="3 3"
        points={baseline.map((b) => `${x(b.mean_predicted)},${y(b.observed_rate)}`).join(" ")} />
      {baseline.map((b, i) => (
        <circle key={`b${i}`} cx={x(b.mean_predicted)} cy={y(b.observed_rate)} r={r(b.count)} fill="none" stroke={GOLD} strokeWidth="1.2" />
      ))}
      <polyline fill="none" stroke={TEAL} strokeWidth="1.6"
        points={model.map((b) => `${x(b.mean_predicted)},${y(b.observed_rate)}`).join(" ")} />
      {model.map((b, i) => (
        <circle key={`m${i}`} cx={x(b.mean_predicted)} cy={y(b.observed_rate)} r={r(b.count)} fill={TEAL} fillOpacity="0.55" stroke={TEAL} />
      ))}
      <text x={W / 2} y={H - 4} fontSize="10" fill={DIM} textAnchor="middle">Predicted recovery probability</text>
      <text x={10} y={H / 2} fontSize="10" fill={DIM} textAnchor="middle" transform={`rotate(-90 10 ${H / 2})`}>Observed recovery rate</text>
    </svg>
  );
}

/* ---------- Horizontal bar list ---------- */
export function HBarList({
  items,
  format = (v: number) => v.toFixed(3),
  color = TEAL_DARK,
}: {
  items: { label: string; value: number; sub?: string }[];
  format?: (v: number) => string;
  color?: string;
}) {
  const max = Math.max(...items.map((i) => Math.abs(i.value)), 1e-9);
  return (
    <div className="space-y-2.5">
      {items.map((i) => (
        <div key={i.label}>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-parchment">{i.label}</span>
            <span className="text-parchmentdim">{format(i.value)}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-charcoal">
            <div className="h-full rounded-full" style={{ width: `${(Math.abs(i.value) / max) * 100}%`, background: color }} />
          </div>
          {i.sub && <p className="mt-0.5 text-[10px] text-parchmentdim/70">{i.sub}</p>}
        </div>
      ))}
    </div>
  );
}

/* ---------- Policy bars with 95% CI whiskers ---------- */
export function PolicyBars({
  rows,
  format,
  baselineKey,
}: {
  rows: { key: string; label: string; value: number; ci?: [number, number]; color: string }[];
  format: (v: number) => string;
  baselineKey?: string;
}) {
  const hi = Math.max(...rows.map((r) => (r.ci ? r.ci[1] : r.value)), 1e-9) * 1.08;
  const lo = 0;
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const base = rows.find((r) => r.key === baselineKey);
  return (
    <div className="space-y-3">
      {rows.map((r) => (
        <div key={r.key}>
          <div className="mb-1 flex justify-between text-xs">
            <span className="text-parchment">{r.label}</span>
            <span className="font-mono text-parchmentdim">
              {format(r.value)}
              {r.ci && <span className="text-parchmentdim/60"> [{format(r.ci[0])} – {format(r.ci[1])}]</span>}
            </span>
          </div>
          <div className="relative h-3.5 rounded-sm bg-charcoal">
            <div className="absolute left-0 top-0 h-full rounded-sm" style={{ width: pos(r.value), background: r.color, opacity: 0.85 }} />
            {r.ci && (
              <>
                <div className="absolute top-1/2 h-px bg-white/80" style={{ left: pos(r.ci[0]), width: `calc(${pos(r.ci[1])} - ${pos(r.ci[0])})` }} />
                <div className="absolute top-[3px] h-2 w-px bg-white/80" style={{ left: pos(r.ci[0]) }} />
                <div className="absolute top-[3px] h-2 w-px bg-white/80" style={{ left: pos(r.ci[1]) }} />
              </>
            )}
            {base && r.key !== base.key && (
              <div className="absolute top-0 h-full w-px bg-gold-bright/70" style={{ left: pos(base.value) }} title="rules baseline" />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------- Simple multi-series line chart ---------- */
export function LineChart({
  series,
  xLabels,
  yFormat = (v: number) => v.toFixed(0),
  height = 190,
  yMinZero = false,
}: {
  series: { name: string; color: string; points: number[]; dashed?: boolean }[];
  xLabels: string[];
  yFormat?: (v: number) => string;
  height?: number;
  yMinZero?: boolean;
}) {
  const W = 480, H = height, PL = 52, PR = 28, PT = 10, PB = 26;
  const all = series.flatMap((s) => s.points);
  let lo = yMinZero ? 0 : Math.min(...all);
  let hi = Math.max(...all);
  const pad = (hi - lo || 1) * 0.12;
  lo = yMinZero ? 0 : lo - pad;
  hi = hi + pad;
  const n = xLabels.length;
  const x = (i: number) => PL + (n === 1 ? 0.5 : i / (n - 1)) * (W - PL - PR);
  const y = (v: number) => H - PB - ((v - lo) / (hi - lo)) * (H - PB - PT);
  const ticks = [0, 0.5, 1].map((t) => lo + t * (hi - lo));
  return (
    <div className="mx-auto max-w-[720px]">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img">
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={PL} x2={W - PR} y1={y(t)} y2={y(t)} stroke="#ffffff10" />
            <text x={PL - 6} y={y(t) + 3} fontSize="9" fill={DIM} textAnchor="end">{yFormat(t)}</text>
          </g>
        ))}
        {xLabels.map((l, i) => (
          <text key={i} x={x(i)} y={H - 8} fontSize="9" fill={DIM} textAnchor="middle">{l}</text>
        ))}
        {series.map((s) => (
          <g key={s.name}>
            <polyline fill="none" stroke={s.color} strokeWidth="1.8" strokeDasharray={s.dashed ? "4 3" : undefined}
              points={s.points.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
            {s.points.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r="2.5" fill={s.color} />
            ))}
          </g>
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap gap-4 text-[11px] text-parchmentdim">
        {series.map((s) => (
          <span key={s.name} className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4" style={{ background: s.color }} /> {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ---------- Bandit arm posterior bars (+ optional ground truth tick) ---------- */
export function ArmBars({
  arms,
  truth,
  best,
  sandboxBest,
}: {
  arms: { arm_hours: number; posterior_mean: number; observations: number }[];
  truth?: Record<string, number>;
  best?: number | null;
  sandboxBest?: number;
}) {
  return (
    <div className="flex h-36 items-end gap-3">
      {arms.map((a) => {
        const hit = truth ? Object.entries(truth).find(([k]) => Number(k) === a.arm_hours) : undefined;
        const t = hit ? hit[1] : undefined;
        return (
          <div key={a.arm_hours} className="relative flex h-full flex-1 flex-col items-center justify-end gap-1">
            <div className="relative flex w-full flex-1 items-end">
              <div
                className="w-full rounded-t-sm"
                style={{
                  height: `${Math.max(a.posterior_mean * 100, 3)}%`,
                  background: a.arm_hours === best ? GOLD : TEAL_DARK,
                  opacity: 0.4 + Math.min(a.observations / 30, 1) * 0.6,
                }}
                title={`${(a.posterior_mean * 100).toFixed(0)}% estimated success from ${a.observations} observation(s)`}
              />
              {t !== undefined && (
                <div
                  className="absolute left-[-2px] right-[-2px] border-t-2 border-dashed"
                  style={{ bottom: `${t * 100}%`, borderColor: a.arm_hours === sandboxBest ? "#fff" : "#ffffff80" }}
                  title={`sandbox ground truth ${(t * 100).toFixed(0)}%`}
                />
              )}
            </div>
            <span className="text-[10px] text-parchmentdim">{fmtHours(a.arm_hours)}</span>
            <span className="text-[9px] text-parchmentdim/60">n={a.observations}</span>
          </div>
        );
      })}
    </div>
  );
}
