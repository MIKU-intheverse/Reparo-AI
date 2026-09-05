"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Sparkles, Zap, FlaskConical, Loader2 } from "lucide-react";
import { api, setEnvironment, setToken } from "@/lib/api";
import { ApiError } from "@/lib/api";

type Mode = "live" | "test";
type Screen = "select" | "signin" | "signup-email" | "signup-otp" | "signup-password";

export default function CommandCenterPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode | null>(null);
  const [screen, setScreen] = useState<Screen>("select");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function pickMode(m: Mode) {
    setMode(m);
    setScreen("select");
    setError(null);
  }

  async function handleSignin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await api.signin(email, password);
      setToken(res.access_token);
      setEnvironment(res.environment);
      routeAfterAuth(res.environment);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSignupStart(e: React.FormEvent) {
    e.preventDefault();
    if (!mode) return;
    setLoading(true);
    setError(null);
    try {
      await api.signupStart(email, mode);
      setInfo(`We emailed a verification code to ${email}.`);
      setScreen("signup-otp");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyOtp(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.signupVerify(email, code);
      setScreen("signup-password");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCompleteSignup(e: React.FormEvent) {
    e.preventDefault();
    if (!mode) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.signupComplete(email, password, mode);
      setToken(res.access_token);
      setEnvironment(res.environment);
      routeAfterAuth(res.environment);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  function routeAfterAuth(environment: string) {
    if (environment === "live") router.push("/connect");
    else router.push("/dashboard");
  }

  return (
    <main className="grid min-h-screen grid-cols-1 bg-grid md:grid-cols-2">
      <div className="relative flex flex-col justify-between border-r border-gold-dim/20 bg-charcoal p-10">
        <Link href="/" className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-gold" strokeWidth={1.5} />
          <span className="font-display text-xl text-parchment">Reparo AI</span>
        </Link>

        <div>
          <p className="mb-3 font-mono text-xs tracking-[0.25em] text-gold">COMMAND CENTER</p>
          <h1 className="font-display text-4xl leading-tight text-parchment md:text-5xl">
            Clarity for every
            <br />
            payment operation.
          </h1>
          <p className="mt-6 max-w-md text-sm leading-relaxed text-parchmentdim">
            See what happened across your Razorpay account, what Reparo's agent recommends, and
            the real data behind every number — live, or in a fully simulated sandbox.
          </p>
        </div>

        <p className="max-w-sm border-t border-gold-dim/20 pt-6 text-xs italic leading-relaxed text-parchmentdim">
          "The cheapest insight to act on is the one you can already trust."
        </p>
      </div>


      <div className="flex items-center justify-center p-10">
        <div className="w-full max-w-md">
          {!mode && (
            <div>
              <p className="mb-8 text-sm text-parchmentdim">Choose an environment to continue.</p>
              <div className="space-y-4">
                <ModeCard
                  icon={Zap}
                  title="Razorpay Client"
                  desc="Connect to your real Razorpay environment."
                  onClick={() => pickMode("live")}
                />
                <ModeCard
                  icon={FlaskConical}
                  title="Test Mode"
                  desc="Explore Reparo AI using a simulated Razorpay environment — no real credentials needed."
                  onClick={() => pickMode("test")}
                />
              </div>
            </div>
          )}

          {mode && screen === "select" && (
            <div>
              <button onClick={() => setMode(null)} className="mb-6 text-xs tracking-widest text-parchmentdim hover:text-gold-bright">
                ← CHANGE ENVIRONMENT
              </button>
              <div className="mb-6 flex items-center gap-2">
                <span className="rounded-full border border-gold/40 px-3 py-1 text-[10px] tracking-widest text-gold-bright">
                  {mode === "live" ? "RAZORPAY CLIENT" : "TEST MODE"}
                </span>
              </div>
              <h2 className="font-display text-2xl text-parchment">Welcome back, operator.</h2>
              <div className="mt-6 flex gap-3 text-xs tracking-widest">
                <button
                  onClick={() => setScreen("signin")}
                  className="flex-1 rounded-sm border border-gold/50 bg-burgundy py-3 text-parchment transition hover:bg-burgundy-light"
                >
                  SIGN IN
                </button>
                <button
                  onClick={() => setScreen("signup-email")}
                  className="flex-1 rounded-sm border border-parchmentdim/20 py-3 text-parchmentdim transition hover:border-gold/40 hover:text-gold-bright"
                >
                  CREATE ACCOUNT
                </button>
              </div>
            </div>
          )}

          {mode && screen === "signin" && (
            <form onSubmit={handleSignin} className="space-y-5">
              <BackButton onClick={() => setScreen("select")} />
              <h2 className="font-display text-2xl text-parchment">Sign in</h2>
              <Field label="EMAIL" type="email" value={email} onChange={setEmail} required />
              <Field label="PASSWORD" type="password" value={password} onChange={setPassword} required />
              {error && <ErrorText text={error} />}
              <SubmitButton loading={loading} label="Sign in" />
            </form>
          )}

          {mode && screen === "signup-email" && (
            <form onSubmit={handleSignupStart} className="space-y-5">
              <BackButton onClick={() => setScreen("select")} />
              <h2 className="font-display text-2xl text-parchment">Create your account</h2>
              <Field label="EMAIL" type="email" value={email} onChange={setEmail} required />
              {error && <ErrorText text={error} />}
              <SubmitButton loading={loading} label="Send verification code" />
            </form>
          )}

          {mode && screen === "signup-otp" && (
            <form onSubmit={handleVerifyOtp} className="space-y-5">
              <BackButton onClick={() => setScreen("signup-email")} />
              <h2 className="font-display text-2xl text-parchment">Verify your email</h2>
              {info && <p className="text-xs text-parchmentdim">{info}</p>}
              <Field label="VERIFICATION CODE" type="text" value={code} onChange={setCode} required maxLength={6} />
              {error && <ErrorText text={error} />}
              <SubmitButton loading={loading} label="Verify" />
            </form>
          )}

          {mode && screen === "signup-password" && (
            <form onSubmit={handleCompleteSignup} className="space-y-5">
              <h2 className="font-display text-2xl text-parchment">Create a password</h2>
              <p className="text-xs text-parchmentdim">Email verified — last step.</p>
              <Field label="PASSWORD" type="password" value={password} onChange={setPassword} required minLength={8} />
              {error && <ErrorText text={error} />}
              <SubmitButton loading={loading} label="Create account" />
            </form>
          )}
        </div>
      </div>
    </main>
  );
}

function ModeCard({ icon: Icon, title, desc, onClick }: any) {
  return (
    <button
      onClick={onClick}
      className="group flex w-full items-start gap-4 rounded border border-gold-dim/25 bg-surface/50 p-5 text-left transition hover:border-gold/60 hover:bg-surface"
    >
      <Icon className="mt-1 h-5 w-5 text-gold" strokeWidth={1.5} />
      <div>
        <p className="font-display text-lg text-parchment">{title}</p>
        <p className="mt-1 text-sm text-parchmentdim">{desc}</p>
      </div>
    </button>
  );
}

function Field({ label, type, value, onChange, ...rest }: any) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] tracking-widest text-parchmentdim">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-sm border border-gold-dim/30 bg-charcoal px-4 py-3 text-sm text-parchment outline-none transition focus:border-gold"
        {...rest}
      />
    </label>
  );
}

function SubmitButton({ loading, label }: { loading: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="flex w-full items-center justify-center gap-2 rounded-sm border border-gold/50 bg-burgundy py-3.5 text-sm font-semibold tracking-widest text-parchment transition hover:bg-burgundy-light disabled:opacity-60"
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {label.toUpperCase()}
    </button>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="text-xs tracking-widest text-parchmentdim hover:text-gold-bright">
      ← BACK
    </button>
  );
}

function ErrorText({ text }: { text: string }) {
  return <p className="rounded border border-burgundy-light/50 bg-burgundy-dark/20 px-3 py-2 text-xs text-gold-bright">{text}</p>;
}
