"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";

export default function Navbar() {
  return (
    <header className="sticky top-0 z-40 border-b border-gold-dim/20 bg-obsidian/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <Link href="/" className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-gold" strokeWidth={1.5} />
          <span className="font-display text-xl tracking-wide text-parchment">Reparo AI</span>
        </Link>

        <nav className="hidden items-center gap-10 text-sm tracking-widest text-parchmentdim md:flex">
          <Link href="/" className="transition hover:text-gold-bright">
            HOME
          </Link>
          <Link href="/system-design" className="transition hover:text-gold-bright">
            SYSTEM DESIGN
          </Link>
          <Link href="/why-to-use" className="transition hover:text-gold-bright">
            WHY TO USE
          </Link>
        </nav>

        <Link
          href="/command-center"
          className="rounded-sm border border-gold/50 bg-burgundy px-5 py-2.5 text-xs font-semibold tracking-widest text-parchment shadow-goldline transition hover:bg-burgundy-light hover:shadow-glow"
        >
          GET STARTED
        </Link>
      </div>
    </header>
  );
}
