"""
Anomaly detection for the recovery pipeline — two detectors, two different actions.

1. CARD TESTING / VELOCITY (per customer): fraudsters validate stolen card
   numbers with bursts of small, mostly-failing payments. Retrying them or
   emailing the "customer" would be actively harmful, so such cases are put
   on a SECURITY HOLD instead of being recovered.
     Model: Isolation Forest trained (unsupervised) on benign per-customer
     one-hour windows, with deliberately hard negatives (persistent honest
     retriers, B2B bulk payers). Threshold = 99.5th percentile of benign scores
     (~0.5% false-positive rate by construction). A deterministic minimum-
     evidence guard (>= N failures in the window) means a single odd payment
     can never trigger a hold. Each alert lists the features that deviate most.

2. METHOD OUTAGE (per payment method): a sudden spike in failures,
   dominated by technical errors, across many customers means the gateway /
   a bank is down. Retrying into an outage burns the bounded retry budget for
   nothing, so affected retries are DEFERRED until the spike clears.
     Model: one-sided binomial z-test of the last-hour failure rate against
     the method's own trailing baseline (interpretable, no training needed).

`AnomalyModel.train_and_save()` writes artifacts/anomaly_model.joblib and
anomaly_card.json (benign/attack AUC, recall at the operating threshold, FPR,
outage-detection recall / delay / false alarms on a labelled synthetic stream).
Like the risk model, evaluation data is synthetic and says so.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timezone

import joblib
import numpy as np
import sklearn
from scipy.stats import binom
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score

from app.config import get_settings
from app.ml import registry
from app.ml.context import PaymentRecord, ScanContext
from app.recovery import rules

settings = get_settings()

VELOCITY_FEATURES = ["n_attempts", "n_failed", "fail_ratio", "n_reasons", "n_methods", "log_median_amount",
                     "amount_cv", "log_min_gap_s", "n_failed_24h"]
FEATURE_TEXT = {
    "n_attempts": "payment attempts in the last hour", "n_failed": "failed attempts in the last hour",
    "fail_ratio": "share of attempts that failed", "n_reasons": "distinct failure reasons",
    "n_methods": "distinct payment methods", "log_median_amount": "typical amount (log ₹)",
    "amount_cv": "amount variation", "log_min_gap_s": "shortest gap between attempts (log s)",
    "n_failed_24h": "failed attempts in 24h",
}


# ---------------------------------------------------------------------------
# Velocity features
# ---------------------------------------------------------------------------
def velocity_features(window: list[PaymentRecord], day_failures: int, window_s: float = 3600.0) -> dict[str, float]:
    n = len(window)
    failed = [r for r in window if r.status == "failed"]
    amounts = np.array([max(r.amount, 1.0) for r in window]) if n else np.array([1.0])
    ts = sorted(r.ts for r in window)
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    min_gap = min(gaps) if gaps else window_s
    return {
        "n_attempts": float(n), "n_failed": float(len(failed)), "fail_ratio": len(failed) / n if n else 0.0,
        "n_reasons": float(len({(r.reason or "unknown") for r in failed})),
        "n_methods": float(len({r.method for r in window if r.method})),
        "log_median_amount": float(math.log(np.median(amounts))),
        "amount_cv": float(np.std(amounts) / (np.mean(amounts) + 1e-9)),
        "log_min_gap_s": float(math.log(max(min_gap, 1.0))), "n_failed_24h": float(max(day_failures, len(failed))),
    }


def _vec(f: dict[str, float]) -> np.ndarray:
    return np.array([f[k] for k in VELOCITY_FEATURES], dtype=np.float64)


# ---------------------------------------------------------------------------
# Synthetic customer windows (benign + attack) — same record type as production
# ---------------------------------------------------------------------------
_REASONS = ["insufficient_funds", "card_declined", "otp_timeout", "issuer_unavailable", "risk_check_failed",
            "do_not_honor", "expired_card"]
_T_REF = 1_800_000_000.0


def _rec(i, t, amt, status, reason, method):
    return PaymentRecord(id=f"s{i}", key="c", method=method, amount=amt, status=status, reason=reason, ts=t)


def synth_window(kind: str, rng: random.Random) -> tuple[list[PaymentRecord], int]:
    """Returns (records in the last hour ending at the failing payment, failures in 24h)."""
    recs: list[PaymentRecord] = []
    method = rng.choice(["card", "upi", "netbanking", "wallet"])
    if kind == "benign":
        mode = rng.random()
        base_amt = math.exp(rng.gauss(math.log(1800), 1.0))
        if mode < 0.80:                                   # ordinary: the one failed payment (+ maybe a related attempt)
            n_extra = 0 if rng.random() < 0.7 else rng.randint(1, 2)
            times = sorted(_T_REF - rng.uniform(60, 3400) for _ in range(n_extra)) + [_T_REF]
            for i, t in enumerate(times):
                last = i == len(times) - 1
                recs.append(_rec(i, t, base_amt * (1 if rng.random() < .6 else rng.uniform(.5, 2)),
                                 "failed" if last or rng.random() < .35 else "captured", rng.choice(_REASONS), method))
            day_f = 1 + int(rng.random() < .25) * rng.randint(0, 2)
        elif mode < 0.93:                                 # persistent honest retrier: same amount, few quick retries
            n = rng.randint(2, 4)
            times = sorted(_T_REF - rng.uniform(0, 900) for _ in range(n - 1)) + [_T_REF]
            reason = rng.choice(_REASONS)
            for i, t in enumerate(times):
                recs.append(_rec(i, t, base_amt, "failed" if rng.random() < .8 or i == n - 1 else "captured", reason, method))
            day_f = n + rng.randint(0, 2)
        else:                                             # B2B / bulk payer: many payments, mostly succeeding
            n = rng.randint(4, 14)
            times = sorted(_T_REF - rng.uniform(0, 3500) for _ in range(n - 1)) + [_T_REF]
            for i, t in enumerate(times):
                recs.append(_rec(i, t, math.exp(rng.gauss(math.log(25000), 0.8)),
                                 "failed" if i == n - 1 or rng.random() < .08 else "captured",
                                 rng.choice(_REASONS), rng.choice(["card", "netbanking", "upi"])))
            day_f = sum(r.status == "failed" for r in recs) + rng.randint(0, 3)
    else:                                                 # card testing burst
        n = rng.randint(6, 40)
        dur = rng.uniform(40, 900)
        times = sorted(_T_REF - rng.uniform(0, dur) for _ in range(n - 1)) + [_T_REF]
        small = math.exp(rng.uniform(math.log(2), math.log(250)))
        reasons = rng.sample(_REASONS, rng.randint(1, 4))
        for i, t in enumerate(times):
            recs.append(_rec(i, t, small * rng.uniform(.5, 2.5), "failed" if i == n - 1 or rng.random() < .88 else "captured",
                             rng.choice(reasons), rng.choice(["card", "card", "card", "wallet"])))
        day_f = sum(r.status == "failed" for r in recs) + rng.randint(0, 25)
    return recs, day_f


def _dataset(kind: str, n: int, seed: int) -> np.ndarray:
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        recs, day_f = synth_window(kind, rng)
        rows.append(_vec(velocity_features(recs, day_f)))
    return np.vstack(rows)


def signature_rule(f: dict[str, float]) -> bool:
    """Hand-written card-testing signature, used as a comparison baseline and
    as a fallback if the model artifact is unavailable."""
    return f["n_failed"] >= 5 and f["fail_ratio"] >= 0.7 and math.exp(f["log_median_amount"]) < 300


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
@dataclass
class FraudAssessment:
    hold: bool
    score: float
    threshold: float
    features: dict
    reasons: list[str]
    source: str                 # "isolation_forest" | "signature_rule"


class AnomalyModel:
    def __init__(self, forest: IsolationForest, threshold: float, mu: np.ndarray, sd: np.ndarray, meta: dict):
        self.forest, self.threshold, self.mu, self.sd, self.meta = forest, threshold, mu, sd, meta

    def score_vec(self, X: np.ndarray) -> np.ndarray:
        return -self.forest.score_samples(X)          # higher = more anomalous

    def assess(self, window: list[PaymentRecord], day_failures: int,
               min_failures: int | None = None) -> FraudAssessment:
        min_failures = settings.ml_fraud_min_failures if min_failures is None else min_failures
        f = velocity_features(window, day_failures)
        x = _vec(f)
        s = float(self.score_vec(x.reshape(1, -1))[0])
        z = (x - self.mu) / self.sd
        top = np.argsort(-np.abs(z))[:3]
        reasons = [f"{FEATURE_TEXT[VELOCITY_FEATURES[i]]}: {_fmt(VELOCITY_FEATURES[i], x[i])} "
                   f"(typical {_fmt(VELOCITY_FEATURES[i], self.mu[i])})" for i in top if abs(z[i]) >= 1.5]
        hold = s >= self.threshold and f["n_failed"] >= min_failures
        return FraudAssessment(hold, s, self.threshold, f, reasons, "isolation_forest")

    @property
    def version(self) -> str:
        return self.meta["version"]

    def save(self, path):
        joblib.dump({"forest": self.forest, "threshold": self.threshold, "mu": self.mu, "sd": self.sd,
                     "meta": self.meta}, path)

    @classmethod
    def load(cls, path) -> "AnomalyModel":
        b = joblib.load(path)
        registry.check_sklearn_version(b["meta"])
        if b["meta"].get("features") != VELOCITY_FEATURES:
            raise RuntimeError("Velocity feature schema changed; retrain required.")
        return cls(b["forest"], b["threshold"], b["mu"], b["sd"], b["meta"])

    @classmethod
    def train_and_save(cls, seed: int = 7, quiet: bool = True) -> "AnomalyModel":
        Xb = _dataset("benign", 9000, seed)
        Xtr, Xte_b = Xb[:6000], Xb[6000:]
        Xte_a = _dataset("attack", 800, seed + 1)
        forest = IsolationForest(n_estimators=300, max_samples=512, contamination="auto", random_state=seed).fit(Xtr)
        m = cls(forest, 0.0, Xtr.mean(axis=0), Xtr.std(axis=0) + 1e-6, {})
        thr = float(np.percentile(m.score_vec(Xtr), 99.5))
        m.threshold = thr
        sb, sa = m.score_vec(Xte_b), m.score_vec(Xte_a)
        y = np.r_[np.zeros(len(sb)), np.ones(len(sa))]
        auc = float(roc_auc_score(y, np.r_[sb, sa]))

        def guard(X):   # the deployed decision: IF threshold AND minimum evidence
            return (m.score_vec(X) >= thr) & (X[:, VELOCITY_FEATURES.index("n_failed")] >= settings.ml_fraud_min_failures)
        feat = lambda X: [dict(zip(VELOCITY_FEATURES, r)) for r in X]
        sig_b = np.mean([signature_rule(f) for f in feat(Xte_b)])
        sig_a = np.mean([signature_rule(f) for f in feat(Xte_a)])
        card = {
            "version": "anomaly-iforest-" + datetime.now(timezone.utc).strftime("%Y%m%d"),
            "trained_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
            "features": VELOCITY_FEATURES, "sklearn_version": sklearn.__version__,
            "data_provenance": "Synthetic benign + card-testing windows (app/ml/anomaly.py). Benign set includes hard "
                               "negatives: persistent honest retriers and B2B bulk payers. Unsupervised: attacks are "
                               "never used for training, only for evaluation.",
            "operating_threshold": round(thr, 4),
            "card_testing": {
                "auc_benign_vs_attack": round(auc, 4),
                "deployed_rule_recall": round(float(guard(Xte_a).mean()), 4),
                "deployed_rule_false_positive_rate": round(float(guard(Xte_b).mean()), 4),
                "signature_rule_recall": round(float(sig_a), 4),
                "signature_rule_false_positive_rate": round(float(sig_b), 4),
                "benign_test_windows": int(len(sb)), "attack_test_windows": int(len(sa)),
            },
            "outage_detection": evaluate_outage_detector(seed=seed),
        }
        m.meta = card
        m.save(registry.path("anomaly_model.joblib"))
        registry.record("anomaly_model.joblib")
        registry.write_json("anomaly_card.json", card)
        if not quiet:
            print(card["card_testing"], card["outage_detection"])
        return m


def _fmt(name: str, v: float) -> str:
    if name == "log_median_amount":
        return f"₹{math.exp(v):,.0f}"
    if name == "log_min_gap_s":
        return f"{math.exp(v):.0f}s"
    if name in ("fail_ratio",):
        return f"{v * 100:.0f}%"
    if name == "amount_cv":
        return f"{v:.2f}"
    return f"{v:.0f}"


# ---------------------------------------------------------------------------
# Outage detection (binomial z-test vs the method's own baseline)
# ---------------------------------------------------------------------------
@dataclass
class OutageSignal:
    method: str
    attempts: int
    failures: int
    rate: float
    baseline_rate: float
    z: float
    technical_share: float


COUNT_WINDOW = 8             # last-K-attempts window: reacts within minutes on busy methods
COUNT_WINDOW_MAX_SPAN_S = 7200.0


def _is_outage(n: int, f: int, tech: float, p0: float, alpha: float) -> tuple[bool, float, float]:
    """Exact one-sided binomial test: P(>= f failures out of n | baseline rate p0) <= alpha.
    alpha is tiny on purpose — the detector is evaluated ~96x/day on several methods, so a
    loose threshold would fire constantly (multiple-comparison problem). Also requires a
    material effect size (>= 2x baseline and >= 35%) and infrastructure-dominated failures."""
    rate = f / n
    pval = float(binom.sf(f - 1, n, p0)) if f > 0 else 1.0
    z = (rate - p0) / math.sqrt(p0 * (1 - p0) / n)
    return (pval <= alpha and rate >= max(2 * p0, 0.35) and tech >= 0.4), rate, z


def detect_outages(ctx: ScanContext, now_ts: float, window_min: int | None = None, baseline_days: int | None = None,
                   min_attempts: int | None = None, alpha: float | None = None) -> list[OutageSignal]:
    """Two complementary one-sided binomial tests per method against the method's
    own trailing baseline: (a) the last `window_min` minutes (needs >= min_attempts
    payments) and (b) the last K attempts if they all fall within two hours
    (reacts faster on busy methods). A method is flagged when either fires AND
    the failures are dominated by technical errors — which is what separates an
    outage from, say, a card-testing burst of ordinary declines."""
    window_s = 60.0 * (window_min or settings.ml_outage_window_minutes)
    base_s = 86400.0 * (baseline_days or settings.ml_outage_baseline_days)
    min_n = min_attempts or settings.ml_outage_min_attempts
    alpha = alpha or settings.ml_outage_alpha
    out = []
    for method, s in ctx.series.items():
        hi_all = int(np.searchsorted(s.ts, now_ts, side="right"))
        best: OutageSignal | None = None

        def baseline(t_hi: float) -> float:
            lo = int(np.searchsorted(s.ts, now_ts - base_s, side="right"))
            hi = int(np.searchsorted(s.ts, t_hi, side="right"))
            n0, f0 = max(hi - lo, 0), int(s.failed[lo:hi].sum()) if hi > lo else 0
            return max((f0 + 1.0) / (n0 + 5.0), 0.03)      # smoothed, floored baseline failure rate

        # (a) time window
        lo = int(np.searchsorted(s.ts, now_ts - window_s, side="right"))
        n, f = hi_all - lo, int(s.failed[lo:hi_all].sum())
        if n >= min_n:
            p0 = baseline(now_ts - window_s)
            tech = float(s.technical[lo:hi_all].sum() / max(f, 1))
            ok, rate, z = _is_outage(n, f, tech, p0, alpha)
            if ok:
                best = OutageSignal(method, n, f, round(rate, 3), round(p0, 3), round(z, 2), round(tech, 2))
        # (b) last-K-attempts window (must be recent: all K within two hours)
        if hi_all >= COUNT_WINDOW:
            lo_k = hi_all - COUNT_WINDOW
            if now_ts - s.ts[lo_k] <= COUNT_WINDOW_MAX_SPAN_S:
                f = int(s.failed[lo_k:hi_all].sum())
                p0 = baseline(now_ts - COUNT_WINDOW_MAX_SPAN_S)
                tech = float(s.technical[lo_k:hi_all].sum() / max(f, 1))
                ok, rate, z = _is_outage(COUNT_WINDOW, f, tech, p0, alpha)
                if ok and (best is None or z > best.z):
                    best = OutageSignal(method, COUNT_WINDOW, f, round(rate, 3), round(p0, 3), round(z, 2), round(tech, 2))
        if best:
            out.append(best)
    return out


def evaluate_outage_detector(seed: int = 7, days: int = 30, n_outages: int = 10, n_seeds: int = 5) -> dict:
    """Pooled evaluation over `n_seeds` independent synthetic 30-day streams."""
    runs = [_evaluate_outage_once(seed + 100 * i, days, n_outages) for i in range(n_seeds)]
    by_method = {}
    for m in ("card", "upi", "netbanking"):
        by_method[m] = {"outages": sum(r["by_method"][m]["outages"] for r in runs),
                        "detected": sum(r["by_method"][m]["detected"] for r in runs),
                        "avg_payments_per_hour": runs[0]["by_method"][m]["avg_payments_per_hour"]}
    total = sum(v["outages"] for v in by_method.values())
    det = sum(v["detected"] for v in by_method.values())
    delays = [r["median_detection_delay_min"] for r in runs if r["median_detection_delay_min"] is not None]
    fa = sum(r["false_alarm_episodes"] for r in runs)
    return {
        "stream": f"{n_seeds} independent {days}-day streams, ~{runs[0]['payments']} payments each, "
                  f"{n_outages} injected outages per stream (60-240 min, 80-95% failures)",
        "outages_detected": f"{det}/{total}", "recall": round(det / total, 3), "by_method": by_method,
        "median_detection_delay_min": round(float(np.median(delays)), 1) if delays else None,
        "false_alarm_episodes_per_month": round(fa / (n_seeds * days) * 30, 3),
        "note": "Scanned every 15 minutes with an exact binomial test (alpha=1e-4). Recall is limited by payment volume: "
                "quiet hours and low-volume methods (netbanking, wallet) cannot accumulate enough attempts for a "
                "statistically sound test, so the detector stays silent rather than guess.",
    }


def _evaluate_outage_once(seed: int, days: int, n_outages: int) -> dict:
    """Run the detector every 15 minutes over a labelled synthetic stream with
    injected outages and report recall, detection delay, and false alarms."""
    rng = np.random.default_rng(seed)
    vol = {"card": 16, "upi": 12, "netbanking": 5, "wallet": 2}           # payments / hour (average)
    base_fail = {"card": .10, "upi": .12, "netbanking": .15, "wallet": .08}
    diurnal = np.array([.3, .2, .15, .15, .2, .4, .7, 1.0, 1.3, 1.5, 1.6, 1.7, 1.7, 1.6, 1.5, 1.5, 1.6, 1.8, 2.0, 2.1, 2.0, 1.7, 1.1, .6])
    diurnal = diurnal / diurnal.mean()
    minutes = days * 1440
    outages = []
    methods = ["card", "upi", "netbanking"]
    while len(outages) < n_outages:
        m = methods[int(rng.integers(0, len(methods)))]
        start = int(rng.integers(2 * 1440, minutes - 600))
        dur = int(rng.integers(60, 241))
        if all(abs(start - o["start"]) > 600 for o in outages):
            outages.append({"method": m, "start": start, "end": start + dur})
    items = []
    base_ts = 1_700_000_000.0
    k = 0
    for m in vol:
        lam = np.array([vol[m] * diurnal[(i // 60) % 24] / 60.0 for i in range(minutes)])
        counts = rng.poisson(lam)
        for minute in np.nonzero(counts)[0]:
            for _ in range(counts[minute]):
                in_out = any(o["method"] == m and o["start"] <= minute < o["end"] for o in outages)
                p_fail = rng.uniform(.8, .95) if in_out else base_fail[m]
                failed = rng.random() < p_fail
                reason = (rng.choice(["gateway_timeout", "issuer_unavailable", "bank_timeout"]) if in_out and rng.random() < .8
                          else rng.choice(_REASONS)) if failed else None
                k += 1
                items.append({"id": f"p{k}", "email": f"u{int(rng.integers(0, 4000))}@x.io", "method": m,
                              "amount": 1000.0, "status": "failed" if failed else "captured", "failure_reason": reason,
                              "created_at": datetime.fromtimestamp(base_ts + minute * 60 + rng.uniform(0, 60), timezone.utc)
                              .replace(tzinfo=None).isoformat()})
    ctx = ScanContext(items, now=datetime.fromtimestamp(base_ts + minutes * 60, timezone.utc).replace(tzinfo=None))
    detected = {i: None for i in range(len(outages))}
    false_alarm_scans = 0
    last_false: dict[str, int] = {}
    false_episodes = 0
    for minute in range(3 * 1440, minutes, 15):
        sigs = detect_outages(ctx, base_ts + minute * 60)
        for s_ in sigs:
            hit = False
            for i, o in enumerate(outages):
                if o["method"] == s_.method and o["start"] <= minute <= o["end"] + 60:
                    hit = True
                    if detected[i] is None:
                        detected[i] = minute - o["start"]
            if not hit:
                false_alarm_scans += 1
                if minute - last_false.get(s_.method, -10_000) > 60:
                    false_episodes += 1
                last_false[s_.method] = minute
    delays = [d for d in detected.values() if d is not None]
    scans = len(range(3 * 1440, minutes, 15))
    by_method = {}
    for m in ("card", "upi", "netbanking"):
        idx = [i for i, o in enumerate(outages) if o["method"] == m]
        by_method[m] = {"outages": len(idx), "detected": sum(detected[i] is not None for i in idx),
                        "avg_payments_per_hour": vol[m]}
    return {
        "stream": f"{days} days, {len(items)} payments, {n_outages} injected outages (60-240 min, 80-95% failures)",
        "by_method": by_method,
        "false_alarm_episodes": int(false_episodes),
        "false_alarm_episodes_per_week": round(false_episodes / days * 7, 3),
        "outages_detected": f"{len(delays)}/{n_outages}",
        "recall": round(len(delays) / n_outages, 3),
        "median_detection_delay_min": round(float(np.median(delays)), 1) if delays else None,
        "false_alarm_scans": int(false_alarm_scans),
        "payments": len(items),
    }
