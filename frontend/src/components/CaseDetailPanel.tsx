"use client";

import { useEffect, useState } from "react";
import { X, Bot, Check, XCircle, Loader2, Wand2, ShieldAlert, Brain, Timer } from "lucide-react";
import { RecoveryStatusPill, CategoryTag } from "@/components/RecoveryStatus";
import { api, ApiError } from "@/lib/api";

const AGENT_LABELS: Record<string, string> = {
  Detector: "Detection",
  Classifier: "Diagnosis",
  RiskAssessment: "Risk Assessment",
  Strategy: "Strategy",
  Timing: "Timing",
  Communication: "Communication",
  Approval: "Approval",
  Execution: "Execution",
  Verification: "Verification",
  Audit: "Audit",
  Security: "Security",
  Anomaly: "Anomaly Detection",
  Simulation: "Sandbox Simulation",
};

export function CaseDetailPanel({
  caseId,
  onClose,
  onChanged,
}: {
  caseId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const d = await api.recoveryCase(caseId);
      setDetail(d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this case.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  async function approve() {
    setBusy(true);
    try {
      await api.recoveryApprove(caseId);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not approve this case.");
    } finally {
      setBusy(false);
    }
  }

  async function holdAction(kind: "release" | "confirm") {
    setBusy(true);
    try {
      if (kind === "release") await api.recoveryReleaseHold(caseId);
      else await api.recoveryConfirmHold(caseId);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the security hold.");
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    setBusy(true);
    try {
      await api.recoveryReject(caseId, reason);
      setRejecting(false);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reject this case.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <div
        className="h-full w-full max-w-lg overflow-y-auto border-l border-gold-dim/25 bg-charcoal p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-6 flex items-center justify-between">
          <h2 className="font-display text-xl text-parchment">Recovery Case</h2>
          <button onClick={onClose} className="text-parchmentdim hover:text-gold-bright">
            <X className="h-5 w-5" />
          </button>
        </div>

        {loading && <p className="text-sm text-parchmentdim">Loading…</p>}
        {!loading && error && <p className="rounded border border-burgundy-light/40 bg-burgundy-dark/20 p-3 text-xs text-gold-bright">{error}</p>}

        {!loading && detail && (
          <div className="space-y-6">
                  <div className="rounded border border-gold-dim/20 bg-surface/40 p-4">
              <div className="mb-3 flex items-center justify-between">
                <RecoveryStatusPill status={detail.status} />
                <CategoryTag category={detail.category} />
              </div>
              <dl className="grid grid-cols-2 gap-3 text-xs">
                <Field label="Payment ID" value={detail.payment_id.slice(0, 16) + "…"} mono />
                <Field label="Order ID" value={detail.order_id ? detail.order_id.slice(0, 16) + "…" : "—"} mono />
                <Field label="Amount" value={`₹${detail.amount.toFixed(2)}`} />
                <Field label="Method" value={detail.method || "—"} />
                <Field label="Customer" value={detail.customer_email || "—"} />
                <Field label="Failure reason" value={detail.failure_reason_raw || "unknown"} />
                <Field label="Recovery probability" value={`${Math.round(detail.recovery_probability * 100)}%`} />
                <Field label="Expected value" value={`₹${detail.expected_recovery_value.toFixed(2)}`} />
                <Field label="Retries" value={`${detail.retry_count} / ${detail.max_retries}`} />
                <Field label="Messages sent" value={`${detail.communications_sent} / ${detail.max_communications}`} />
                <Field label="Recommended action" value={detail.recommended_action.replaceAll("_", " ")} />
                {detail.next_action_at && <Field label="Next action" value={new Date(detail.next_action_at).toLocaleString()} />}
                {detail.recovery_window_expires_at && (
                  <Field label="Recovery window closes" value={new Date(detail.recovery_window_expires_at).toLocaleDateString()} />
                )}
              </dl>
              {detail.payment_link_url && (
                <p className="mt-3 truncate text-xs text-gold-bright">Payment link: {detail.payment_link_url}</p>
              )}
              {detail.prepared_message && (
                <div className="mt-3 rounded border border-gold-dim/20 bg-charcoal p-3">
                  <p className="mb-1 text-[10px] tracking-widest text-parchmentdim">PREPARED MESSAGE</p>
                  <p className="text-xs text-parchment">{detail.prepared_message}</p>
                </div>
              )}
            </div>

                  {detail.status === "security_hold" && (
              <div className="rounded border border-[#c0504d]/50 bg-[#c0504d]/10 p-4">
                <p className="mb-1 flex items-center gap-2 text-sm font-semibold text-[#f0a8a5]">
                  <ShieldAlert className="h-4 w-4" /> Security hold — automation paused
                </p>
                <p className="mb-3 text-xs text-parchmentdim">
                  This customer&apos;s recent activity resembles card testing. No retry or message will be sent until you decide.
                  {detail.ml?.security?.reasons?.length > 0 && (
                    <span className="mt-2 block text-parchment">Why: {detail.ml.security.reasons.join("; ")}.</span>
                  )}
                </p>
                <div className="flex gap-3">
                  <button
                    onClick={() => holdAction("release")}
                    disabled={busy}
                    className="flex flex-1 items-center justify-center gap-2 rounded-sm border border-emerald/50 bg-emerald/15 py-2.5 text-xs font-semibold tracking-widest text-emerald-200 transition hover:bg-emerald/25 disabled:opacity-50"
                  >
                    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} LOOKS LEGITIMATE
                  </button>
                  <button
                    onClick={() => holdAction("confirm")}
                    disabled={busy}
                    className="flex flex-1 items-center justify-center gap-2 rounded-sm border border-[#c0504d]/60 py-2.5 text-xs font-semibold tracking-widest text-[#f0a8a5] transition hover:bg-[#c0504d]/20 disabled:opacity-50"
                  >
                    <XCircle className="h-3.5 w-3.5" /> CONFIRM SUSPICIOUS
                  </button>
                </div>
              </div>
            )}

            {detail.ml?.risk && detail.ml.risk.factors?.length > 0 && (
              <div className="rounded border border-[#00697C]/30 bg-[#00586A]/10 p-4">
                <p className="mb-1 flex items-center gap-2 text-[11px] tracking-widest text-parchmentdim">
                  <Brain className="h-3.5 w-3.5 text-[#5fd0d0]" /> WHY {Math.round(detail.ml.risk.probability * 100)}% RECOVERABLE
                </p>
                <p className="mb-3 text-[10px] text-parchmentdim/80">
                  Model {detail.ml.risk.model_version} · effect of each factor vs a typical failed payment (percentage points)
                </p>
                <div className="space-y-2">
                  {detail.ml.risk.factors.map((f: any) => (
                    <div key={f.factor}>
                      <div className="mb-0.5 flex justify-between text-[11px]">
                        <span className="text-parchment">
                          {f.factor} <span className="text-parchmentdim">· {f.detail}</span>
                        </span>
                        <span className={f.effect >= 0 ? "text-[#3fbf9f]" : "text-[#f0a8a5]"}>
                          {f.effect >= 0 ? "+" : ""}
                          {(f.effect * 100).toFixed(1)}
                        </span>
                      </div>
                      <div className="relative h-1.5 rounded-full bg-charcoal">
                        <div className="absolute left-1/2 top-0 h-full w-px bg-gold-dim/40" />
                        <div
                          className={`absolute top-0 h-full rounded-full ${f.effect >= 0 ? "bg-emerald" : "bg-[#c0504d]"}`}
                          style={{
                            width: `${Math.min(Math.abs(f.effect) * 100 * 1.6, 50)}%`,
                            left: f.effect >= 0 ? "50%" : undefined,
                            right: f.effect < 0 ? "50%" : undefined,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {detail.ml?.timing && (
              <div className="rounded border border-gold-dim/20 bg-surface/40 p-4">
                <p className="mb-1 flex items-center gap-2 text-[11px] tracking-widest text-parchmentdim">
                  <Timer className="h-3.5 w-3.5 text-gold" /> LEARNED RETRY TIMING
                </p>
                <p className="mb-3 text-[10px] text-parchmentdim/80">
                  Context “{String(detail.ml.timing.context).replace("|", " · ")}” — chose{" "}
                  <span className="text-gold-bright">{fmtH(detail.ml.timing.arm_hours)}</span>
                  {detail.ml.timing.outcome === 1 && " · retry succeeded"}
                  {detail.ml.timing.outcome === 0 && " · retry failed"}
                </p>
                <div className="flex h-24 items-end gap-2">
                  {detail.ml.timing.alternatives.map((a: any) => (
                    <div key={a.arm_hours} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
                      <div className="flex w-full flex-1 items-end">
                        <div
                          className={`w-full rounded-t-sm ${a.arm_hours === detail.ml.timing.arm_hours ? "bg-gold" : "bg-[#00697C]"}`}
                          style={{ height: `${Math.max(a.posterior_mean * 100, 4)}%` }}
                          title={`${(a.posterior_mean * 100).toFixed(0)}% estimated success · ${a.observations} observation(s)`}
                        />
                      </div>
                      <span className="text-[9px] text-parchmentdim">{fmtH(a.arm_hours)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

                  {detail.status === "pending_approval" && (
              <div className="rounded border border-gold/40 bg-burgundy/20 p-4">
                <p className="mb-1 flex items-center gap-2 text-sm font-semibold text-gold-bright">
                  <Wand2 className="h-4 w-4" /> Human approval required
                </p>
                <p className="mb-3 text-xs text-parchmentdim">
                  This action contacts the customer directly and needs reviewer sign-off before it executes.
                </p>
                {!rejecting ? (
                  <div className="flex gap-3">
                    <button
                      onClick={approve}
                      disabled={busy}
                      className="flex flex-1 items-center justify-center gap-2 rounded-sm border border-emerald/50 bg-emerald/15 py-2.5 text-xs font-semibold tracking-widest text-emerald-200 transition hover:bg-emerald/25 disabled:opacity-50"
                    >
                      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />} APPROVE
                    </button>
                    <button
                      onClick={() => setRejecting(true)}
                      disabled={busy}
                      className="flex flex-1 items-center justify-center gap-2 rounded-sm border border-burgundy-light/50 py-2.5 text-xs font-semibold tracking-widest text-gold-bright transition hover:bg-burgundy-dark/30 disabled:opacity-50"
                    >
                      <XCircle className="h-3.5 w-3.5" /> REJECT
                    </button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <textarea
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="Reason for rejection (recorded in the audit trail)…"
                      rows={2}
                      className="w-full rounded-sm border border-gold-dim/30 bg-charcoal px-3 py-2 text-xs text-parchment outline-none focus:border-gold"
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={reject}
                        disabled={busy}
                        className="flex-1 rounded-sm border border-burgundy-light/50 bg-burgundy-dark/30 py-2 text-xs tracking-widest text-gold-bright disabled:opacity-50"
                      >
                        CONFIRM REJECT
                      </button>
                      <button onClick={() => setRejecting(false)} className="flex-1 rounded-sm border border-gold-dim/30 py-2 text-xs tracking-widest text-parchmentdim">
                        CANCEL
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

                  {detail.communications && detail.communications.length > 0 && (
              <div>
                <p className="mb-3 text-[11px] tracking-widest text-parchmentdim">CUSTOMER COMMUNICATION</p>
                <div className="space-y-2">
                  {detail.communications.map((m: any) => (
                    <div key={m.id} className="rounded border border-[#00697C]/25 bg-[#00586A]/10 p-3">
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-xs font-semibold capitalize text-[#5fd0d0]">{m.message_type.replaceAll("_", " ")}</span>
                        <span className={`rounded-full border px-2 py-0.5 text-[9px] uppercase tracking-wider ${
                          m.status === "sent" ? "border-emerald/50 text-emerald-200" :
                          m.status === "failed" ? "border-burgundy-light/50 text-gold-bright" :
                          "border-gold-dim/40 text-parchmentdim"
                        }`}>
                          {m.status === "simulated" ? "prepared · not delivered" : m.status}
                        </span>
                      </div>
                      <p className="text-xs text-parchment">{m.content}</p>
                      <p className="mt-1 text-[10px] text-parchmentdim">{new Date(m.created_at).toLocaleString()}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

                  <div>
              <p className="mb-3 flex items-center gap-2 text-[11px] tracking-widest text-parchmentdim">
                <Bot className="h-3.5 w-3.5 text-gold" /> AI RECOVERY TRACE
              </p>
              <ol className="space-y-4 border-l border-gold-dim/20 pl-5">
                {detail.trace.map((step: any, i: number) => (
                  <li key={step.id} className="relative">
                    <span className="absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full border border-gold bg-charcoal" />
                    <p className="text-xs font-semibold tracking-widest text-gold-bright">
                      {i + 1}. {AGENT_LABELS[step.agent] || step.agent}
                    </p>
                    <p className="mt-0.5 text-sm text-parchment">{step.decision}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-parchmentdim">{step.reason}</p>
                    <p className="mt-1 text-[10px] text-parchmentdim/70">
                      {new Date(step.created_at).toLocaleTimeString()} · {step.actor}
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function fmtH(h: number | null | undefined) {
  if (h === null || h === undefined) return "—";
  return h < 1 ? `${Math.round(h * 60)}m` : `${h}h`;
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] tracking-widest text-parchmentdim">{label.toUpperCase()}</dt>
      <dd className={`mt-0.5 text-parchment ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
