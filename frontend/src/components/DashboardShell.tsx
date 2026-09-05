"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  BarChart3,
  CreditCard,
  Package,
  Undo2,
  Users,
  Bot,
  Settings,
  Sparkles,
  LogOut,
  Zap,
  FlaskConical,
  Landmark,
  Gavel,
} from "lucide-react";
import { setToken, setEnvironment } from "@/lib/api";
import { useAuthGuard } from "@/lib/useAuthGuard";

const NAV = [
  { href: "/dashboard", label: "Recovery Console", icon: LayoutDashboard },
  { href: "/dashboard/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/dashboard/payments", label: "Payments", icon: CreditCard },
  { href: "/dashboard/orders", label: "Orders", icon: Package },
  { href: "/dashboard/refunds", label: "Refunds", icon: Undo2 },
  { href: "/dashboard/settlements", label: "Settlements", icon: Landmark },
  { href: "/dashboard/disputes", label: "Disputes", icon: Gavel },
  { href: "/dashboard/customers", label: "Customers", icon: Users },
  { href: "/dashboard/agent", label: "AI Agent", icon: Bot },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

export default function DashboardShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { ready, environment, email } = useAuthGuard();

  function logout() {
    setToken(null);
    setEnvironment(null);
    router.push("/command-center");
  }

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-obsidian text-parchmentdim">
        <span className="text-sm tracking-widest">LOADING COMMAND CENTER…</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-obsidian">
      <div className="flex">
          <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-gold-dim/15 bg-charcoal md:flex">
          <Link href="/" className="flex items-center gap-2 px-6 py-6">
            <Sparkles className="h-5 w-5 text-gold" strokeWidth={1.5} />
            <span className="font-display text-lg text-parchment">Reparo AI</span>
          </Link>

          <nav className="flex-1 space-y-1 px-3">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  className={`flex items-center gap-3 rounded-sm px-3 py-2.5 text-sm transition ${
                    active
                      ? "border border-gold/40 bg-burgundy/40 text-gold-bright"
                      : "text-parchmentdim hover:bg-surface/60 hover:text-parchment"
                  }`}
                >
                  <Icon className="h-4 w-4" strokeWidth={1.5} />
                  {label}
                </Link>
              );
            })}
          </nav>

          <div className="border-t border-gold-dim/15 px-6 py-5">
            <p className="truncate text-xs text-parchmentdim">{email}</p>
            <button
              onClick={logout}
              className="mt-2 flex items-center gap-2 text-xs tracking-widest text-parchmentdim hover:text-gold-bright"
            >
              <LogOut className="h-3.5 w-3.5" /> SIGN OUT
            </button>
          </div>
        </aside>

          <div className="min-w-0 flex-1">
          <div className="sticky top-0 z-30 flex items-center justify-between border-b border-gold-dim/15 bg-obsidian/90 px-6 py-4 backdrop-blur-md">
            <p className="font-display text-lg text-parchment">
              {NAV.find((n) => n.href === pathname)?.label || "Dashboard"}
            </p>
            <EnvironmentBadge environment={environment} />
          </div>
          <div className="p-6">{children}</div>
        </div>
      </div>
    </div>
  );
}

export function EnvironmentBadge({ environment }: { environment: string | null }) {
  if (environment === "live") {
    return (
      <span className="flex items-center gap-1.5 rounded-full border border-gold/50 bg-burgundy/40 px-3 py-1.5 text-[11px] font-semibold tracking-widest text-gold-bright">
        <Zap className="h-3 w-3" /> LIVE — RAZORPAY CLIENT
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-emerald/50 bg-emerald/20 px-3 py-1.5 text-[11px] font-semibold tracking-widest text-emerald-200">
      <FlaskConical className="h-3 w-3" /> TEST MODE
    </span>
  );
}
