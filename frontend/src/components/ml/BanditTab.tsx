"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { ArmBars } from "./Charts";
import { fmtHours } from "./format";
import { ActionButton, Banner, Card } from "./ui";

export default function BanditTab({ isTest, onChanged }: { isTest: boolean; onChanged: () => void }) {
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () => api.mlBandit().then(setData).catch(() => setErr("Could not load bandit state."));
  useEffect(() => {
    load();
  }, []);

  async function run(name: string, fn: () => Promise<string>) {
    setBusy(name);
    setErr(null);
    setMsg(null);
    try {
      setMsg(await fn());
      await load();
      onChanged();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Action failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <Banner tone="info">
        <strong className="text-gold-bright">How it works.</strong> For each failure reason the engine keeps a Beta posterior over the success rate of
        each candidate retry delay and uses <em>Thompson sampling</em>: sample once per delay, play the best sample. Exploration fades as evidence
        accumulates. The bandit only chooses <em>within</em> the guardrails — delays shorter than the cooldown (after the first retry) or past the
        recovery window are removed before it ever sees them, and retry caps / approvals are untouched. It starts nearly blank (weak prior at the old category success rates)
        and learns from the outcome of every retry that actually runs.
      </Banner>

      {isTest && (
        <Card title="SANDBOX CONTROLS" subtitle={`Sandbox ground truth is the "${data?.sandbox_world ?? "base"}" world. Set ML_SANDBOX_WORLD=shifted in the backend .env to watch the bandit adapt to changed dynamics.`}>
          <div className="flex flex-wrap gap-3">
            <ActionButton busy={busy === "learn"} tone="gold" onClick={() => run("learn", async () => {
              const r = await api.mlSimLearn(100, 6, 24);
              return `Simulated ${r.simulated_hours}h: generated ${r.cases_generated} failures, ran ${r.rounds + 1} scans. Recovery rate now ${(r.recovery_rate * 100).toFixed(0)}%, ${r.awaiting_approval} awaiting human approval.`;
            })}>RUN LEARNING DEMO (≈ 2s)</ActionButton>
            <ActionButton busy={busy === "fail"} onClick={() => run("fail", async () => `Created ${(await api.mlSimFailures(40)).created} failed payments (run a scan in Recovery Console to open cases).`)}>+40 FAILED PAYMENTS</ActionButton>
          </div>
          <p className="mt-3 text-[11px] text-parchmentdim/70">Each demo run adds ~100 failures and compresses ~6 days into a few seconds; run it a few times and watch the bars converge on the dashed ground-truth markers.</p>
          {msg && <p className="mt-3 text-xs text-parchment">{msg}</p>}
          {err && <p className="mt-3 text-xs text-[#f0a8a5]">{err}</p>}
        </Card>
      )}

      {!data && !err && <p className="text-sm text-parchmentdim">Loading…</p>}
      {data && data.contexts.length === 0 && (
        <Card><p className="text-sm text-parchmentdim">Nothing learned yet. Scan some failed payments (or run the learning demo) — every executed retry teaches the bandit.</p></Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {data?.contexts.map((c: any) => (
          <Card
            key={c.context}
            title={`${c.reason.replaceAll("_", " ").toUpperCase()} · ${c.stage === "first" ? "FIRST RETRY" : "LATER RETRIES"}`}
            subtitle={`${c.total_observations} observation(s) · ${c.best_arm_hours === null ? "not enough data to name a favourite yet" : `current favourite: ${fmtHours(c.best_arm_hours)}`}${c.sandbox_best_arm_hours !== undefined ? ` · sandbox truth: ${fmtHours(c.sandbox_best_arm_hours)}` : ""}`}
          >
            <ArmBars arms={c.arms} truth={c.sandbox_truth} best={c.best_arm_hours} sandboxBest={c.sandbox_best_arm_hours} />
            <p className="mt-3 text-[10px] text-parchmentdim/60">
              Bars: learned success estimate per delay (faded = little evidence). Dashed ticks: sandbox ground truth. Gold = current favourite.
            </p>
          </Card>
        ))}
      </div>
    </div>
  );
}
