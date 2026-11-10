"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { inr, pct } from "./format";
import { Card } from "./ui";

const REASONS = ["insufficient_funds", "otp_timeout", "issuer_unavailable", "bank_timeout", "gateway_timeout", "risk_check_failed", "card_declined", "expired_card", "unknown"];
const METHODS = ["card", "upi", "netbanking", "wallet"];

export default function WhatIfTab() {
  const [f, setF] = useState({
    reason: "insufficient_funds", method: "upi", amount: 2000, retry_count: 0, comms_sent: 0, age_hours: 0,
    hour: 14, day_of_month: 15, weekend: false, customer_payments: 6, customer_success_rate: 0.8,
  });
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    const t = setTimeout(() => {
      api.mlScore(f).then((r) => { setRes(r); setErr(null); }).catch(() => setErr("Could not score this scenario."));
    }, 250);
    return () => clearTimeout(t);
  }, [f]);

  const input = "mt-1 block w-full rounded-sm border border-gold-dim/30 bg-charcoal px-2 py-1.5 text-sm text-parchment";
  const lbl = "text-[11px] tracking-wider text-parchmentdim";
  const num = (k: string, min: number, max: number, step = 1) => (
    <input type="number" min={min} max={max} step={step} value={(f as any)[k]} className={input}
      onChange={(e) => set(k, e.target.value === "" ? 0 : Number(e.target.value))} />
  );

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <Card title="HYPOTHETICAL FAILED PAYMENT" subtitle="Change anything — the live model re-scores instantly." className="lg:col-span-2">
        <div className="grid grid-cols-2 gap-3">
          <label className={lbl}>FAILURE REASON
            <select className={input} value={f.reason} onChange={(e) => set("reason", e.target.value)}>
              {REASONS.map((r) => <option key={r} value={r}>{r.replaceAll("_", " ")}</option>)}
            </select>
          </label>
          <label className={lbl}>METHOD
            <select className={input} value={f.method} onChange={(e) => set("method", e.target.value)}>
              {METHODS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className={lbl}>AMOUNT (₹){num("amount", 1, 10000000, 100)}</label>
          <label className={lbl}>HOURS SINCE FAILURE{num("age_hours", 0, 720)}</label>
          <label className={lbl}>RETRIES SO FAR{num("retry_count", 0, 10)}</label>
          <label className={lbl}>MESSAGES SENT{num("comms_sent", 0, 10)}</label>
          <label className={lbl}>HOUR OF DAY (0-23){num("hour", 0, 23)}</label>
          <label className={lbl}>DAY OF MONTH{num("day_of_month", 1, 31)}</label>
          <label className={lbl}>CUSTOMER&apos;S PAST PAYMENTS{num("customer_payments", 0, 10000)}</label>
          <label className={lbl}>THEIR SUCCESS RATE{num("customer_success_rate", 0, 1, 0.05)}</label>
        </div>
        <label className="mt-3 flex items-center gap-2 text-xs text-parchmentdim">
          <input type="checkbox" checked={f.weekend} onChange={(e) => set("weekend", e.target.checked)} /> Weekend
        </label>
        {err && <p className="mt-3 text-xs text-[#f0a8a5]">{err}</p>}
      </Card>

      <div className="space-y-6 lg:col-span-3">
        {res && (
          <>
            <Card>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <p className="text-[10px] tracking-widest text-parchmentdim">MODEL SAYS</p>
                  <p className="font-display text-4xl text-gold-bright">{pct(res.probability)}</p>
                  <p className="text-[11px] text-parchmentdim/80">recoverable</p>
                </div>
                <div>
                  <p className="text-[10px] tracking-widest text-parchmentdim">OLD STATIC RULE SAID</p>
                  <p className="font-display text-4xl text-parchmentdim">{pct(res.rules_baseline_probability)}</p>
                  <p className="text-[11px] text-parchmentdim/80">for “{res.category.replace("_", " ")}”</p>
                </div>
                <div>
                  <p className="text-[10px] tracking-widest text-parchmentdim">EXPECTED VALUE</p>
                  <p className="font-display text-4xl text-[#3fbf9f]">{inr(res.expected_value)}</p>
                  <p className="text-[11px] text-parchmentdim/80">amount × probability</p>
                </div>
              </div>
            </Card>
            <Card title="WHY" subtitle={`Effect of each factor vs a typical failed payment, in percentage points · ${res.model_version}`}>
              <div className="space-y-3">
                {res.factors.map((x: any) => (
                  <div key={x.factor}>
                    <div className="mb-1 flex justify-between text-xs">
                      <span className="text-parchment">{x.factor} <span className="text-parchmentdim">· {x.detail}</span></span>
                      <span className={x.effect >= 0 ? "text-[#3fbf9f]" : "text-[#f0a8a5]"}>{x.effect >= 0 ? "+" : ""}{(x.effect * 100).toFixed(1)}</span>
                    </div>
                    <div className="relative h-2 rounded-full bg-charcoal">
                      <div className="absolute left-1/2 top-0 h-full w-px bg-gold-dim/40" />
                      <div className={`absolute top-0 h-full rounded-full ${x.effect >= 0 ? "bg-emerald" : "bg-[#c0504d]"}`}
                        style={{ width: `${Math.min(Math.abs(x.effect) * 100 * 1.4, 50)}%`, left: x.effect >= 0 ? "50%" : undefined, right: x.effect < 0 ? "50%" : undefined }} />
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-[10px] text-parchmentdim/60">Try: insufficient funds at hour 0 vs after 48h; OTP timeout immediately vs next day; a ₹90,000 payment; day 3 vs day 15.</p>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
