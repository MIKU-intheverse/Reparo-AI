"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, Loader2, Wrench } from "lucide-react";
import DashboardShell from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";

type Msg = { role: "user" | "assistant"; content: string; trace?: any[] };

const SUGGESTIONS = [
  "Show me today's failed payments",
  "What was my revenue this week?",
  "List recent refunds",
  "Summarize payment activity",
];

export default function AgentPage() {
  const [messages, setMessages] = useState<Msg[]>([
    { role: "assistant", content: "I'm the Reparo AI operations agent. Ask me about payments, orders, refunds, customers, or revenue — I'll pull real data from your active environment." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(text: string) {
    if (!text.trim() || loading) return;
    setError(null);
    const next: Msg[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const history = next
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(0, -1)
        .map((m) => ({ role: m.role, content: m.content }));
      const res = await api.agentChat(text, history);
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply, trace: res.tool_trace }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The agent couldn't complete that request.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <DashboardShell>
      <div className="flex h-[calc(100vh-160px)] flex-col rounded-lg border border-gold-dim/20 bg-surface/30">
        <div className="flex-1 space-y-5 overflow-y-auto p-6">
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              {m.role === "assistant" && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-burgundy/30">
                  <Bot className="h-4 w-4 text-gold-bright" />
                </div>
              )}
              <div className={`max-w-xl rounded-lg px-4 py-3 text-sm leading-relaxed ${m.role === "user" ? "bg-burgundy/50 text-parchment" : "border border-gold-dim/20 bg-charcoal text-parchment"}`}>
                <p className="whitespace-pre-line">{m.content}</p>
                {m.trace && m.trace.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5 border-t border-gold-dim/15 pt-2">
                    {m.trace.map((t, ti) => (
                      <span key={ti} className="flex items-center gap-1 rounded-full border border-gold-dim/30 px-2 py-0.5 text-[10px] text-parchmentdim">
                        <Wrench className="h-2.5 w-2.5" /> {t.tool}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {m.role === "user" && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-gold-dim/30 bg-charcoal">
                  <User className="h-4 w-4 text-parchmentdim" />
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-xs text-parchmentdim">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-gold" /> Reparo is checking your data…
            </div>
          )}
          {error && <p className="text-xs text-gold-bright">{error}</p>}
          <div ref={endRef} />
        </div>

        <div className="border-t border-gold-dim/15 p-4">
          <div className="mb-3 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="rounded-full border border-gold-dim/30 px-3 py-1.5 text-[11px] text-parchmentdim transition hover:border-gold/50 hover:text-gold-bright"
              >
                {s}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="flex gap-3"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about payments, revenue, refunds…"
              className="flex-1 rounded-sm border border-gold-dim/30 bg-charcoal px-4 py-3 text-sm text-parchment outline-none focus:border-gold"
            />
            <button
              type="submit"
              disabled={loading}
              className="flex items-center gap-2 rounded-sm border border-gold/50 bg-burgundy px-5 py-3 text-sm font-semibold text-parchment transition hover:bg-burgundy-light disabled:opacity-60"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      </div>
    </DashboardShell>
  );
}
