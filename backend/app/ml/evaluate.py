"""
Offline policy evaluation.

    python -m app.ml.evaluate                 # full report -> artifacts/eval_report.json
    python -m app.ml.evaluate --n-cases 2000  # quick run

Replays the SAME failed payments (same random draws) through five recovery
policies inside the world of world.py and compares economic outcomes:

  do_nothing   only organic recovery (customer pays unaided)
  naive_retry  retry every failure every 6h, never contact the customer
  rules        the production engine before the ML upgrade
  ml_risk      rules + calibrated recovery model (suppression + value-ranked review queue)
  ml_full      ml_risk + Thompson-sampling retry timing (learns online during the run)

Net value = recovered revenue - (retries x cost + messages x cost + human reviews x cost).
Human reviewers have limited daily capacity, so *which* cases they review first matters.
Results are bootstrapped over cases (95% CIs) and repeated in a *shifted* world where
the structure the model was trained on has drifted.

Caveat: the world is a stylised, documented simulator (see world.py) — these numbers
validate the machinery and show *why* each component helps; they are not a forecast.
"""
from __future__ import annotations

import argparse
import heapq
import math
import random
from datetime import datetime, timezone

import numpy as np

from app.ml import features as F
from app.ml import registry
from app.ml.bandit import ThompsonBandit, context_key
from app.ml.episodes import (COOLDOWN_H, MAX_RETRIES, WINDOW_H, DoNothingPolicy, NaiveRetryPolicy, Plan, Policy,
                             RulesPolicy, feature_input, run_episode)
from app.ml.world import BASE_WORLD, Case, WorldParams, generate_cases, retry_success_prob, time_parts_from_hours
from app.recovery import rules
from app.config import get_settings

settings = get_settings()
ARMS = list(settings.ml_bandit_arms_hours)

DEFAULTS = {"cost_retry": 2.0, "cost_message": 4.0, "cost_review": 25.0, "approvals_per_day": 8,
            "review_hour": 10, "n_cases": 6000, "seed": 2024, "bootstrap": 1000}


class MLRiskPolicy(RulesPolicy):
    """Rules for category/strategy, but the calibrated model decides whether a
    case is worth pursuing and how urgently a human should look at it."""
    name = "ml_risk"

    def __init__(self, p_open: dict[int, float]):
        self.p_open = p_open

    def plan(self, case: Case) -> Plan:
        base = super().plan(case)
        if base.kind == "none":
            return base
        p = rules.guard_probability(self.p_open.get(case.cid))
        if p is None:
            return base
        if not rules.is_recoverable(p):
            return Plan("none", p_hat=p)
        if base.kind in ("retry", "link"):
            return Plan(base.kind, priority=case.amount * p, p_hat=p)
        return Plan(base.kind, p_hat=p)


class MLFullPolicy(MLRiskPolicy):
    name = "ml_full"

    def __init__(self, p_open: dict[int, float], seed: int = 0, prior_strength: float | None = None):
        super().__init__(p_open)
        self.bandit = ThompsonBandit(prior_strength=prior_strength or settings.ml_bandit_prior_strength, seed=seed)
        self._pending: dict[int, tuple[str, float]] = {}
        self.choices: dict[str, dict[float, int]] = {}

    def _choose(self, case: Case, k: int, age_h: float) -> float | None:
        remaining = WINDOW_H - age_h
        arms = rules.allowed_delay_arms(ARMS, k, COOLDOWN_H, remaining)
        ch = self.bandit.choose(context_key(case.reason, k), arms)
        if ch is None:
            return None
        self._pending[case.cid] = (ch.context, ch.arm)
        self.choices.setdefault(ch.context, {}).setdefault(ch.arm, 0)
        self.choices[ch.context][ch.arm] += 1
        return ch.arm

    def first_retry_delay(self, case):
        d = self._choose(case, 0, 0.0)
        return 0.0 if d is None else d

    def next_retry_delay(self, case, k, age_h):
        return self._choose(case, k, age_h)

    def feedback_retry(self, case, k, delay_h, success):
        ctx, arm = self._pending.pop(case.cid, (None, None))
        if ctx is not None:
            self.bandit.update(ctx, arm, 1 if success else 0)


def assign_approvals(cases: list[Case], plans: dict[int, Plan], capacity: int, review_hour: int = 10,
                     window_h: float = WINDOW_H) -> dict[int, float]:
    """Daily human-review queue. Reviewers handle `capacity` link cases per day,
    highest `priority` first. Returns {case_id: hours-since-failure at approval}."""
    link = [c for c in cases if plans[c.cid].kind == "link"]
    if not link:
        return {}
    link.sort(key=lambda c: c.t0)
    heap: list = []
    i, out = 0, {}
    first_day = int(link[0].t0 // 24)
    last_day = int(link[-1].t0 // 24) + int(window_h // 24) + 2
    for d in range(first_day, last_day + 1):
        T = d * 24 + review_hour
        while i < len(link) and link[i].t0 <= T:
            heapq.heappush(heap, (-plans[link[i].cid].priority, link[i].cid))
            i += 1
        taken = 0
        while heap and taken < capacity:
            _, cid = heapq.heappop(heap)
            age = T - cases_by_id(cases)[cid].t0
            if age > window_h:
                continue
            out[cid] = age
            taken += 1
    return out


_CASE_INDEX: dict[int, dict[int, Case]] = {}


def cases_by_id(cases: list[Case]) -> dict[int, Case]:
    key = id(cases)
    if key not in _CASE_INDEX:
        _CASE_INDEX.clear()
        _CASE_INDEX[key] = {c.cid: c for c in cases}
    return _CASE_INDEX[key]


def run_policy(policy: Policy, cases: list[Case], params: WorldParams, capacity: int, costs: dict) -> dict:
    plans = {c.cid: policy.plan(c) for c in cases}
    approvals = assign_approvals(cases, plans, capacity, costs["review_hour"])
    value = np.zeros(len(cases))
    cost = np.zeros(len(cases))
    rec = np.zeros(len(cases))
    att = np.zeros(len(cases))
    msg = np.zeros(len(cases))
    rev = np.zeros(len(cases))
    ttr = np.full(len(cases), np.nan)
    for i, c in enumerate(cases):
        plan = plans[c.cid]
        if plan.kind == "link" and c.cid not in approvals:
            plan = Plan("none")                       # never reached a reviewer in time
        r = run_episode(c, policy, plan, params, approve_age_h=approvals.get(c.cid))
        rec[i] = r.recovered
        if r.recovered and r.recovery_age_h is not None:
            ttr[i] = r.recovery_age_h
        value[i] = c.amount if r.recovered else 0.0
        att[i], msg[i], rev[i] = r.attempts, r.messages, 1.0 if r.reviewed else 0.0
        cost[i] = r.attempts * costs["cost_retry"] + r.messages * costs["cost_message"] + rev[i] * costs["cost_review"]
    return {"recovered": rec, "value": value, "cost": cost, "attempts": att, "messages": msg, "reviews": rev,
            "net": value - cost, "hours_to_recovery": ttr}


def _bootstrap(rng, per_case: np.ndarray, B: int, base: np.ndarray | None = None) -> tuple[float, float]:
    n = len(per_case)
    idx = rng.integers(0, n, size=(B, n))
    arr = per_case if base is None else per_case - base
    means = arr[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(name: str, out: dict, cases: list[Case], rng, B: int, rules_out: dict | None) -> dict:
    n = len(cases)
    total_value = float(sum(c.amount for c in cases))
    s = {
        "policy": name,
        "recovery_rate": round(float(out["recovered"].mean()), 4),
        "recovered_value": round(float(out["value"].sum()), 2),
        "value_recovery_rate": round(float(out["value"].sum() / total_value), 4),
        "net_value": round(float(out["net"].sum()), 2),
        "net_per_case": round(float(out["net"].mean()), 2),
        "retries_per_case": round(float(out["attempts"].mean()), 3),
        "messages_per_case": round(float(out["messages"].mean()), 3),
        "reviews_per_case": round(float(out["reviews"].mean()), 3),
        "total_cost": round(float(out["cost"].sum()), 2),
        "mean_hours_to_recovery": round(float(np.nanmean(out["hours_to_recovery"])), 1)
        if np.isfinite(out["hours_to_recovery"]).any() else None,
    }
    lo, hi = _bootstrap(rng, out["net"], B)
    s["net_per_case_ci95"] = [round(lo, 2), round(hi, 2)]
    if rules_out is not None and name != "rules":
        dlo, dhi = _bootstrap(rng, out["net"], B, base=rules_out["net"])
        d = float((out["net"] - rules_out["net"]).mean())
        s["lift_vs_rules_per_case"] = round(d, 2)
        s["lift_vs_rules_ci95"] = [round(dlo, 2), round(dhi, 2)]
        s["lift_vs_rules_pct"] = round(100 * d / max(abs(float(rules_out["net"].mean())), 1e-9), 2)
        s["lift_significant"] = bool(dlo > 0 or dhi < 0)
    return s


def true_arm_success(reason: str, params: WorldParams, k: int = 0, n: int = 400, seed: int = 1) -> dict[float, float]:
    """Ground-truth success probability of each retry delay for a failure reason,
    averaged over the customer / amount / time mix. Used as a reference to check
    what the bandit should be learning; it is NOT visible to any policy."""
    cases = [c for c in generate_cases(n * 4, seed, params) if c.reason == reason][:n]
    out = {}
    for arm in ARMS:
        ps = []
        for c in cases:
            age = arm + (0 if k == 0 else COOLDOWN_H * k)
            h, d, _, _ = time_parts_from_hours(c.t0 + age)
            ps.append(retry_success_prob(c.reason, c.method, c.amount, c.cust_rate, age, k, h, d, params))
        out[arm] = float(np.mean(ps)) if ps else float("nan")
    return out


def learning_curve(rules_out: dict, ml_out: dict, chunks: int = 10) -> list[dict]:
    n = len(rules_out["net"])
    edges = np.linspace(0, n, chunks + 1).astype(int)
    return [{"chunk": i + 1, "cases": int(edges[i + 1] - edges[i]),
             "rules_net_per_case": round(float(rules_out["net"][edges[i]:edges[i + 1]].mean()), 2),
             "ml_full_net_per_case": round(float(ml_out["net"][edges[i]:edges[i + 1]].mean()), 2)} for i in range(chunks)]


def evaluate_world(model, params: WorldParams, cfg: dict, seed: int) -> dict:
    cases = generate_cases(cfg["n_cases"], seed, params)
    # Model probabilities at the moment a case opens (batch, once, shared by both ML policies).
    X = np.vstack([F.build_row(feature_input(c, 0, 0, 0.0)) for c in cases])
    p_open = dict(zip([c.cid for c in cases], model.predict_matrix(X).tolist())) if model else {}
    costs = {k: cfg[k] for k in ("cost_retry", "cost_message", "cost_review", "review_hour")}
    rng = np.random.default_rng(seed + 1)
    outs, ml_full = {}, MLFullPolicy(p_open, seed=seed)
    policies: list[Policy] = [DoNothingPolicy(), NaiveRetryPolicy(), RulesPolicy()]
    if model:
        policies += [MLRiskPolicy(p_open), ml_full]
    for pol in policies:
        outs[pol.name] = run_policy(pol, cases, params, cfg["approvals_per_day"], costs)
    summaries = [summarize(name, out, cases, rng, cfg["bootstrap"], outs["rules"]) for name, out in outs.items()]
    world = {"world": params.name, "n_cases": len(cases), "total_failed_value": round(float(sum(c.amount for c in cases)), 2),
             "policies": summaries}
    if model:
        world["learning_curve"] = learning_curve(outs["rules"], outs["ml_full"])
        reasons = ["insufficient_funds", "otp_timeout", "issuer_unavailable", "risk_check_failed", "gateway_timeout"]
        table = []
        for r in reasons:
            ctx = context_key(r, 0)
            truth = true_arm_success(r, params)
            learned = {a: ml_full.bandit.mean(ctx, a) for a in ARMS}
            table.append({"reason": r, "oracle_best_delay_h": max(truth, key=truth.get),
                          "learned_best_delay_h": max(learned, key=learned.get),
                          "chosen_counts": ml_full.choices.get(ctx, {}),
                          "true_success_by_delay": {str(a): round(v, 3) for a, v in truth.items()}})
        world["bandit_vs_oracle"] = table
    return world


def capacity_sweep(model, cfg: dict, seed: int, capacities=(2, 4, 8, 12, 24)) -> list[dict]:
    cases = generate_cases(max(cfg["n_cases"] // 2, 1500), seed + 7, BASE_WORLD)
    X = np.vstack([F.build_row(feature_input(c, 0, 0, 0.0)) for c in cases])
    p_open = dict(zip([c.cid for c in cases], model.predict_matrix(X).tolist()))
    costs = {k: cfg[k] for k in ("cost_retry", "cost_message", "cost_review", "review_hour")}
    out = []
    for cap in capacities:
        r = run_policy(RulesPolicy(), cases, BASE_WORLD, cap, costs)
        m = run_policy(MLRiskPolicy(p_open), cases, BASE_WORLD, cap, costs)
        out.append({"reviews_per_day": cap, "rules_net_per_case": round(float(r["net"].mean()), 2),
                    "ml_risk_net_per_case": round(float(m["net"].mean()), 2),
                    "lift_per_case": round(float((m["net"] - r["net"]).mean()), 2)})
    return out


def run_evaluation(n_cases: int | None = None, seed: int | None = None, quiet: bool = True, write: bool = True,
                   include_sweep: bool = True, **overrides) -> dict:
    cfg = {**DEFAULTS, **overrides}
    if n_cases:
        cfg["n_cases"] = n_cases
    if seed is not None:
        cfg["seed"] = seed
    model = registry.get_risk_model()
    report = {
        "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        "model_version": model.version if model else None,
        "config": {k: cfg[k] for k in cfg}, "window_hours": WINDOW_H, "max_retries": MAX_RETRIES,
        "base": evaluate_world(model, BASE_WORLD, cfg, cfg["seed"]),
        "shifted": evaluate_world(model, BASE_WORLD.shifted(), cfg, cfg["seed"] + 100),
        "conservative": evaluate_world(model, BASE_WORLD.conservative(), cfg, cfg["seed"] + 200),
        "notes": [
            "Same failed payments and random draws are replayed under every policy (common random numbers).",
            "The risk model is trained once on the base world; the shifted world has different recovery dynamics, "
            "so it tests robustness. The bandit starts cold in every world and learns online during the run.",
            "The conservative world is calibrated to PUBLISHED industry recovery rates (rules baseline ~40%, inside the 25-55% "
            "band vendors report) because the base world is more optimistic than published figures. See "
            "data/industry_benchmarks.json for sources and caveats.",
            "Human review capacity is limited (reviews_per_day); ml_risk ranks the queue by expected recovered value, "
            "rules reviews first-come-first-served.",
            "Adaptive timing trades speed for success: ml_full often waits longer before retrying, so mean hours-to-recovery "
            "rises while recovery rate and net value improve. A merchant that values cash-in-hand speed can restrict the arms.",
            "The world is a stylised simulator, not production data: treat results as validation of the machinery.",
        ],
    }
    if include_sweep and model:
        report["capacity_sweep"] = capacity_sweep(model, cfg, cfg["seed"])
    if write:
        registry.write_json("eval_report.json", report)
    if not quiet:
        for w in ("base", "shifted", "conservative"):
            print(f"\n== {w} world ({report[w]['n_cases']} failed payments) ==")
            for p in report[w]["policies"]:
                lift = f"  lift vs rules {p['lift_vs_rules_per_case']:+.2f}/case {p['lift_vs_rules_ci95']}" if "lift_vs_rules_per_case" in p else ""
                print(f"{p['policy']:12s} rec {p['recovery_rate']:.3f}  net/case {p['net_per_case']:8.2f} {p['net_per_case_ci95']}  "
                      f"retries {p['retries_per_case']:.2f} msgs {p['messages_per_case']:.2f}{lift}")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-cases", type=int, default=DEFAULTS["n_cases"])
    ap.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    ap.add_argument("--approvals-per-day", type=int, default=DEFAULTS["approvals_per_day"])
    args = ap.parse_args()
    run_evaluation(args.n_cases, args.seed, quiet=False, approvals_per_day=args.approvals_per_day)


if __name__ == "__main__":
    main()
