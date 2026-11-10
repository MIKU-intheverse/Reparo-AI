"""
ScanContext: a one-shot, in-memory snapshot of the merchant's recent payments,
fetched ONCE per recovery scan (not once per case). It supplies
  * customer-history features for the risk model,
  * the per-customer velocity windows used by the card-testing detector,
  * per-method failure-rate series used by the outage detector.
Works identically for the Test-Mode sandbox and for live Razorpay data because
it only consumes the normalised payment dicts both providers return.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np


_EPOCH = datetime(1970, 1, 1)
SUCCESS_STATUSES = {"captured", "refunded", "authorized"}
INFRA_MARKERS = ("timeout", "unavailable", "network", "gateway", "server_error", "server error", "downtime")


def is_infra_reason(reason: str | None) -> bool:
    """Failure reasons that point at infrastructure (gateway / bank / network)
    rather than at the customer or the instrument. Deliberately broader than the
    retry classifier: `issuer_unavailable` is a 'soft decline' for retry purposes
    but is an infrastructure fault for outage detection."""
    r = (reason or "").lower()
    return any(m in r for m in INFRA_MARKERS)


def to_ts(dt: datetime) -> float:
    return (dt - _EPOCH).total_seconds()


def parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        d = datetime.fromisoformat(str(value).replace("Z", ""))
        return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
    except Exception:
        return None


def customer_key(email: str | None, contact: str | None) -> str | None:
    if email:
        return email.strip().lower()
    if contact:
        return contact.strip()
    return None


@dataclass
class PaymentRecord:
    id: str
    key: str | None
    method: str | None
    amount: float
    status: str
    reason: str | None
    ts: float


@dataclass
class MethodSeries:
    ts: np.ndarray
    failed: np.ndarray
    technical: np.ndarray


class ScanContext:
    def __init__(self, items: list[dict], now: datetime | None = None):
        self.now = now or datetime.now(timezone.utc).replace(tzinfo=None)
        recs: list[PaymentRecord] = []
        for p in items:
            dt = parse_dt(p.get("created_at"))
            if dt is None or not p.get("id"):
                continue
            recs.append(PaymentRecord(
                id=p["id"], key=customer_key(p.get("email"), p.get("contact")), method=p.get("method"),
                amount=float(p.get("amount") or 0.0), status=(p.get("status") or "").lower(),
                reason=p.get("failure_reason"), ts=to_ts(dt)))
        recs.sort(key=lambda r: r.ts)
        self.records = recs
        self.by_customer: dict[str, list[PaymentRecord]] = {}
        self._cust_ts: dict[str, list[float]] = {}
        for r in recs:
            if r.key:
                self.by_customer.setdefault(r.key, []).append(r)
        for k, lst in self.by_customer.items():
            self._cust_ts[k] = [r.ts for r in lst]
        self.series = self._build_series(recs)

    @staticmethod
    def _build_series(recs: list[PaymentRecord]) -> dict[str, MethodSeries]:
        by_m: dict[str, list[PaymentRecord]] = {}
        for r in recs:
            if r.method:
                by_m.setdefault(r.method, []).append(r)
        out = {}
        for m, lst in by_m.items():
            out[m] = MethodSeries(
                ts=np.array([r.ts for r in lst]),
                failed=np.array([r.status == "failed" for r in lst]),
                technical=np.array([r.status == "failed" and is_infra_reason(r.reason) for r in lst]))
        return out

    # ---- customer-level helpers ------------------------------------------
    def customer_history(self, key: str | None, before_ts: float, exclude_id: str | None = None) -> tuple[int, int]:
        """(n_prior_payments, n_prior_successful) strictly before `before_ts`."""
        if not key or key not in self.by_customer:
            return 0, 0
        lst, ts = self.by_customer[key], self._cust_ts[key]
        hi = bisect_left(ts, before_ts)
        prior = [r for r in lst[:hi] if r.id != exclude_id]
        return len(prior), sum(1 for r in prior if r.status in SUCCESS_STATUSES)

    def customer_window(self, key: str | None, t_ref: float, window_s: float) -> list[PaymentRecord]:
        """Payments by `key` in (t_ref - window_s, t_ref]."""
        if not key or key not in self.by_customer:
            return []
        lst, ts = self.by_customer[key], self._cust_ts[key]
        lo, hi = bisect_right(ts, t_ref - window_s), bisect_right(ts, t_ref)
        return lst[lo:hi]

    def customer_failures_since(self, key: str | None, t_ref: float, window_s: float) -> int:
        return sum(1 for r in self.customer_window(key, t_ref, window_s) if r.status == "failed")

    def window_slice(self, method: str, t_lo: float, t_hi: float):
        s = self.series.get(method)
        if s is None:
            return None
        lo, hi = np.searchsorted(s.ts, t_lo, side="right"), np.searchsorted(s.ts, t_hi, side="right")
        return s, lo, hi
