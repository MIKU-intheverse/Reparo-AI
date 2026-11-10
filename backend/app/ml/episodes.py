"""
Episode runner + non-ML baseline policies.

An *episode* replays one failed payment through a recovery policy inside the
world of world.py, using the case's pre-drawn uniforms so that different
policies are compared on identical randomness (common random numbers).

The runner mirrors the guardrails of the production engine:
  * at most `max_retries` silent retries and `max_comms` customer messages,
  * a cooldown between consecutive actions,
  * nothing after the recovery window closes,
  * recovery messages need a human approval (latency supplied by the caller).

It can also log the *decision states* a policy passes through (open, after each
failed retry, after each unanswered message) — that is the training data for
the recovery-probability model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import get_settings
from app.ml.features import FeatureInput
from app.ml.world import (BASE_WORLD, Case, WorldParams, link_success_prob, retry_success_prob,
                          time_parts_from_hours)
from app.recovery import rules

settings = get_settings()

WINDOW_H = settings.recovery_window_days * 24.0
MAX_RETRIES = settings.recovery_max_retries
MAX_COMMS = settings.recovery_max_communications
COOLDOWN_H = settings.recovery_cooldown_hours


@dataclass
class Plan:
    kind: str                 # "none" | "retry" | "link" | "manual"
    priority: float = 0.0     # higher = reviewed first when approval capacity is scarce
    p_hat: float | None = None


@dataclass
class EpisodeResult:
    recovered: bool = False
    organic: bool = False
    attempts: int = 0
    messages: int = 0
    reviewed: bool = False
    recovery_age_h: float | None = None
    states: list = field(default_factory=list)   # [(FeatureInput, retry_count, comms)] when logging


class Policy:
    """Interface every recovery policy implements."""
    name = "policy"

    def plan(self, case: Case) -> Plan:
        raise NotImplementedError

    def first_retry_delay(self, case: Case) -> float:
        return 0.0

    def next_retry_delay(self, case: Case, k: int, age_h: float) -> float | None:
        return COOLDOWN_H

    def feedback_retry(self, case: Case, k: int, delay_h: float, success: bool) -> None:
        pass


class DoNothingPolicy(Policy):
    name = "do_nothing"

    def plan(self, case):
        return Plan("none")


class NaiveRetryPolicy(Policy):
    """Retry everything on a fixed cadence, regardless of why it failed."""
    name = "naive_retry"

    def plan(self, case):
        return Plan("retry")

    def first_retry_delay(self, case):
        return 0.0

    def next_retry_delay(self, case, k, age_h):
        return COOLDOWN_H


class RulesPolicy(Policy):
    """The production rules engine before this ML upgrade: classify, then
    retry soft/technical failures at fixed per-category delays, ask hard
    declines for a new payment method, route unknowns to manual review."""
    name = "rules"

    @staticmethod
    def category(case: Case) -> str:
        return rules.classify_failure(case.reason)

    def plan(self, case):
        cat = self.category(case)
        p = rules.risk_assessment(cat, 0)
        if not rules.is_recoverable(p):
            return Plan("none", p_hat=p)
        strat = rules.choose_strategy(cat, 0)
        if strat == "retry":
            return Plan("retry", priority=case.amount * p, p_hat=p)
        if strat == "request_new_method":
            # First-come-first-served: earlier failures are reviewed first.
            return Plan("link", priority=-case.t0, p_hat=p)
        return Plan("manual", p_hat=p)

    def first_retry_delay(self, case):
        return 0.0          # legacy engine retried immediately on first detection

    def next_retry_delay(self, case, k, age_h):
        return max(COOLDOWN_H, rules.choose_timing(self.category(case)).total_seconds() / 3600.0)


def feature_input(case: Case, retry_count: int, comms: int, age_h: float) -> FeatureInput:
    hour, dom, wd, frac = time_parts_from_hours(case.t0 + age_h)
    return FeatureInput(reason=case.reason, method=case.method, amount=case.amount, retry_count=retry_count,
                        comms_sent=comms, age_hours=age_h, local_hour_frac=frac, day_of_month=dom, weekday=wd,
                        cust_n=case.cust_n, cust_captured=case.cust_captured)


def run_episode(case: Case, policy: Policy, plan: Plan, params: WorldParams = BASE_WORLD, *,
                approve_age_h: float | None = None, log_states: bool = False,
                window_h: float = WINDOW_H, max_retries: int = MAX_RETRIES, max_comms: int = MAX_COMMS,
                cooldown_h: float = COOLDOWN_H) -> EpisodeResult:
    res = EpisodeResult()

    def log(k: int, c: int, age: float):
        if log_states and case.t_org > age:          # only states in which the payment is still unpaid
            res.states.append((feature_input(case, k, c, age), k, c))

    log(0, 0, 0.0)

    if plan.kind == "retry":
        delay = max(policy.first_retry_delay(case), 0.0)
        age, k = 0.0, 0
        while k < max_retries:
            age += delay
            if age > window_h:
                break
            if case.t_org <= age:
                res.recovered = res.organic = True
                res.recovery_age_h = case.t_org
                return res
            hour, dom, _, _ = time_parts_from_hours(case.t0 + age)
            p = retry_success_prob(case.reason, case.method, case.amount, case.cust_rate, age, k, hour, dom, params)
            res.attempts += 1
            success = case.u_retry[k] < p
            policy.feedback_retry(case, k, delay, success)
            if success:
                res.recovered, res.recovery_age_h = True, age
                return res
            k += 1
            log(k, 0, age)
            if k >= max_retries:
                break
            nxt = policy.next_retry_delay(case, k, age)
            if nxt is None:
                break
            delay = max(nxt, cooldown_h)

    elif plan.kind == "link":
        age = case.u_appr if approve_age_h is None else approve_age_h
        res.reviewed = True
        j = 0
        while j < max_comms:
            if age > window_h:
                break
            if case.t_org <= age:
                res.recovered = res.organic = True
                res.recovery_age_h = case.t_org
                return res
            hour, _, _, _ = time_parts_from_hours(case.t0 + age)
            res.messages += 1
            p = link_success_prob(case.reason, case.amount, case.resp, j, hour, params)
            if case.u_link[j] < p:
                pay_age = age + case.u_resp[j] * cooldown_h
                if case.t_org < pay_age:
                    res.recovered = res.organic = True
                    res.recovery_age_h = case.t_org
                else:
                    res.recovered, res.recovery_age_h = True, pay_age
                return res
            j += 1
            log(0, j, age)
            age += cooldown_h

    # No (further) intervention: the customer may still pay unaided in the window.
    if case.t_org <= window_h:
        res.recovered = res.organic = True
        res.recovery_age_h = case.t_org
    return res
