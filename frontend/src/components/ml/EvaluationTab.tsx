"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import BenchmarkCard from "./BenchmarkCard";
import { LineChart, PolicyBars } from "./Charts";
import { POLICY_COLOR, POLICY_LABEL, fmtHours, inr, pct, signed } from "./format";
import { ActionButton, Banner, Card, Stat, Th } from "./ui";

export default function EvaluationTab({ initial, onUpdated }: { initial: any; onUpdated: (r: any) => void }) {
  const [world, setWorld] = useState<"base" | "shifted" | "conservative">("base");
  const [nCases, setNCases] = useState(initial.config.n_cases);
  const [cap, setCap] = useState(initial.config.approvals_per_day);
  const [seed, setSeed] = useState(initial.config.seed);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const report = initial;
  const worlds = (["base", "shifted", "conservative"] as const).filter((k) => report[k]);
  const w = report[world] ?? report.base;
  const by = Object.fromEntries(w.policies.map((p: any) => [p.policy, p]));
  const full = by.ml_full, rules = by.rules, risk = by.ml_risk;

  async function rerun() {
    setBusy(true);
    setErr(null);
    try {
      onUpdated(await api.mlRunEvaluation({ n_cases: nCases, seed, approvals_per_day: cap }));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Evaluation failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Banner tone="info">
        The <strong>same {w.n_cases.toLocaleString()} failed payments</strong> (same random draws) are replayed through five recovery policies in a simulated world. Net value = recovered revenue − retry, message and human-review costs.
        Bars show 95% bootstrap CIs; the gold tick marks the rules baseline. {report.notes[report.notes.length - 1]}
      </Banner>

      <div className="flex flex-wrap items-center gap-3">
        {worlds.map((k) => (
          <button
            key={k}
            onClick={() => setWorld(k)}
            className={`rounded-sm border px-4 py-1.5 text-xs tracking-widest transition ${world === k ? "border-gold-dim bg-gold/10 text-gold-bright" : "border-gold-dim/30 text-parchmentdim hover:text-parchment"}`}
          >
            {k === "base" ? "BASE WORLD (what the model was trained on)" : k === "shifted" ? "SHIFTED WORLD (drifted dynamics)" : "CONSERVATIVE WORLD (calibrated to published recovery rates)"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="NET VALUE LIFT vs RULES"
          value={`${signed(full.lift_vs_rules_pct, 1)}%`}
          sub={`${signed(full.lift_vs_rules_per_case, 0)} ₹/case · CI ${full.lift_vs_rules_ci95.map((v: number) => signed(v, 0)).join(" … ")}`}
          tone={full.lift_significant && full.lift_vs_rules_per_case > 0 ? "good" : undefined}
        />
        <Stat label="RECOVERY RATE" value={pct(full.recovery_rate, 1)} sub={`rules ${pct(rules.recovery_rate, 1)} · naive ${pct(by.naive_retry.recovery_rate, 1)} · nothing ${pct(by.do_nothing.recovery_rate, 1)}`} />
        <Stat label="RETRIES / CASE" value={full.retries_per_case.toFixed(2)} sub={`rules ${rules.retries_per_case.toFixed(2)} · naive ${by.naive_retry.retries_per_case.toFixed(2)}`} />
        <Stat label="TIME TO RECOVERY" value={`${full.mean_hours_to_recovery}h`} sub={`rules ${rules.mean_hours_to_recovery}h — the price of waiting for better odds`} tone="bad" />
      </div>

      <Card title="NET VALUE PER FAILED PAYMENT (₹)" subtitle="Higher is better. Whiskers = 95% CI over cases.">
        <PolicyBars
          baselineKey="rules"
          format={(v) => inr(v)}
          rows={w.policies.map((p: any) => ({
            key: p.policy, label: POLICY_LABEL[p.policy], value: p.net_per_case, ci: p.net_per_case_ci95, color: POLICY_COLOR[p.policy],
          }))}
        />
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="ABLATION — WHICH COMPONENT HELPS?" subtitle="Lift vs the rules policy, per failed payment, with 95% CI.">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gold-dim/20"><Th>COMPONENT ADDED</Th><Th right>LIFT ₹/CASE</Th><Th right>95% CI</Th></tr></thead>
            <tbody>
              {[["ml_risk", "Calibrated risk model (queue ranking, suppression)"], ["ml_full", "+ Thompson-sampling retry timing"]].map(([k, l]) => {
                const p = by[k];
                return (
                  <tr key={k} className="border-b border-gold-dim/10">
                    <td className="px-3 py-2 text-parchment">{l}</td>
                    <td className={`px-3 py-2 text-right font-mono ${p.lift_significant && p.lift_vs_rules_per_case > 0 ? "text-[#3fbf9f]" : "text-parchmentdim"}`}>{signed(p.lift_vs_rules_per_case, 1)}</td>
                    <td className="px-3 py-2 text-right font-mono text-parchmentdim">{p.lift_vs_rules_ci95.map((v: number) => signed(v, 0)).join(" … ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-3 text-[11px] leading-relaxed text-parchmentdim/80">
            {risk.lift_significant
              ? "The risk model helps at this review capacity."
              : `At ${cap} reviews/day the review queue is not a bottleneck, so ranking cases by expected value changes nothing — the risk model's value shows up when capacity is scarce (see the sweep below).`}
          </p>
        </Card>

        <Card title="LEARNING CURVE" subtitle="Net ₹ per case in each tenth of the run. The bandit starts cold and learns online during the evaluation.">
          <LineChart
            xLabels={w.learning_curve.map((c: any) => String(c.chunk))}
            series={[
              { name: "Rules", color: POLICY_COLOR.rules, points: w.learning_curve.map((c: any) => c.rules_net_per_case) },
              { name: "ML (full)", color: POLICY_COLOR.ml_full, points: w.learning_curve.map((c: any) => c.ml_full_net_per_case) },
            ]}
            yFormat={(v) => inr(v)}
          />
        </Card>
      </div>

      {report.capacity_sweep && (
        <Card title="WHEN DOES THE RISK MODEL MATTER? REVIEW-CAPACITY SWEEP" subtitle="Hard declines need a human to approve a customer message. When reviewers can only handle a few per day, who they look at first matters.">
          <LineChart
            xLabels={report.capacity_sweep.map((r: any) => `${r.reviews_per_day}/day`)}
            series={[
              { name: "Rules (first-come-first-served)", color: POLICY_COLOR.rules, points: report.capacity_sweep.map((r: any) => r.rules_net_per_case) },
              { name: "Risk model (ranked by expected value)", color: POLICY_COLOR.ml_risk, points: report.capacity_sweep.map((r: any) => r.ml_risk_net_per_case) },
            ]}
            yFormat={(v) => inr(v)}
          />
        </Card>
      )}

      <Card title="DID THE BANDIT FIND THE RIGHT DELAYS?" subtitle="Learned best first-retry delay vs the oracle best delay (computed from the simulator's ground truth, invisible to the policy).">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gold-dim/20"><Th>FAILURE REASON</Th><Th right>ORACLE BEST</Th><Th right>LEARNED BEST</Th><Th right>MATCH</Th></tr></thead>
            <tbody>
              {w.bandit_vs_oracle.map((r: any) => (
                <tr key={r.reason} className="border-b border-gold-dim/10">
                  <td className="px-3 py-2 text-parchment">{r.reason.replaceAll("_", " ")}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{fmtHours(r.oracle_best_delay_h)}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{fmtHours(r.learned_best_delay_h)}</td>
                  <td className={`px-3 py-2 text-right ${r.oracle_best_delay_h === r.learned_best_delay_h ? "text-[#3fbf9f]" : "text-gold-bright"}`}>
                    {r.oracle_best_delay_h === r.learned_best_delay_h ? "✓" : "near"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <BenchmarkCard />

      <Card title="ALL METRICS">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gold-dim/20">
                <Th>POLICY</Th><Th right>RECOVERY</Th><Th right>VALUE RECOVERED</Th><Th right>NET ₹/CASE</Th><Th right>RETRIES</Th><Th right>MESSAGES</Th><Th right>REVIEWS</Th><Th right>HRS TO RECOVER</Th>
              </tr>
            </thead>
            <tbody>
              {w.policies.map((p: any) => (
                <tr key={p.policy} className="border-b border-gold-dim/10">
                  <td className="px-3 py-2 text-parchment">{POLICY_LABEL[p.policy]}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{pct(p.recovery_rate, 1)}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{pct(p.value_recovery_rate, 1)}</td>
                  <td className="px-3 py-2 text-right font-mono text-gold-bright">{inr(p.net_per_case, 0)}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{p.retries_per_case.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{p.messages_per_case.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{p.reviews_per_case.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{p.mean_hours_to_recovery ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="RE-RUN THE EVALUATION" subtitle={`Generated ${report.generated_at} with model ${report.model_version}. Runs server-side in a few seconds.`}>
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-[11px] text-parchmentdim">
            FAILED PAYMENTS
            <select value={nCases} onChange={(e) => setNCases(Number(e.target.value))} className="mt-1 block rounded-sm border border-gold-dim/30 bg-charcoal px-2 py-1.5 text-sm text-parchment">
              {Array.from(new Set([1000, 2000, 4000, 6000, initial.config.n_cases])).sort((a, b) => a - b).map((n) => <option key={n} value={n}>{n.toLocaleString()}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-parchmentdim">
            REVIEWS / DAY
            <select value={cap} onChange={(e) => setCap(Number(e.target.value))} className="mt-1 block rounded-sm border border-gold-dim/30 bg-charcoal px-2 py-1.5 text-sm text-parchment">
              {Array.from(new Set([2, 4, 8, 12, 24, initial.config.approvals_per_day])).sort((a, b) => a - b).map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-parchmentdim">
            SEED
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="mt-1 block w-28 rounded-sm border border-gold-dim/30 bg-charcoal px-2 py-1.5 text-sm text-parchment" />
          </label>
          <ActionButton onClick={rerun} busy={busy} tone="gold">RE-RUN</ActionButton>
        </div>
        {err && <p className="mt-3 text-xs text-[#f0a8a5]">{err}</p>}
      </Card>
    </div>
  );
}
