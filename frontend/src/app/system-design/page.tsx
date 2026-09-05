import Navbar from "@/components/Navbar";
import { ArrowDown, Lock, Zap, FlaskConical, Database, Bot } from "lucide-react";

const LAYERS = [
  { icon: Zap, title: "User", desc: "Signs in via the Command Center and picks an environment." },
  { icon: Lock, title: "Authentication", desc: "Email + password, with email-OTP verification at signup." },
  { icon: Bot, title: "Agent / Backend", desc: "FastAPI backend brokers every request — the browser never talks to Razorpay directly." },
];

export default function SystemDesignPage() {
  return (
    <main className="min-h-screen bg-grid">
      <Navbar />

      <section className="mx-auto max-w-5xl px-6 py-20">
        <p className="font-mono text-xs tracking-[0.25em] text-gold">ARCHITECTURE </p>
        <h1 className="mt-3 font-display text-4xl text-parchment md:text-5xl">Sytem Overview</h1>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-parchmentdim">
          Reparo AI is built around one non-negotiable rule: the dashboard and the AI agent never
          know or care whether they're looking at your real Razorpay account or a simulated one —
          only the backend's environment router does.
        </p>

        <div className="mt-14 space-y-2">
          {LAYERS.map(({ icon: Icon, title, desc }, i) => (
            <div key={title}>
              <div className="glass-panel flex items-center gap-4 rounded-lg p-5">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-burgundy/30">
                  <Icon className="h-4 w-4 text-gold-bright" />
                </div>
                <div>
                  <p className="font-display text-parchment">{title}</p>
                  <p className="text-xs text-parchmentdim">{desc}</p>
                </div>
              </div>
              {i < LAYERS.length - 1 && <ArrowDown className="mx-auto my-2 h-4 w-4 text-gold-dim" />}
            </div>
          ))}

          <ArrowDown className="mx-auto my-2 h-4 w-4 text-gold-dim" />

          <div className="rounded-lg border border-gold/40 bg-surface/50 p-5 text-center">
            <p className="font-display text-parchment">Environment Router</p>
            <p className="text-xs text-parchmentdim">Reads the authenticated user's fixed environment (live / test) before every data request.</p>
          </div>

          <ArrowDown className="mx-auto my-2 h-4 w-4 text-gold-dim" />

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="rounded-lg border border-gold/40 bg-burgundy/20 p-6 text-center">
              <Zap className="mx-auto mb-2 h-5 w-5 text-gold-bright" />
              <p className="font-display text-parchment">Live Mode</p>
              <p className="mt-1 text-xs text-parchmentdim">RazorpayProvider → official Razorpay API, using your encrypted, server-only credentials.</p>
            </div>
            <div className="rounded-lg border border-emerald/40 bg-emerald/10 p-6 text-center">
              <FlaskConical className="mx-auto mb-2 h-5 w-5 text-emerald-300" />
              <p className="font-display text-parchment">Test Mode</p>
              <p className="mt-1 text-xs text-parchmentdim">SimulationProvider → a stateful simulation database with realistic, evolving data.</p>
            </div>
          </div>

          <ArrowDown className="mx-auto my-2 h-4 w-4 text-gold-dim" />

          <div className="rounded-lg border border-gold/40 bg-surface/50 p-5 text-center">
            <Database className="mx-auto mb-2 h-5 w-5 text-gold-bright" />
            <p className="font-display text-parchment">Common Normalized Data Model</p>
            <p className="text-xs text-parchmentdim">Both providers return the exact same Payment / Order / Refund / Customer shape.</p>
          </div>

          <ArrowDown className="mx-auto my-2 h-4 w-4 text-gold-dim" />

          <div className="rounded-lg border border-gold/40 bg-burgundy/30 p-6 text-center shadow-glow">
            <p className="font-display text-lg text-gold-bright">Dashboard + AI Agent</p>
            <p className="mt-1 text-xs text-parchmentdim">One frontend, one tool layer — powered by whichever environment is active.</p>
          </div>
        </div>

        <div className="mt-16 grid grid-cols-1 gap-6 md:grid-cols-3">
          <SecurityCard title="Secrets stay server-side" body="Your Razorpay Key Secret is encrypted at rest and only ever decrypted inside the backend, at the moment of an outbound Razorpay call." />
          <SecurityCard title="Signed webhooks" body="Incoming Razorpay webhook events are verified against a shared secret before being processed, with duplicate-event protection." />
          <SecurityCard title="Agent tool layer" body="The AI agent can only call a fixed set of backend tools — it can't issue arbitrary requests to Razorpay or see raw credentials." />
        </div>
      </section>
    </main>
  );
}

function SecurityCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded border border-gold-dim/20 bg-surface/40 p-6">
      <h3 className="font-display text-parchment">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-parchmentdim">{body}</p>
    </div>
  );
}
