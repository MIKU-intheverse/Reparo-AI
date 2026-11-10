"""
Thompson-sampling bandit that learns *when* to retry.

For every context (failure reason x first-vs-later retry) the bandit keeps a
Beta posterior over the success probability of each candidate delay ("arm").
To choose a delay it samples once from every arm's posterior and plays the
arm with the highest sample — exploration happens automatically in proportion
to uncertainty, and fades as evidence accumulates.

Safety: the bandit never sees the whole delay space. `rules.allowed_delay_arms`
removes any arm that would violate the cooldown or fall outside the recovery
window, and the retry cap / approval requirements are enforced elsewhere. The
bandit can only pick *within* those bounds.

Cold start: priors are weak (default 4 pseudo-observations) and centred on the
legacy per-category success rates, so a brand-new merchant behaves sensibly
and then adapts to its own customers. Rewards are the observed outcome of the
retry that followed the chosen delay.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.ml.features import normalize_reason
from app.recovery import rules

LEGACY_PRIOR_MEAN = {"soft_decline": 0.55, "technical": 0.65, "hard_decline": 0.05, "unknown": 0.25}


def context_key(reason: str | None, retry_count: int) -> str:
    return f"{normalize_reason(reason)}|{'first' if retry_count == 0 else 'later'}"


def prior_for(context: str, strength: float) -> tuple[float, float]:
    reason = context.split("|")[0]
    mean = LEGACY_PRIOR_MEAN[rules.classify_failure(None if reason == "unknown" else reason)]
    return mean * strength, (1 - mean) * strength


class MemoryStore:
    def __init__(self):
        self.counts: dict[tuple[str, float], list[float]] = {}

    def get(self, ctx: str, arm: float) -> tuple[float, float]:
        s, f = self.counts.get((ctx, arm), (0.0, 0.0))
        return s, f

    def add(self, ctx: str, arm: float, reward: int) -> None:
        c = self.counts.setdefault((ctx, arm), [0.0, 0.0])
        c[0 if reward else 1] += 1.0


class DBStore:
    """Per-user posterior counts persisted in the bandit_arms table."""

    def __init__(self, db, user_id: str):
        from app.models import BanditArm
        self.db, self.user_id, self.M = db, user_id, BanditArm

    def _row(self, ctx: str, arm: float):
        return (self.db.query(self.M).filter_by(user_id=self.user_id, context_key=ctx, arm_hours=arm).first())

    def get(self, ctx: str, arm: float) -> tuple[float, float]:
        r = self._row(ctx, arm)
        return (r.successes, r.failures) if r else (0.0, 0.0)

    def add(self, ctx: str, arm: float, reward: int) -> None:
        from datetime import datetime
        r = self._row(ctx, arm)
        if r is None:
            r = self.M(user_id=self.user_id, context_key=ctx, arm_hours=arm, successes=0.0, failures=0.0)
            self.db.add(r)
        if reward:
            r.successes += 1.0
        else:
            r.failures += 1.0
        r.updated_at = datetime.utcnow()
        self.db.flush()

    def all_rows(self):
        return self.db.query(self.M).filter_by(user_id=self.user_id).all()


@dataclass
class Choice:
    arm: float
    context: str
    sampled: float
    posterior_mean: float
    observations: float
    alternatives: list[dict]


class ThompsonBandit:
    def __init__(self, store=None, prior_strength: float = 4.0, seed: int | None = None):
        self.store = store or MemoryStore()
        self.prior_strength = prior_strength
        self.rng = random.Random(seed)

    def posterior(self, ctx: str, arm: float) -> tuple[float, float]:
        a0, b0 = prior_for(ctx, self.prior_strength)
        s, f = self.store.get(ctx, arm)
        return a0 + s, b0 + f

    def mean(self, ctx: str, arm: float) -> float:
        a, b = self.posterior(ctx, arm)
        return a / (a + b)

    def observations(self, ctx: str, arm: float) -> float:
        s, f = self.store.get(ctx, arm)
        return s + f

    def choose(self, ctx: str, arms: list[float]) -> Choice | None:
        if not arms:
            return None
        samples = {}
        for arm in arms:
            a, b = self.posterior(ctx, arm)
            samples[arm] = self.rng.betavariate(a, b)
        best = max(arms, key=lambda x: samples[x])
        alts = [{"arm_hours": a, "sampled": round(samples[a], 3), "posterior_mean": round(self.mean(ctx, a), 3),
                 "observations": self.observations(ctx, a)} for a in sorted(arms)]
        return Choice(best, ctx, samples[best], self.mean(ctx, best), self.observations(ctx, best), alts)

    def update(self, ctx: str, arm: float, reward: int) -> None:
        self.store.add(ctx, arm, 1 if reward else 0)

    def best_arm(self, ctx: str, arms: list[float]) -> float | None:
        return max(arms, key=lambda x: self.mean(ctx, x)) if arms else None
