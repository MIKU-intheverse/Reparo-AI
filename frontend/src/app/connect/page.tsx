"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck, KeyRound } from "lucide-react";
import { api, ApiError } from "@/lib/api";

export default function ConnectRazorpayPage() {
  const router = useRouter();
  const [keyId, setKeyId] = useState("");
  const [keySecret, setKeySecret] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api
      .razorpayStatus()
      .then((s) => {
        if (s.connected) router.push("/dashboard");
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [router]);

  async function handleConnect(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.razorpayConnect(keyId.trim(), keySecret.trim());
      router.push("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Connection failed. ${err.message}`
          : "Unable to connect to Razorpay. Please verify your Key ID, Key Secret, and API permissions."
      );
    } finally {
      setLoading(false);
    }
  }

  if (checking) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-obsidian">
        <Loader2 className="h-6 w-6 animate-spin text-gold" />
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-grid px-6">
      <div className="w-full max-w-lg">
        <div className="mb-8 flex items-center gap-2 text-gold">
          <ShieldCheck className="h-5 w-5" strokeWidth={1.5} />
          <span className="text-xs tracking-[0.25em]">SECURE CONNECTION</span>
        </div>

        <h1 className="font-display text-3xl text-parchment">Connect your Razorpay account</h1>
        <p className="mt-3 text-sm leading-relaxed text-parchmentdim">
          Your Key Secret is sent directly to our backend over HTTPS, validated against the real
          Razorpay API, encrypted at rest, and never returned to this browser again.
        </p>

        <form onSubmit={handleConnect} className="glass-panel mt-8 space-y-5 rounded-lg p-8">
          <label className="block">
            <span className="mb-1.5 flex items-center gap-1.5 text-[11px] tracking-widest text-parchmentdim">
              <KeyRound className="h-3 w-3" /> RAZORPAY KEY ID
            </span>
            <input
              value={keyId}
              onChange={(e) => setKeyId(e.target.value)}
              placeholder="rzp_live_XXXXXXXXXXXXXX"
              required
              className="w-full rounded-sm border border-gold-dim/30 bg-charcoal px-4 py-3 font-mono text-sm text-parchment outline-none transition focus:border-gold"
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[11px] tracking-widest text-parchmentdim">RAZORPAY KEY SECRET</span>
            <input
              type="password"
              value={keySecret}
              onChange={(e) => setKeySecret(e.target.value)}
              placeholder="••••••••••••••••••••"
              required
              autoComplete="off"
              className="w-full rounded-sm border border-gold-dim/30 bg-charcoal px-4 py-3 font-mono text-sm text-parchment outline-none transition focus:border-gold"
            />
          </label>

          {error && (
            <p className="rounded border border-burgundy-light/50 bg-burgundy-dark/20 px-3 py-2 text-xs leading-relaxed text-gold-bright">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-sm border border-gold/50 bg-burgundy py-3.5 text-sm font-semibold tracking-widest text-parchment transition hover:bg-burgundy-light disabled:opacity-60"
          >
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            {loading ? "VALIDATING WITH RAZORPAY…" : "TEST CONNECTION & CONNECT"}
          </button>

          <p className="text-center text-[11px] text-parchmentdim">
            Don't have real credentials yet?{" "}
            <a href="/command-center" className="text-gold-bright hover:underline">
              Try Test Mode instead
            </a>
            .
          </p>
        </form>
      </div>
    </main>
  );
}
