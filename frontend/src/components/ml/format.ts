export const TEAL = "#5fd0d0";
export const TEAL_DARK = "#00697C";
export const GOLD = "#c9a05a";
export const DIM = "#cfc3a9";
export const RED = "#c0504d";
export const GREEN = "#3fbf9f";

export function fmtHours(h: number | null | undefined): string {
  if (h === null || h === undefined || Number.isNaN(h)) return "—";
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h >= 48) return `${(h / 24).toFixed(h % 24 === 0 ? 0 : 1)}d`;
  return `${Number.isInteger(h) ? h : h.toFixed(1)}h`;
}

export const pct = (x: number | null | undefined, d = 0) =>
  x === null || x === undefined ? "—" : `${(x * 100).toFixed(d)}%`;

export const inr = (x: number | null | undefined, d = 0) =>
  x === null || x === undefined ? "—" : `₹${x.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d })}`;

export const signed = (x: number, d = 0) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}`;

export const POLICY_LABEL: Record<string, string> = {
  do_nothing: "Do nothing",
  naive_retry: "Naive retry",
  rules: "Rules (before ML)",
  ml_risk: "Rules + risk model",
  ml_full: "Rules + risk model + learned timing",
};
export const POLICY_COLOR: Record<string, string> = {
  do_nothing: "#6b7b80",
  naive_retry: "#9a8a6a",
  rules: GOLD,
  ml_risk: "#3fa7b8",
  ml_full: TEAL,
};
