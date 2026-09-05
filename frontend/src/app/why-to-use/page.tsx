import Link from "next/link";
import Navbar from "@/components/Navbar";
import {
  Layers,
  Radar,
  Sparkles,
  Wand2,
  Send,
  BrainCircuit,
  ScrollText,
  ShieldCheck,
  ArrowRight,
} from "lucide-react";

const REASONS = [
  {
    icon: Layers,
    title: "Unified Razorpay operations",
    body: "Payments, orders, refunds, settlements, disputes, and customers in one command center instead of switching between Razorpay and spreadsheets.",
  },
  {
    icon: Radar,
    title: "Real-time visibility",
    body: "Refresh on demand, or let signed Razorpay webhooks keep your operational view current as payment events happen.",
  },
  {
    icon: Sparkles,
    title: "AI operations agent",
    body: "Ask operational questions in plain language and get answers grounded in real Razorpay data through tool calls — never fabricated numbers.",
  },
  {
    icon: Wand2,
    title: "Automated recovery",
    body: "Detect failed payments, diagnose the failure, select the next recovery action, and move cases through the recovery pipeline automatically.",
  },
  {
    icon: Send,
    title: "Customer recovery channel",
    body: "Send timely recovery messages and follow-ups to customers through configured communication channels instead of relying on manual outreach.",
  },
  {
    icon: BrainCircuit,
    title: "Intelligent recovery decisions",
    body: "Classify payment failures, estimate recovery probability, and recommend the safest next action based on the case context.",
  },
  {
    icon: ScrollText,
    title: "Complete audit trails",
    body: "Record recovery decisions, actions, timestamps, outcomes, and communication history so every important operation remains traceable.",
  },
  {
    icon: ShieldCheck,
    title: "Approval & control",
    body: "Keep sensitive recovery actions under human control with approval workflows, retry limits, and safe operational boundaries.",
  },
];

export default function WhyToUsePage() {
  return (
    <main className="min-h-screen bg-grid">
      <Navbar />

      <section className="mx-auto max-w-6xl px-6 py-20">
        <p className="font-mono text-xs tracking-[0.25em] text-gold">
          VALUE
        </p>

        <h1 className="mt-3 font-display text-4xl text-parchment md:text-5xl">
          Why to use Reparo AI
        </h1>

        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-parchmentdim">
          Reparo AI turns a Razorpay account into an operational command center
          — an AI-powered system that detects problems, reasons over real data,
          takes controlled recovery actions, communicates with customers, and
          records the entire recovery journey.
        </p>

        <div className="mt-12 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-4">
          {REASONS.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded border border-gold-dim/20 bg-surface/40 p-5 transition duration-200 hover:border-gold/40 hover:bg-surface/60"
            >
              <Icon
                className="mb-4 h-5 w-5 text-gold"
                strokeWidth={1.5}
              />

              <h3 className="font-display text-base text-parchment">
                {title}
              </h3>

              <p className="mt-2 text-xs leading-relaxed text-parchmentdim">
                {body}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-16 flex justify-center">
          <Link
            href="/command-center"
            className="group flex items-center gap-2 rounded-sm border border-gold/60 bg-surface px-8 py-4 text-sm font-semibold tracking-widest text-parchment shadow-goldline transition hover:bg-[#008080] hover:text-white hover:shadow-glow"
          >
            GET STARTED
            <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
          </Link>
        </div>
      </section>
    </main>
  );
}
