"""
Generative "world" for failed-payment recovery.

This module is the single source of ground truth for:
  * the Test-Mode sandbox (SimulationProvider asks it whether a retry succeeds),
  * training data for the recovery-probability model,
  * the offline policy-evaluation harness.

It encodes plausible, *stylised* structure — it is NOT calibrated to real
production data (none is publicly available):

  insufficient_funds  recovers better the longer we wait (balances refill),
                      with a bonus when the retry lands in the salary window
                      (day 1-7 of the month); large amounts recover worse.
  otp_timeout         recovers only if retried quickly while the customer is
                      still engaged; night-time retries are worse.
  issuer/bank errors  transient infrastructure faults: retrying instantly hits
                      the same fault, retrying after a few hours works best.
  gateway_timeout     clears fast.
  risk_check_failed   improves slowly as risk scores decay.
  card_declined /     hard declines: retrying essentially never works; the
  expired_card        customer must supply a new payment method.

Every retry also gets worse with each prior failure, and more reliable
customers recover more often. Customers may also pay on their own ("organic
recovery"), which is why a do-nothing baseline is not zero.

The marginal per-category retry success rates are anchored to the legacy
sandbox constants (soft .55, technical .65, hard .05, unknown .25) so the
sandbox's headline behaviour is preserved while adding realistic structure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import numpy as np

REASONS = ["insufficient_funds", "card_declined", "otp_timeout", "issuer_unavailable",
           "risk_check_failed", "bank_timeout", "gateway_timeout", "expired_card"]
METHODS = ["card", "upi", "netbanking", "wallet"]

# Sandbox calendar: hour 0 == 2025-01-01 00:00 (local time, a Wednesday).
EPOCH = datetime(2025, 1, 1)
_EPOCH_WEEKDAY = EPOCH.weekday()          # Mon=0 ... Sun=6
_MAX_DAYS = 3 * 366
_DOM_TABLE = [(EPOCH + timedelta(days=i)).day for i in range(_MAX_DAYS)]

# Failure-reason mix conditional on payment method (rows sum to 1).
REASON_MIX = {
    "card":       {"insufficient_funds": .24, "card_declined": .22, "otp_timeout": .12, "issuer_unavailable": .09,
                   "risk_check_failed": .12, "bank_timeout": .05, "gateway_timeout": .06, "expired_card": .10},
    "upi":        {"insufficient_funds": .34, "card_declined": .00, "otp_timeout": .12, "issuer_unavailable": .14,
                   "risk_check_failed": .06, "bank_timeout": .20, "gateway_timeout": .12, "expired_card": .02},
    "netbanking": {"insufficient_funds": .26, "card_declined": .06, "otp_timeout": .22, "issuer_unavailable": .16,
                   "risk_check_failed": .06, "bank_timeout": .14, "gateway_timeout": .08, "expired_card": .02},
    "wallet":     {"insufficient_funds": .46, "card_declined": .04, "otp_timeout": .10, "issuer_unavailable": .08,
                   "risk_check_failed": .08, "bank_timeout": .04, "gateway_timeout": .16, "expired_card": .04},
}
METHOD_MIX = {"card": .45, "upi": .35, "netbanking": .12, "wallet": .08}
# Diurnal arrival profile (local hour): evening-heavy.
_HOUR_W = np.array([.4, .25, .2, .15, .2, .4, .8, 1.3, 1.8, 2.2, 2.6, 3.0, 3.2, 3.2, 3.0, 3.0, 3.2, 3.6, 4.0, 4.4, 4.6, 4.2, 2.6, 1.2])
_HOUR_W = _HOUR_W / _HOUR_W.sum()

UNKNOWN = "unknown"


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def time_parts_from_hours(t_hours: float) -> tuple[int, int, int, float]:
    """(hour_of_day, day_of_month, weekday, fractional_hour) for sandbox time."""
    day = int(t_hours // 24)
    day = min(max(day, 0), _MAX_DAYS - 1)
    frac = t_hours - 24 * (t_hours // 24)
    return int(frac), _DOM_TABLE[day], (day + _EPOCH_WEEKDAY) % 7, float(frac)


def time_parts_from_datetime(dt_local: datetime) -> tuple[int, int, int, float]:
    frac = dt_local.hour + dt_local.minute / 60.0 + dt_local.second / 3600.0 + dt_local.microsecond / 3.6e9
    return dt_local.hour, dt_local.day, dt_local.weekday(), float(frac)


@dataclass(frozen=True)
class WorldParams:
    """All structural constants of the world. `shifted()` returns a perturbed
    world used to test how policies behave when reality drifts from what the
    offline model was trained on."""
    name: str = "base"
    base_logit: dict = field(default_factory=lambda: {
        "insufficient_funds": -0.55, "card_declined": -3.3, "otp_timeout": -0.95, "issuer_unavailable": -0.45,
        "risk_check_failed": -0.65, "bank_timeout": -0.25, "gateway_timeout": -0.10, "expired_card": -3.8,
        UNKNOWN: -1.2})
    method_adj: dict = field(default_factory=lambda: {"card": 0.0, "upi": 0.15, "netbanking": -0.2, "wallet": 0.05})
    fund_gain: float = 1.2
    fund_tau: float = 24.0
    salary_bonus: float = 0.8
    salary_tail: float = 0.3
    otp_gain: float = 1.3
    otp_tau: float = 2.5
    night_pen: float = 0.7
    infra_gain: float = 1.1
    issuer_peak_h: float = 3.0
    bank_peak_h: float = 2.0
    infra_width: float = 0.9
    immediate_pen: float = 0.5
    gw_gain: float = 0.8
    gw_tau: float = 6.0
    risk_gain: float = 0.9
    risk_tau: float = 40.0
    retry_decay: float = 0.55
    cust_coef: float = 1.4
    amount_coef_funds: float = 0.42
    amount_coef_risk: float = 0.55
    amount_coef_other: float = 0.12
    link_base: float = -0.35
    link_resp_coef: float = 2.2
    link_amount_coef: float = 0.28
    link_msg_decay: float = 0.7
    logit_offset: float = 0.0          # global shift applied to every retry / link success logit
    organic_scale: float = 1.0         # multiplier on the unaided-payment hazard
    organic_per_day: dict = field(default_factory=lambda: {
        "insufficient_funds": .020, "otp_timeout": .035, "gateway_timeout": .040, "issuer_unavailable": .030,
        "bank_timeout": .030, "risk_check_failed": .010, "card_declined": .010, "expired_card": .008, UNKNOWN: .010})

    def conservative(self) -> "WorldParams":
        """A pessimistic world calibrated to PUBLISHED industry recovery rates (see
        data/industry_benchmarks.json): one global logit shift and a lower organic-payment rate,
        chosen so the *rules* baseline recovers ~40% of failures — inside the 25-55% band vendors
        report. Only the rules baseline was used to pick the offset; no ML policy was."""
        return replace(self, name="conservative", logit_offset=CONSERVATIVE_OFFSET, organic_scale=0.5)

    def shifted(self) -> "WorldParams":
        """A drifted world: funds refill faster, salary effect weakens, OTP urgency
        fades slower, infra faults last longer, risk scores decay quicker."""
        return replace(self, name="shifted", fund_tau=12.0, salary_bonus=0.3, otp_tau=6.0, issuer_peak_h=8.0,
                       bank_peak_h=6.0, risk_tau=18.0, retry_decay=0.35, gw_tau=12.0)


CONSERVATIVE_OFFSET = -1.6      # calibrated in tests/test_world_and_features.py::test_conservative_world_matches_published_band
BASE_WORLD = WorldParams()


def get_world(name: str) -> WorldParams:
    """base | shifted | conservative (anything else -> base)."""
    if name == "shifted":
        return BASE_WORLD.shifted()
    if name == "conservative":
        return BASE_WORLD.conservative()
    return BASE_WORLD


def _amount_coef(reason: str, p: WorldParams) -> float:
    if reason == "insufficient_funds":
        return p.amount_coef_funds
    if reason == "risk_check_failed":
        return p.amount_coef_risk
    return p.amount_coef_other


def _log_bump(age: float, peak: float, width: float) -> float:
    return math.exp(-((math.log((age + 0.25) / peak)) ** 2) / (2 * width ** 2))


def time_curve(reason: str, age_h: float, hour: int, dom: int, p: WorldParams) -> float:
    """Logit contribution of *when* the retry happens, per failure reason."""
    if reason == "insufficient_funds":
        z = p.fund_gain * (1 - math.exp(-age_h / p.fund_tau))
        if 1 <= dom <= 7:
            z += p.salary_bonus
        elif dom >= 28:
            z += p.salary_tail
        return z
    if reason == "otp_timeout":
        z = p.otp_gain * math.exp(-age_h / p.otp_tau)
        if hour < 6:
            z -= p.night_pen
        elif 18 <= hour <= 22:
            z += 0.2
        return z
    if reason == "issuer_unavailable":
        return p.infra_gain * _log_bump(age_h, p.issuer_peak_h, p.infra_width) - p.immediate_pen * math.exp(-age_h / 0.4)
    if reason == "bank_timeout":
        return p.infra_gain * _log_bump(age_h, p.bank_peak_h, p.infra_width) - p.immediate_pen * math.exp(-age_h / 0.4)
    if reason == "gateway_timeout":
        return p.gw_gain * math.exp(-age_h / p.gw_tau)
    if reason == "risk_check_failed":
        return p.risk_gain * (1 - math.exp(-age_h / p.risk_tau))
    if reason in ("card_declined", "expired_card"):
        return 0.1 * (1 - math.exp(-age_h / 48.0))
    return 0.0


def retry_success_prob(reason: str | None, method: str, amount: float, cust_rate: float, age_h: float,
                       retry_idx: int, hour: int, dom: int, params: WorldParams = BASE_WORLD) -> float:
    """P(silent retry succeeds). `age_h` is hours since the original failure;
    `retry_idx` is the number of retries already attempted."""
    r = reason if reason in params.base_logit else UNKNOWN
    z = params.base_logit[r]
    z += params.method_adj.get(method, 0.0)
    z -= _amount_coef(r, params) * math.log(max(amount, 50.0) / 1800.0)
    z += params.cust_coef * (cust_rate - 0.75)
    z += time_curve(r, max(age_h, 0.0), hour, dom, params)
    z -= params.retry_decay * retry_idx
    return sigmoid(z + params.logit_offset)


def link_success_prob(reason: str | None, amount: float, resp: float, msg_idx: int, hour: int,
                      params: WorldParams = BASE_WORLD) -> float:
    """P(customer completes a payment after recovery message #msg_idx)."""
    z = params.link_base + params.link_resp_coef * (resp - 0.4)
    z -= params.link_amount_coef * math.log(max(amount, 50.0) / 1800.0)
    z -= params.link_msg_decay * msg_idx
    z += 0.3 if 9 <= hour <= 21 else -0.6
    if reason in ("card_declined", "expired_card"):
        z += 0.25
    return sigmoid(z + params.logit_offset)


def organic_hazard_per_hour(reason: str | None, cust_rate: float, params: WorldParams = BASE_WORLD) -> float:
    r = reason if reason in params.organic_per_day else UNKNOWN
    return params.organic_per_day[r] * params.organic_scale * (0.5 + cust_rate) / 24.0


@dataclass
class Case:
    """One failed payment plus all the randomness needed to replay it under any
    policy (common random numbers => low-variance policy comparisons)."""
    cid: int
    t0: float                  # failure time, hours since EPOCH (local)
    reason: str | None
    method: str
    amount: float
    cust_n: int                # prior payments by this customer
    cust_captured: int         # of which succeeded
    resp: float                # latent responsiveness to payment links (hidden from models)
    t_org: float               # hours after t0 at which the customer would pay unaided (inf if never)
    u_retry: tuple             # uniforms deciding retry outcomes
    u_link: tuple              # uniforms deciding link outcomes
    u_resp: tuple              # uniforms for response latency after a message
    u_appr: float              # reviewer approval latency (hours) when unconstrained

    @property
    def cust_rate(self) -> float:
        from app.ml.features import smooth_rate
        return smooth_rate(self.cust_captured, self.cust_n)


def generate_cases(n: int, seed: int, params: WorldParams = BASE_WORLD, horizon_days: float | None = None,
                   arrivals_per_day: float = 40.0) -> list[Case]:
    rng = np.random.default_rng(seed)
    days = horizon_days if horizon_days is not None else max(n / arrivals_per_day, 1.0)
    n_days = max(int(math.ceil(days)), 1)
    cases: list[Case] = []
    day_idx = rng.integers(0, n_days, size=n)
    hours = rng.choice(24, size=n, p=_HOUR_W)
    minutes = rng.uniform(0, 1, size=n)
    methods = rng.choice(METHODS, size=n, p=[METHOD_MIX[m] for m in METHODS])
    for i in range(n):
        method = str(methods[i])
        mix = REASON_MIX[method]
        reason: str | None = str(rng.choice(REASONS, p=[mix[r] for r in REASONS]))
        if rng.random() < 0.03:
            reason = None                       # provider gave no reason
        amount = float(np.clip(rng.lognormal(math.log(1800), 1.0), 50, 150000))
        reliab = float(rng.beta(6, 2))
        cust_n = int(1 + rng.poisson(2 + 14 * reliab))
        cust_captured = int(rng.binomial(cust_n, reliab))
        resp = float(np.clip(0.55 * reliab + 0.45 * rng.beta(2, 3), 0.02, 0.98))
        t0 = float(day_idx[i] * 24 + hours[i] + minutes[i])
        from app.ml.features import smooth_rate
        rate = smooth_rate(cust_captured, cust_n)
        hz = organic_hazard_per_hour(reason, rate, params)
        t_org = float(rng.exponential(1.0 / hz)) if hz > 0 else float("inf")
        cases.append(Case(
            cid=i, t0=t0, reason=reason, method=method, amount=amount, cust_n=cust_n, cust_captured=cust_captured,
            resp=resp, t_org=t_org, u_retry=tuple(float(x) for x in rng.random(8)),
            u_link=tuple(float(x) for x in rng.random(4)), u_resp=tuple(float(x) for x in rng.random(4)),
            u_appr=float(rng.uniform(1.0, 12.0))))
    cases.sort(key=lambda c: c.t0)
    for j, c in enumerate(cases):
        c.cid = j
    return cases
