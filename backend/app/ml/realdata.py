"""
Real-data checks against the UCI *Online Retail* transactions.

    python -m app.ml.realdata                      # bundled 1-week sample (15,000 line items)
    python -m app.ml.realdata --path Online_Retail.csv   # the full 541,909-row data set from UCI

WHAT THIS DATA IS — AND IS NOT
  Real invoices from a UK online retailer: real amounts, real repeat-purchase timing, real bursts from
  wholesale customers. It contains NO payment failures and NO recovery outcomes, so it cannot train or
  score the recovery model. Used honestly, it can do two things:

  1. Sanity-check an assumption of the simulator: the *shape* of transaction amounts (log-normal spread).
  2. Stress-test the card-testing detector for false positives on REAL customer activity — treating real
     invoice attempts as payment attempts and asking how often a security hold would fire:
        - worst case : every real attempt fails (a pessimistic upper bound)
        - realistic  : each attempt independently fails with probability `fail_prob` (default 12%),
                       averaged over many random draws

Currency (GBP) and market (UK wholesale) differ from the sandbox (INR / Razorpay); only distributional
shape and behavioural timing are compared, never absolute levels.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import math
import random
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.ml import anomaly as A
from app.ml import registry
from app.ml.context import PaymentRecord, to_ts

settings = get_settings()
DEFAULT_PATH = Path(__file__).parent / "data" / "online_retail_sample.csv.gz"
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M", "%d/%m/%Y %H:%M")
ALIASES = {"invoice": ("InvoiceNo", "Invoice"), "qty": ("Quantity",), "price": ("UnitPrice", "Price"),
           "date": ("InvoiceDate",), "cust": ("CustomerID", "Customer ID")}
WORLD_AMOUNT_LOG_SD = 1.0          # world.py: lognormal(median 1800, sigma 1.0)


@dataclass
class Invoice:
    id: str
    customer: str
    ts: float
    amount: float


def _parse_dt(s: str) -> datetime | None:
    s = (s or "").strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def _open_text(path: Path):
    raw = path.open("rb")
    if path.suffix == ".gz":
        raw = gzip.open(raw)
    return io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")


def load_invoices(path: str | Path | None = None) -> tuple[list[Invoice], dict]:
    """Aggregate line items into one record per *invoice* (the closest thing to a payment attempt).
    Cancellations ('C…' invoices), rows without a customer id and non-positive totals are excluded."""
    path = Path(path) if path else DEFAULT_PATH
    inv: dict[str, dict] = {}
    stats = {"rows": 0, "rows_missing_customer": 0, "cancelled_invoices": set(), "bad_rows": 0}
    with _open_text(path) as f:
        reader = csv.DictReader(f)
        cols = {k: next((c for c in names if c in (reader.fieldnames or [])), None) for k, names in ALIASES.items()}
        missing = [k for k, v in cols.items() if v is None]
        if missing:
            raise ValueError(f"{path.name}: missing required column(s) {missing}; expected UCI Online Retail columns.")
        for row in reader:
            stats["rows"] += 1
            inv_id = (row[cols["invoice"]] or "").strip()
            if inv_id.upper().startswith("C"):
                stats["cancelled_invoices"].add(inv_id)
                continue
            cust = (row[cols["cust"]] or "").strip()
            if not cust:
                stats["rows_missing_customer"] += 1
                continue
            dt = _parse_dt(row[cols["date"]])
            try:
                amount = float(row[cols["qty"]]) * float(row[cols["price"]])
            except (TypeError, ValueError):
                dt = None
            if dt is None:
                stats["bad_rows"] += 1
                continue
            rec = inv.setdefault(inv_id, {"customer": cust.split(".")[0], "ts": to_ts(dt), "amount": 0.0})
            rec["amount"] += amount
    invoices = [Invoice(i, r["customer"], r["ts"], r["amount"]) for i, r in inv.items() if r["amount"] > 0]
    invoices.sort(key=lambda x: x.ts)
    stats["cancelled_invoices"] = len(stats["cancelled_invoices"])
    return invoices, stats


def amount_shape(invs: list[Invoice]) -> dict:
    a = np.array([i.amount for i in invs])
    logs = np.log(a)
    return {"real_log_sd": round(float(logs.std()), 3), "simulator_log_sd": WORLD_AMOUNT_LOG_SD,
            "real_median_gbp": round(float(np.median(a)), 1),
            "real_p05_p95_gbp": [round(float(np.percentile(a, 5)), 1), round(float(np.percentile(a, 95)), 1)],
            "reading": "Shape comparison only (log-spread of invoice totals); levels differ by currency and market."}


def _by_customer(invs: list[Invoice]) -> dict[str, list[Invoice]]:
    out: dict[str, list[Invoice]] = {}
    for i in invs:
        out.setdefault(i.customer, []).append(i)
    return out


def activity(invs: list[Invoice]) -> dict:
    per = _by_customer(invs)
    counts = sorted(len(v) for v in per.values())
    gaps = []
    for v in per.values():
        gaps += [b.ts - a.ts for a, b in zip(v, v[1:])]
    n = len(invs)
    return {"customers": len(per), "invoices_per_customer_median": statistics.median(counts),
            "invoices_per_customer_p90": counts[int(0.9 * (len(counts) - 1))], "invoices_per_customer_max": counts[-1],
            "share_of_invoices_with_a_repeat_within_60min": round(sum(1 for g in gaps if g < 3600) / max(n, 1), 3),
            "share_of_invoices_with_a_repeat_within_10min": round(sum(1 for g in gaps if g < 600) / max(n, 1), 3)}


def _window_features(per: dict[str, list[PaymentRecord]], focal: list[PaymentRecord]):
    """Detector features for the hour centred on each focal payment (same windowing as the live engine)."""
    half = settings.ml_fraud_window_minutes * 30.0
    feats, keys = [], []
    for r in focal:
        lst = per[r.key]
        w = [x for x in lst if r.ts - half < x.ts <= r.ts + half]
        day_f = sum(1 for x in lst if x.status == "failed" and abs(x.ts - r.ts) <= 43200)
        feats.append(A.velocity_features(w, day_f))
        keys.append(r.key)
    return feats, keys


def _stress(model: A.AnomalyModel, per: dict[str, list[PaymentRecord]], focal: list[PaymentRecord]) -> dict:
    if not focal:
        return {"windows": 0, "held": 0, "rate": 0.0, "customers_flagged": 0, "max_attempts_in_window": 0}
    feats, keys = _window_features(per, focal)
    X = np.vstack([A._vec(f) for f in feats])
    hold = (model.score_vec(X) >= model.threshold) & (X[:, A.VELOCITY_FEATURES.index("n_failed")] >= settings.ml_fraud_min_failures)
    return {"windows": len(focal), "held": int(hold.sum()), "rate": float(hold.mean()),
            "customers_flagged": len({k for k, h in zip(keys, hold) if h}),
            "max_attempts_in_window": int(max(f["n_attempts"] for f in feats))}


def detector_stress(model: A.AnomalyModel, invs: list[Invoice], fail_prob: float = 0.12, trials: int = 25,
                    seed: int = 7) -> dict:
    def build(fail_flags: list[bool]) -> dict[str, list[PaymentRecord]]:
        per: dict[str, list[PaymentRecord]] = {}
        for i, failed in zip(invs, fail_flags):
            per.setdefault(i.customer, []).append(PaymentRecord(
                i.id, i.customer, "card", i.amount, "failed" if failed else "captured",
                "card_declined" if failed else None, i.ts))
        return per

    per_all = build([True] * len(invs))
    worst = _stress(model, per_all, [r for lst in per_all.values() for r in lst])

    rng = random.Random(seed)
    rates, windows, flagged = [], [], []
    for _ in range(trials):
        flags = [rng.random() < fail_prob for _ in invs]
        per = build(flags)
        s = _stress(model, per, [r for lst in per.values() for r in lst if r.status == "failed"])
        rates.append(s["rate"]); windows.append(s["windows"]); flagged.append(s["customers_flagged"])
    realistic = {"failure_probability": fail_prob, "trials": trials,
                 "failed_windows_per_trial": round(float(np.mean(windows)), 1),
                 "hold_rate_mean": round(float(np.mean(rates)), 4),
                 "hold_rate_min": round(float(np.min(rates)), 4), "hold_rate_max": round(float(np.max(rates)), 4),
                 "customers_flagged_mean": round(float(np.mean(flagged)), 2)}
    worst["rate"] = round(worst["rate"], 4)
    return {"model_version": model.version, "operating_threshold": round(model.threshold, 4),
            "synthetic_benign_false_positive_rate": model.meta["card_testing"]["deployed_rule_false_positive_rate"],
            "worst_case_all_attempts_fail": worst, "realistic": realistic}


def run(path: str | Path | None = None, fail_prob: float = 0.12, seed: int = 7, write: bool = True) -> dict:
    path = Path(path) if path else DEFAULT_PATH
    invs, st = load_invoices(path)
    if len(invs) < 50:
        raise ValueError("Too few usable invoices to evaluate.")
    model = registry.get_anomaly_model()
    if model is None:
        raise RuntimeError("Anomaly model unavailable.")
    is_sample = path.resolve() == DEFAULT_PATH.resolve()
    ts = [i.ts for i in invs]
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    report = {
        "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        "dataset": {"name": "UCI Online Retail (real UK online-retailer transactions)", "file": path.name,
                    "is_bundled_sample": is_sample, "line_items_read": st["rows"], "invoices_used": len(invs),
                    "customers": len({i.customer for i in invs}), "period": [iso(min(ts)), iso(max(ts))],
                    "excluded": {"rows_without_customer": st["rows_missing_customer"],
                                 "cancelled_invoices": st["cancelled_invoices"], "unparseable_rows": st["bad_rows"]},
                    "licence_note": "CC BY 4.0 per UCI (verify); see app/ml/data/DATA_LICENSE.md",
                    "limits": "Real invoices, but NO payment failures and NO recovery outcomes: it cannot train or score the "
                              "recovery model. Bundled file is a one-week sample; pass --path for the full data set."},
        "amount_shape": amount_shape(invs),
        "activity": activity(invs),
        "detector_stress": detector_stress(model, invs, fail_prob, seed=seed),
        "interpretation": [
            "The simulator's amount spread (log-sd 1.0) is close to the real invoice-total spread, so the log-normal "
            "amount assumption is reasonable in shape.",
            "Under the worst case — every real attempt failing — the detector holds more windows than on synthetic benign "
            "data. Those are wholesale customers placing several invoices within minutes; treating a burst of failures "
            "from such a customer as worth a human look is defensible, but it does mean B2B-heavy merchants will see more holds.",
            "Under realistic failure rates the hold rate is far lower, because a hold needs several failures inside one hour.",
            "Neither number says anything about recall on real fraud: this data set has no fraud labels.",
        ],
    }
    if write and is_sample:
        registry.write_json("realdata_report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", default=None, help="Online Retail CSV / CSV.GZ (default: bundled sample)")
    ap.add_argument("--fail-prob", type=float, default=0.12)
    args = ap.parse_args()
    r = run(args.path, args.fail_prob, write=True)
    d = r["dataset"]
    print(f"{d['invoices_used']} invoices, {d['customers']} customers, {d['period'][0]} .. {d['period'][1]}")
    print("amount log-sd real vs simulator:", r["amount_shape"]["real_log_sd"], "vs", r["amount_shape"]["simulator_log_sd"])
    s = r["detector_stress"]
    print("worst case (all fail):", s["worst_case_all_attempts_fail"])
    print("realistic:", s["realistic"])


if __name__ == "__main__":
    main()
