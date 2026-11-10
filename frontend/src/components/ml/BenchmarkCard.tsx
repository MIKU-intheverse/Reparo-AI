"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { pct } from "./format";
import { Banner, Card, Th } from "./ui";

const fmt = (x: any) => (x.value !== undefined ? pct(x.value, x.value < 0.1 || String(x.value).length > 4 ? 1 : 0) : `${pct(x.low)} – ${pct(x.high)}`);

export default function BenchmarkCard() {
  const [d, setD] = useState<any>(null);
  useEffect(() => {
    api.mlBenchmarks().then(setD).catch(() => setD(null));
  }, []);
  if (!d) return null;
  const band = d.published.calibration_band;
  const sim = d.simulated.recovery_rate_by_world as Record<string, any>;
  const inBand = (v: number) => v >= band.low && v <= band.high;

  return (
    <Card title="REALITY CHECK AGAINST PUBLISHED INDUSTRY FIGURES" subtitle="There is no public dataset of failed payments with recovery outcomes. What exists are vendor-published aggregates — used here only as calibration targets and sanity checks, never as training data.">
      <Banner tone="warn">{d.published.disclaimer}</Banner>

      <p className="mb-2 mt-5 text-[11px] tracking-widest text-parchmentdim">WHY THERE ARE THREE WORLDS</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-gold-dim/20"><Th>SIMULATED WORLD</Th><Th right>DO NOTHING</Th><Th right>RULES BASELINE</Th><Th right>FULL ML</Th><Th right>RULES vs PUBLISHED {pct(band.low)}–{pct(band.high)}</Th></tr></thead>
          <tbody>
            {Object.entries(sim).map(([k, v]: [string, any]) => (
              <tr key={k} className="border-b border-gold-dim/10">
                <td className="px-3 py-2 capitalize text-parchment">{k}</td>
                <td className="px-3 py-2 text-right font-mono text-parchmentdim">{pct(v.do_nothing, 1)}</td>
                <td className="px-3 py-2 text-right font-mono text-parchment">{pct(v.rules, 1)}</td>
                <td className="px-3 py-2 text-right font-mono text-[#3fbf9f]">{pct(v.ml_full, 1)}</td>
                <td className={`px-3 py-2 text-right text-xs ${inBand(v.rules) ? "text-[#3fbf9f]" : "text-[#f0a8a5]"}`}>{inBand(v.rules) ? "inside the published band" : "more optimistic than published"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-parchmentdim/80">
        The base world recovers far more than vendors report, so it flatters every policy. The conservative world adds one global shift (and a lower organic-payment rate), chosen only so the <em>rules</em> baseline lands inside the published band; no ML policy was used to pick it. The ML lift holds there too.
      </p>

      <p className="mb-2 mt-5 text-[11px] tracking-widest text-parchmentdim">PUBLISHED FAILURE MIX</p>
      <table className="w-full text-sm">
        <tbody>
          {d.published.failure_mix.map((x: any) => (
            <tr key={x.stat} className="border-b border-gold-dim/10">
              <td className="px-3 py-2 text-parchment">{x.stat}<a href={x.url} target="_blank" rel="noreferrer" className="ml-2 text-[10px] text-[#5fd0d0] hover:underline">{x.source}</a></td>
              <td className="px-3 py-2 text-right font-mono text-gold-bright">{pct(x.value, 1)}</td>
            </tr>
          ))}
          <tr><td className="px-3 py-2 text-parchmentdim">Simulator: insufficient-funds share of failures</td><td className="px-3 py-2 text-right font-mono text-parchmentdim">{pct(d.simulated.insufficient_funds_share, 1)}</td></tr>
        </tbody>
      </table>

      <p className="mb-2 mt-5 text-[11px] tracking-widest text-parchmentdim">PUBLISHED RECOVERY &amp; TIMING FIGURES</p>
      <table className="w-full text-sm">
        <tbody>
          {[...d.published.recovery_rates, ...d.published.timing].map((x: any) => (
            <tr key={x.stat} className="border-b border-gold-dim/10">
              <td className="px-3 py-2 text-parchment">{x.stat}<a href={x.url} target="_blank" rel="noreferrer" className="ml-2 text-[10px] text-[#5fd0d0] hover:underline">{x.source}</a></td>
              <td className="px-3 py-2 text-right font-mono text-gold-bright">{fmt(x)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
