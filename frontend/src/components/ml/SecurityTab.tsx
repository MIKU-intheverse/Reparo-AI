"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { fmtHours, pct } from "./format";
import { ActionButton, Banner, Card, Stat } from "./ui";

export default function SecurityTab({ card, isTest, onChanged }: { card: any; isTest: boolean; onChanged: () => void }) {
  const [alerts, setAlerts] = useState<any[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [method, setMethod] = useState("upi");
  const [real, setReal] = useState<any>(null);
  const ct = card?.card_testing, od = card?.outage_detection;

  const load = () => api.mlAlerts("all").then((r) => setAlerts(r.items)).catch(() => setErr("Could not load alerts."));
  useEffect(() => {
    load();
    api.mlRealdata().then(setReal).catch(() => setReal(null));
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
        Two detectors with <strong>different actions</strong>. <strong>Card testing</strong> (Isolation Forest on per-customer velocity features): the case goes on a
        <em> security hold</em> — no retry, no customer message — until a human decides. <strong>Method outage</strong> (exact binomial test vs the method&apos;s own baseline):
        retries for that method are <em>deferred</em> without consuming the bounded retry budget, then resume when the spike clears.
      </Banner>

      {card && (
        <>
          <Banner tone="warn">{card.data_provenance} Attack windows are blatant by construction, so near-perfect separation is expected; the useful claims are the low false-positive rate and the explicit minimum-evidence guard.</Banner>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="CARD TESTING · RECALL" value={pct(ct.deployed_rule_recall, 1)} sub={`signature rule alone: ${pct(ct.signature_rule_recall, 1)}`} tone="good" />
            <Stat label="CARD TESTING · FALSE POSITIVES" value={pct(ct.deployed_rule_false_positive_rate, 2)} sub={`on ${ct.benign_test_windows.toLocaleString()} benign windows incl. hard negatives`} />
            <Stat label="OUTAGE · RECALL" value={pct(od.recall, 0)} sub={`${od.outages_detected} injected outages · median delay ${od.median_detection_delay_min} min`} />
            <Stat label="OUTAGE · FALSE ALARMS" value={`${od.false_alarm_episodes_per_month}/mo`} sub="exact binomial test, α = 1e-4" />
          </div>
          <Card title="OUTAGE RECALL BY PAYMENT METHOD" subtitle={od.note}>
            <div className="grid grid-cols-3 gap-4">
              {Object.entries(od.by_method).map(([m, v]: [string, any]) => (
                <div key={m} className="rounded border border-gold-dim/15 p-3">
                  <p className="text-xs uppercase tracking-widest text-parchmentdim">{m}</p>
                  <p className="mt-1 font-display text-xl text-gold-bright">{v.detected}/{v.outages}</p>
                  <p className="text-[10px] text-parchmentdim/70">≈{v.avg_payments_per_hour} payments/hour</p>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {real && (
        <Card title="REAL-DATA CHECK — UCI ONLINE RETAIL" subtitle={`${real.dataset.invoices_used.toLocaleString()} real invoices from ${real.dataset.customers} customers (${real.dataset.period[0]} → ${real.dataset.period[1]}). ${real.dataset.limits}`}>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="AMOUNT SPREAD (LOG-SD)" value={`${real.amount_shape.real_log_sd}`} sub={`simulator assumes ${real.amount_shape.simulator_log_sd.toFixed(1)}`} tone="good" />
            <Stat label="REPEAT WITHIN 10 MIN" value={pct(real.activity.share_of_invoices_with_a_repeat_within_10min, 1)} sub={`one customer placed ${real.activity.invoices_per_customer_max} invoices in a week`} />
            <Stat label="HOLDS · EVERY ATTEMPT FAILS" value={pct(real.detector_stress.worst_case_all_attempts_fail.rate, 1)} sub={`${real.detector_stress.worst_case_all_attempts_fail.customers_flagged} wholesale customer(s) · pessimistic upper bound`} tone="bad" />
            <Stat label="HOLDS · REALISTIC FAILURES" value={pct(real.detector_stress.realistic.hold_rate_mean, 1)} sub={`${(real.detector_stress.realistic.failure_probability * 100).toFixed(0)}% failure rate, ${real.detector_stress.realistic.trials} random draws`} tone="good" />
          </div>
          <ul className="mt-4 list-disc space-y-1.5 pl-5 text-[11px] leading-relaxed text-parchmentdim">
            {real.interpretation.map((t: string) => <li key={t}>{t}</li>)}
          </ul>
          <p className="mt-3 text-[10px] text-parchmentdim/60">Reproduce: <code>python -m app.ml.realdata</code> (add <code>--path Online_Retail.csv</code> for the full UCI data set). {real.dataset.licence_note}</p>
        </Card>
      )}

      {isTest && (
        <Card title="TRY IT — SANDBOX INCIDENTS" subtitle="Inject a realistic incident, then scan. Cases appear in the Recovery Console (filter: Security Hold) or show “Retry deferred” in their trace.">
          <div className="flex flex-wrap items-center gap-3">
            <ActionButton busy={busy === "ct"} tone="red" onClick={() => run("ct", async () => {
              const r = await api.mlSimIncident("card_testing");
              await api.recoveryScan();
              return r.message + " Scan complete — check Security Hold cases.";
            })}>INJECT CARD-TESTING BURST + SCAN</ActionButton>
            <span className="text-parchmentdim">or</span>
            <select value={method} onChange={(e) => setMethod(e.target.value)} className="rounded-sm border border-gold-dim/30 bg-charcoal px-2 py-2 text-xs text-parchment">
              {["upi", "card", "netbanking", "wallet"].map((m) => <option key={m} value={m}>{m.toUpperCase()}</option>)}
            </select>
            <ActionButton busy={busy === "out"} tone="gold" onClick={() => run("out", async () => {
              const r = await api.mlSimIncident("outage", method);
              await api.recoveryScan();
              return r.message + " Scan complete — affected retries are deferred.";
            })}>INJECT OUTAGE + SCAN</ActionButton>
            <ActionButton busy={busy === "ff"} onClick={() => run("ff", async () => {
              await api.recoveryAdvance(3);
              await api.recoveryScan();
              return "Advanced 3 hours and scanned: the outage window has passed, so the alert resolves and deferred retries resume.";
            })}>+3H & SCAN</ActionButton>
          </div>
          {msg && <p className="mt-3 text-xs text-parchment">{msg}</p>}
          {err && <p className="mt-3 text-xs text-[#f0a8a5]">{err}</p>}
        </Card>
      )}

      <Card title="ALERTS" subtitle="Newest first. Card-testing alerts close once every held case is decided; outage alerts resolve after 30 quiet minutes.">
        {alerts.length === 0 && <p className="text-sm text-parchmentdim">No alerts yet.</p>}
        <div className="space-y-3">
          {alerts.map((a) => (
            <div key={a.id} className={`rounded border p-4 ${a.status === "open" ? (a.kind === "card_testing" ? "border-[#c0504d]/50 bg-[#c0504d]/10" : "border-gold-dim/50 bg-gold/5") : "border-gold-dim/15 opacity-70"}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-parchment">
                  {a.kind === "card_testing" ? "Suspected card testing" : `Suspected ${String(a.subject).toUpperCase()} outage`}
                  <span className="ml-2 text-xs text-parchmentdim">{a.kind === "card_testing" ? a.subject : ""}</span>
                </p>
                <div className="flex items-center gap-3">
                  <span className="rounded-sm border border-gold-dim/30 px-2 py-0.5 text-[10px] tracking-widest text-parchmentdim">{a.status.toUpperCase()}</span>
                  {a.status === "open" && (
                    <button onClick={() => api.mlAckAlert(a.id).then(load)} className="text-[11px] tracking-widest text-[#5fd0d0] hover:underline">ACKNOWLEDGE</button>
                  )}
                </div>
              </div>
              {a.kind === "card_testing" ? (
                <div className="mt-2 text-xs text-parchmentdim">
                  Anomaly score {a.score} (threshold {a.details.threshold?.toFixed?.(2)}) · {a.details.case_ids?.length ?? 0} case(s) · {a.details.features?.n_failed} failures in the hour
                  {a.details.reasons?.length > 0 && <p className="mt-1 text-parchment">{a.details.reasons.join("; ")}.</p>}
                  <Link href="/dashboard" className="mt-1 inline-block text-[#5fd0d0] hover:underline">Review held cases in the Recovery Console →</Link>
                </div>
              ) : (
                <p className="mt-2 text-xs text-parchmentdim">
                  {a.details.failures}/{a.details.attempts} recent payments failed ({pct(a.details.failure_rate)}) vs a {pct(a.details.baseline_rate)} baseline · {pct(a.details.infra_share)} gateway/bank errors · retries deferred in {fmtHours(1)} steps, never consuming the retry budget
                </p>
              )}
              <p className="mt-1 text-[10px] text-parchmentdim/60">first seen {new Date(a.created_at + "Z").toLocaleString()} · last seen {new Date(a.last_seen_at + "Z").toLocaleString()}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
