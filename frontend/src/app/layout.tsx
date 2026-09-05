import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Reparo AI — Razorpay Operations Command Center",
  description: "Your intelligent Razorpay operations command center.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
