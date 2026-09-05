import Link from "next/link";
import { Wand2, ShieldCheck, Sparkles, ArrowRight } from "lucide-react";
import Navbar from "@/components/Navbar";

export default function HomePage() {
  return (
    <main className="relative overflow-hidden">
      <Navbar />

      <section className="relative bg-grid">
        <div className="mx-auto grid max-w-7xl grid-cols-1 gap-16 px-6 pb-24 pt-20 md:grid-cols-2 md:pt-28">
          <div>
            <p className="mb-4 flex items-center gap-2 font-mono text-xs tracking-[0.25em] text-gold">
              <Wand2 className="h-3.5 w-3.5" /> AI OPERATIONS AGENT / 01
            </p>

            <h1 className="font-display text-5xl leading-[1.05] text-parchment md:text-6xl">
              Reparo <span className="glow-text text-gold-bright">AI.</span>
              <br />
              <span className="text-parchmentdim">Command your</span>
              <br />
              Razorpay operations.
            </h1>

            <p className="mt-6 max-w-lg text-base leading-relaxed text-parchmentdim">
              Connect your Razorpay environment, monitor transactions, and understand business
              activity through a unified operations dashboard — with an AI agent that answers
              real questions using your real data, never guesses.
            </p>

            <div className="mt-10 flex items-center gap-4">
              <Link
                href="/command-center"
                className="group flex items-center gap-2 rounded-sm border border-gold/60 bg-surface px-7 py-3.5 text-sm font-semibold tracking-widest text-parchment shadow-goldline transition hover:bg-[#008080] hover:text-white hover:shadow-glow"
              >
                GET STARTED
                <ArrowRight className="h-4 w-4 transition group-hover:translate-x-1" />
              </Link>

              <Link
                href="/system-design"
                className="rounded-sm border border-parchmentdim/20 px-7 py-3.5 text-sm tracking-widest text-parchmentdim transition hover:border-gold/40 hover:text-gold-bright"
              >
                EXPLORE THE SYSTEM
              </Link>
            </div>
          </div>

          <div className="relative">
            <div className="mist-particle absolute -left-6 top-10 h-2 w-2 rounded-full bg-gold-bright/60 blur-[1px]" />

            <div
              className="mist-particle absolute right-10 top-40 h-1.5 w-1.5 rounded-full bg-gold-bright/40 blur-[1px]"
              style={{ animationDelay: "2s" }}
            />

            <div className="glass-panel rounded-lg p-6 shadow-glow">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-[11px] tracking-[0.2em] text-parchmentdim">
                    COMMAND CENTER PREVIEW
                  </p>
                  <p className="font-display text-lg text-parchment">
                    Operations Overview
                  </p>
                </div>

                <span className="rounded-full border border-emerald/60 bg-emerald/20 px-3 py-1 text-[10px] tracking-widest text-emerald-200">
                  ● PREVIEW
                </span>
              </div>

              <div className="mb-5 grid grid-cols-2 gap-4">
                <div>
                  <p className="text-[11px] tracking-widest text-parchmentdim">
                    REVENUE RECOVERED
                  </p>
                  <p className="font-display text-2xl text-gold-bright">
                    ₹2,16,700
                  </p>
                  <p className="text-[11px] text-parchmentdim">
                    illustrative — sign in for live data
                  </p>
                </div>

                <div>
                  <p className="text-[11px] tracking-widest text-parchmentdim">
                    SUCCESS RATE
                  </p>
                  <p className="font-display text-2xl text-parchment">
                    78.4%
                  </p>
                  <p className="text-[11px] text-parchmentdim">
                    within safe bounds
                  </p>
                </div>
              </div>

              <div className="gold-divider mb-5" />

              <div className="flex items-center justify-between text-[11px] tracking-widest text-parchmentdim">
                <span>AI AGENT / ACTION QUEUE</span>
                <span className="text-gold-bright">04 pending</span>
              </div>

              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-charcoal">
                <div className="h-full w-2/3 rounded-full bg-gradient-to-r from-[#00697C] to-gold" />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="border-t border-gold-dim/15 bg-charcoal/60">
        <div className="mx-auto grid max-w-7xl grid-cols-1 gap-10 px-6 py-16 md:grid-cols-3">
          {[
            {
              icon: ShieldCheck,
              title: "Live + Test environments",
              body: "Connect a real Razorpay account, or explore the entire product first in a stateful simulated sandbox — same dashboard, same agent, different data source.",
            },
            {
              icon: Sparkles,
              title: "An agent, not a chatbot",
              body: "Reparo's agent calls real tools against your connected environment — payments, orders, refunds, revenue — and never fabricates a number.",
            },
            {
              icon: Wand2,
              title: "Secure by architecture",
              body: "Your Razorpay Key Secret never touches the browser. All Razorpay API calls are made server-side, credentials encrypted at rest.",
            },
          ].map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="rounded border border-gold-dim/20 bg-surface/40 p-6"
            >
              <Icon
                className="mb-4 h-5 w-5 text-gold"
                strokeWidth={1.5}
              />

              <h3 className="font-display text-lg text-parchment">
                {title}
              </h3>

              <p className="mt-2 text-sm leading-relaxed text-parchmentdim">
                {body}
              </p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-gold-dim/15 px-6 py-10 text-center text-xs tracking-widest text-parchmentdim">
        REPARO AI — AN OPERATIONS AGENT FOR RAZORPAY
      </footer>
    </main>
  );
}
