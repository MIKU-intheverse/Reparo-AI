import random
from datetime import datetime, timedelta

import pytest

from app.config import get_settings
from app.ml import service
from app.ml.bandit import DBStore, MemoryStore, ThompsonBandit, context_key, prior_for
from app.models import MLDecision, RecoveryCase

settings = get_settings()


def test_context_keys_and_priors():
    assert context_key("Insufficient_Funds", 0) == "insufficient_funds|first"
    assert context_key(None, 2) == "unknown|later"
    a, b = prior_for("card_declined|first", 4.0)
    assert round(a / (a + b), 2) == 0.05                      # legacy hard-decline prior
    a, b = prior_for("gateway_timeout|first", 4.0)
    assert round(a / (a + b), 2) == 0.65


def test_thompson_sampling_converges_to_best_arm():
    truth = {0.25: 0.30, 6.0: 0.45, 12.0: 0.70, 24.0: 0.50, 48.0: 0.40, 72.0: 0.35}
    rng = random.Random(1)
    bandit = ThompsonBandit(prior_strength=4.0, seed=2)
    picks = []
    for _ in range(1500):
        ch = bandit.choose("insufficient_funds|first", list(truth))
        picks.append(ch.arm)
        bandit.update(ch.context, ch.arm, rng.random() < truth[ch.arm])
    last = picks[-400:]
    assert last.count(12.0) / len(last) > 0.7
    assert bandit.best_arm("insufficient_funds|first", list(truth)) == 12.0
    # exploration happened early (every arm was tried)
    assert set(picks[:300]) == set(truth)


def test_choose_handles_empty_and_returns_alternatives():
    b = ThompsonBandit(seed=0)
    assert b.choose("x|first", []) is None
    ch = b.choose("otp_timeout|first", [0.25, 6.0])
    assert {a["arm_hours"] for a in ch.alternatives} == {0.25, 6.0}


def test_db_store_persists_counts(db, user):
    b1 = ThompsonBandit(DBStore(db, user.id), seed=0)
    b1.update("otp_timeout|first", 0.25, 1)
    b1.update("otp_timeout|first", 0.25, 0)
    b1.update("otp_timeout|first", 0.25, 1)
    db.commit()
    b2 = ThompsonBandit(DBStore(db, user.id), seed=0)
    assert b2.store.get("otp_timeout|first", 0.25) == (2.0, 1.0)
    assert b2.observations("otp_timeout|first", 0.25) == 3.0
    assert b2.mean("otp_timeout|first", 0.25) > prior_for("otp_timeout|first", 4.0)[0] / 4.0 - 0.2


def _case(db, user, retry_count=0, reason="insufficient_funds", window_hours=168.0):
    now = datetime.utcnow()
    c = RecoveryCase(user_id=user.id, source="test", payment_id=f"p{random.random()}", amount=900.0,
                     failure_reason_raw=reason, category="soft_decline", retry_count=retry_count, method="upi",
                     recovery_window_expires_at=now + timedelta(hours=window_hours), failed_payment_created_at=now, created_at=now)
    db.add(c); db.flush()
    return c


def test_chosen_delays_always_respect_guardrails(db, user):
    """Whatever the bandit samples, delays must honour the cooldown (after the first retry) and the window."""
    for _ in range(80):
        first = service.choose_timing(db, user, _case(db, user, 0), "retry")
        assert first.source == "bandit" and first.delay <= timedelta(hours=72)
        later = service.choose_timing(db, user, _case(db, user, 1), "retry")
        assert later.delay >= timedelta(hours=settings.recovery_cooldown_hours)
        short = service.choose_timing(db, user, _case(db, user, 1, window_hours=20), "retry")
        assert short.delay <= timedelta(hours=20) and short.delay >= timedelta(hours=settings.recovery_cooldown_hours)


def test_non_retry_strategies_and_disabled_bandit_use_rules(db, user, monkeypatch):
    c = _case(db, user)
    assert service.choose_timing(db, user, c, "request_new_method").source == "rules"
    monkeypatch.setattr(settings, "ml_bandit_enabled", False)
    assert service.choose_timing(db, user, c, "retry").source == "rules"
    # window too short for any arm -> safe fallback to rules, never an exception
    monkeypatch.setattr(settings, "ml_bandit_enabled", True)
    tiny = _case(db, user, retry_count=1, window_hours=2)
    assert service.choose_timing(db, user, tiny, "retry").source == "rules"


def test_rewards_only_for_retries_that_actually_ran(db, user):
    c = _case(db, user)
    ch = service.choose_timing(db, user, c, "retry")
    # case recovers organically before the scheduled retry ever executes -> must NOT credit the arm
    c.status = "recovered"
    service.sweep_outcomes(db, user.id)
    d = db.query(MLDecision).filter_by(case_id=c.id, kind="timing").one()
    assert d.outcome == -1
    assert DBStore(db, user.id).get(ch.context, ch.arm) == (0.0, 0.0)
    # executed retry that failed in test mode -> immediate reward of 0 recorded
    c2 = _case(db, user)
    ch2 = service.choose_timing(db, user, c2, "retry")
    service.record_retry_outcome(db, c2, False)
    assert DBStore(db, user.id).get(ch2.context, ch2.arm) == (0.0, 1.0)
