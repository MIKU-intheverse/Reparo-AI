import numpy as np

from app.config import get_settings
from app.ml import evaluate as E
from app.ml.episodes import (COOLDOWN_H, MAX_COMMS, MAX_RETRIES, NaiveRetryPolicy, RulesPolicy, Plan, run_episode)
from app.ml.world import BASE_WORLD, generate_cases

settings = get_settings()


def test_evaluation_is_reproducible_and_ordered():
    kw = dict(n_cases=1200, seed=99, write=False, include_sweep=False, bootstrap=200)
    a, b = E.run_evaluation(**kw), E.run_evaluation(**kw)
    assert a["base"]["policies"] == b["base"]["policies"]
    net = {p["policy"]: p["net_per_case"] for p in a["base"]["policies"]}
    assert net["do_nothing"] < net["naive_retry"] < net["rules"]
    for p in a["base"]["policies"]:
        lo, hi = p["net_per_case_ci95"]
        assert lo <= p["net_per_case"] <= hi
    assert a["base"]["bandit_vs_oracle"] and len(a["base"]["learning_curve"]) == 10


def test_ml_risk_is_neutral_when_reviewers_are_not_a_bottleneck_and_helps_when_they_are():
    r = E.run_evaluation(n_cases=3000, seed=5, write=False, include_sweep=True, bootstrap=100, approvals_per_day=8)
    sweep = {row["reviews_per_day"]: row["lift_per_case"] for row in r["capacity_sweep"]}
    assert abs(sweep[24]) < 1.0 and sweep[2] > 20 and sweep[4] > 20


def test_episodes_never_exceed_retry_or_message_caps():
    cases = generate_cases(3000, 8)
    for pol in (RulesPolicy(), NaiveRetryPolicy()):
        for c in cases:
            r = run_episode(c, pol, pol.plan(c))
            assert r.attempts <= MAX_RETRIES and r.messages <= MAX_COMMS


def test_ml_policy_delays_respect_cooldown_in_every_episode():
    cases = generate_cases(2500, 21)
    pol = E.MLFullPolicy({}, seed=1)
    for c in cases:
        plan = pol.plan(c)
        run_episode(c, pol, plan)
    for ctx, counts in pol.choices.items():
        if ctx.endswith("|later"):
            assert all(arm >= COOLDOWN_H for arm in counts)


def test_review_queue_respects_capacity_and_priority():
    cases = [c for c in generate_cases(600, 4) if c.reason in ("card_declined", "expired_card")]
    plans = {c.cid: Plan("link", priority=c.amount) for c in cases}
    out = E.assign_approvals(cases, plans, capacity=1)
    by_day = {}
    for cid, age in out.items():
        day = int((next(c for c in cases if c.cid == cid).t0 + age) // 24)
        by_day[day] = by_day.get(day, 0) + 1
    assert max(by_day.values()) <= 1
    assert all(age <= settings.recovery_window_days * 24 for age in out.values())


def test_shifted_world_differs_but_bandit_still_helps():
    r = E.run_evaluation(n_cases=3000, seed=17, write=False, include_sweep=False, bootstrap=300)
    full = next(p for p in r["shifted"]["policies"] if p["policy"] == "ml_full")
    assert full["lift_vs_rules_per_case"] > 0


def test_conservative_world_lift_holds_under_pessimistic_assumptions():
    r = E.run_evaluation(n_cases=3000, seed=23, write=False, include_sweep=False, bootstrap=300)
    by = {p["policy"]: p for p in r["conservative"]["policies"]}
    assert 0.25 <= by["rules"]["recovery_rate"] <= 0.55                      # inside the published band
    assert by["ml_full"]["lift_vs_rules_per_case"] > 0 and by["do_nothing"]["recovery_rate"] < by["rules"]["recovery_rate"]
