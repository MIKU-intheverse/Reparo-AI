"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck, ShieldAlert, ShieldX, Loader2, Sparkles } from "lucide-react";
import DashboardShell from "@/components/DashboardShell";
import { LoadingBlock } from "@/components/DataStates";
import { api, ApiError, getEnvironment } from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const [environment, setEnv] = useState<string | null>(null);
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [simBusy, setSimBusy] = useState(false);

  useEffect(() => {
    api
      .me()
      .then((me) => {
        setEnv(me.environment);
        if (me.environment === "live") {
          return api.razorpayStatus().then(setStatus);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  async function refreshConnection() {
    setBusy(true);
    setMessage(null);
    try {
      await api.razorpayTestConnection();
      setMessage("Connection verified.");
      const s = await api.razorpayStatus();
      setStatus(s);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not verify connection.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!confirm("Disconnect Razorpay? You will need to reconnect before viewing live data again.")) return;
    setBusy(true);
    try {
      await api.razorpayDisconnect();
      router.push("/connect");
    } finally {
      setBusy(false);
    }
  }

  async function simulate(shouldFail: boolean) {
    setSimBusy(true);
    setMessage(null);
    try {
      const p = await api.simulatePayment(shouldFail);
      setMessage(`Created simulated ${p.status} payment of ₹${p.amount.toFixed(2)} — visible in Payments now.`);
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not create simulated payment.");
    } finally {
      setSimBusy(false);
    }
  }

  if (loading) {
    return (
      <DashboardShell>
        <LoadingBlock />
      </DashboardShell>
    );
  }

  return (
    <DashboardShell>
      <div className="max-w-2xl space-y-8">
        {environment === "live" && (
          <section className="rounded-lg border border-gold-dim/20 bg-surface/40 p-6">
            <h2 className="font-display text-xl text-parchment">Razorpay Connection</h2>
            <p className="mt-1 text-sm text-parchmentdim">Manage your live Razorpay Client connection.</p>

            <div className="mt-5 flex items-center gap-3">
              {status?.status === "connected" && <ShieldCheck className="h-5 w-5 text-emerald-300" />}
              {status?.status === "error" && <ShieldAlert className="h-5 w-5 text-gold-bright" />}
              {status?.status === "disconnected" && <ShieldX className="h-5 w-5 text-parchmentdim" />}
              <div>
                <p className="text-sm text-parchment">
                  {status?.status === "connected" ? "● Connected" : status?.status === "error" ? "⚠ Connection Error" : "○ Not Connected"}
                </p>
                {status?.key_id && <p className="font-mono text-xs text-parchmentdim">{status.key_id}</p>}
                {status?.last_synced_at && (
                  <p className="text-xs text-parchmentdim">Last synced: {new Date(status.last_synced_at).toLocaleString()}</p>
                )}
              </div>
            </div>

            {message && <p className="mt-4 rounded border border-gold-dim/20 bg-charcoal px-3 py-2 text-xs text-parchmentdim">{message}</p>}

            <div className="mt-5 flex gap-3">
              <button
                onClick={refreshConnection}
                disabled={busy}
                className="flex items-center gap-2 rounded-sm border border-gold/40 px-4 py-2 text-xs tracking-widest text-gold-bright transition hover:bg-gold/10 disabled:opacity-50"
              >
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} TEST CONNECTION
              </button>
              <button
                onClick={disconnect}
                disabled={busy}
                className="rounded-sm border border-burgundy-light/50 px-4 py-2 text-xs tracking-widest text-gold-bright transition hover:bg-burgundy-dark/30 disabled:opacity-50"
              >
                DISCONNECT
              </button>
            </div>
          </section>
        )}

        {environment === "test" && (
          <section className="rounded-lg border border-gold-dim/20 bg-surface/40 p-6">
            <div className="mb-1 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-gold" />
              <h2 className="font-display text-xl text-parchment">Demo / Test Tools</h2>
            </div>
            <p className="text-sm text-parchmentdim">
              Simulate a failed payment, then head to the Recovery Console and click "Run Recovery Scan" to watch
              Reparo detect it, diagnose the cause, and work it through the recovery pipeline end to end.
            </p>

            {message && <p className="mt-4 rounded border border-gold-dim/20 bg-charcoal px-3 py-2 text-xs text-parchmentdim">{message}</p>}

            <div className="mt-5 flex gap-3">
              <button
                onClick={() => simulate(false)}
                disabled={simBusy}
                className="flex items-center gap-2 rounded-sm border border-emerald/50 bg-emerald/10 px-4 py-2 text-xs tracking-widest text-emerald-200 transition hover:bg-emerald/20 disabled:opacity-50"
              >
                {simBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} SIMULATE SUCCESSFUL PAYMENT
              </button>
              <button
                onClick={() => simulate(true)}
                disabled={simBusy}
                className="flex items-center gap-2 rounded-sm border border-burgundy-light/50 px-4 py-2 text-xs tracking-widest text-gold-bright transition hover:bg-burgundy-dark/30 disabled:opacity-50"
              >
                {simBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} SIMULATE FAILED PAYMENT
              </button>
            </div>
          </section>
        )}

        <section className="rounded-lg border border-gold-dim/20 bg-surface/40 p-6">
          <h2 className="font-display text-xl text-parchment">Environment</h2>
          <p className="mt-2 text-sm text-parchmentdim">
            This account operates permanently in <strong className="text-parchment">{environment === "live" ? "Razorpay Client / Live Mode" : "Test Mode"}</strong>.
            To use the other environment, create a separate account from the Command Center.
          </p>
        </section>
      </div>
    </DashboardShell>
  );
}
