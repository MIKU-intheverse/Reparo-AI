"""
The ONE feature schema used everywhere: offline training data, offline
evaluation, and live scoring inside the recovery engine. Having a single
builder removes the classic train/serve-skew bug (tested in
tests/test_features.py).

All features are available at decision time — nothing here leaks the outcome.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

REASON_VOCAB = ["insufficient_funds", "card_declined", "otp_timeout", "issuer_unavailable", "risk_check_failed",
                "bank_timeout", "gateway_timeout", "expired_card", "unknown"]
METHOD_VOCAB = ["card", "upi", "netbanking", "wallet", "other"]
NUMERIC = ["log_amount", "retry_count", "comms_sent", "age_hours", "hour_sin", "hour_cos",
           "salary_window", "weekend", "cust_log_n", "cust_success_rate"]

FEATURE_COLUMNS = ([f"reason={r}" for r in REASON_VOCAB] + [f"method={m}" for m in METHOD_VOCAB] + NUMERIC)
N_FEATURES = len(FEATURE_COLUMNS)
_IDX = {c: i for i, c in enumerate(FEATURE_COLUMNS)}

# Human-readable feature groups, used for explanations and grouped importance.
GROUPS: dict[str, list[str]] = {
    "Failure reason": [f"reason={r}" for r in REASON_VOCAB],
    "Payment method": [f"method={m}" for m in METHOD_VOCAB],
    "Amount": ["log_amount"],
    "Attempt history": ["retry_count", "comms_sent"],
    "Time since failure": ["age_hours"],
    "Time of day": ["hour_sin", "hour_cos"],
    "Salary window / weekend": ["salary_window", "weekend"],
    "Customer history": ["cust_log_n", "cust_success_rate"],
}
GROUP_INDICES = {g: [_IDX[c] for c in cols] for g, cols in GROUPS.items()}

# Domain-knowledge monotonic constraints for the gradient-boosted model:
# higher amount / more prior failures can only lower recovery odds; a better
# customer track record can only raise them.
MONOTONIC = {"log_amount": -1, "retry_count": -1, "cust_success_rate": 1}
MAX_AGE_HOURS = 168.0


def smooth_rate(captured: int, n: int, prior_mean: float = 0.8, prior_strength: float = 4.0) -> float:
    """Empirical-Bayes success rate, so a customer with 1 payment isn't scored 0% or 100%."""
    return (captured + prior_mean * prior_strength) / (n + prior_strength)


def normalize_reason(reason: str | None) -> str:
    if not reason:
        return "unknown"
    r = reason.lower().strip().replace(" ", "_")
    return r if r in REASON_VOCAB else "unknown"


def normalize_method(method: str | None) -> str:
    return method if method in METHOD_VOCAB else "other"


@dataclass
class FeatureInput:
    reason: str | None
    method: str | None
    amount: float
    retry_count: int
    comms_sent: int
    age_hours: float
    local_hour_frac: float        # 0 <= h < 24 (local time of the decision)
    day_of_month: int
    weekday: int                  # Mon=0 ... Sun=6
    cust_n: int
    cust_captured: int


def build_row(f: FeatureInput) -> np.ndarray:
    x = np.zeros(N_FEATURES, dtype=np.float64)
    x[_IDX[f"reason={normalize_reason(f.reason)}"]] = 1.0
    x[_IDX[f"method={normalize_method(f.method)}"]] = 1.0
    x[_IDX["log_amount"]] = math.log(max(float(f.amount), 1.0))
    x[_IDX["retry_count"]] = f.retry_count
    x[_IDX["comms_sent"]] = f.comms_sent
    x[_IDX["age_hours"]] = min(max(float(f.age_hours), 0.0), MAX_AGE_HOURS)
    ang = 2 * math.pi * (f.local_hour_frac % 24) / 24.0
    x[_IDX["hour_sin"]] = math.sin(ang)
    x[_IDX["hour_cos"]] = math.cos(ang)
    x[_IDX["salary_window"]] = 1.0 if (1 <= f.day_of_month <= 7 or f.day_of_month >= 28) else 0.0
    x[_IDX["weekend"]] = 1.0 if f.weekday >= 5 else 0.0
    x[_IDX["cust_log_n"]] = math.log1p(max(f.cust_n, 0))
    x[_IDX["cust_success_rate"]] = smooth_rate(f.cust_captured, f.cust_n)
    return x


def monotonic_vector() -> list[int]:
    v = [0] * N_FEATURES
    for name, sign in MONOTONIC.items():
        v[_IDX[name]] = sign
    return v


def row_to_dict(x: np.ndarray) -> dict[str, float]:
    return {c: round(float(x[i]), 6) for i, c in enumerate(FEATURE_COLUMNS) if x[i] != 0.0}


def dict_to_row(d: dict) -> np.ndarray:
    x = np.zeros(N_FEATURES, dtype=np.float64)
    for k, v in d.items():
        if k in _IDX:
            x[_IDX[k]] = float(v)
    return x


_CANONICAL = [
    FeatureInput("insufficient_funds", "upi", 1500.0, 1, 0, 12.0, 14.5, 3, 2, 6, 5),
    FeatureInput("otp_timeout", "card", 90.0, 0, 2, 0.25, 2.0, 15, 6, 0, 0),
    FeatureInput("card_declined", "wallet", 45000.0, 2, 1, 70.0, 22.75, 30, 4, 25, 3),
    FeatureInput(None, "mystery", 10.0, 0, 0, 500.0, 23.99, 1, 5, 1, 1),
]


def fingerprint() -> str:
    """Hash of what the features MEAN (not just their names): the vectors produced for fixed
    canonical inputs. Stored with every trained model and verified on load, so a silent change to
    feature engineering can never pair a stale model with new features (train/serve skew)."""
    import hashlib
    blob = np.round(np.vstack([build_row(c) for c in _CANONICAL]), 6).tobytes() + "|".join(FEATURE_COLUMNS).encode()
    return hashlib.sha1(blob).hexdigest()[:16]
