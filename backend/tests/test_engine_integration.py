"""End-to-end behaviour of the recovery engine with the ML layer attached (sandbox / Test Mode)."""
import json
import random

import pytest

from app.config import get_settings
from app.ml import service
from app.models import BanditArm, MLAlert, MLDecision, RecoveryCase
from app.providers.factory import get_provider
from app.recovery import engine

settings = get_settings()


def _scan(user, db):
    return engine.run_scan(user, db)


def _cases(db, user, **f):
    return db.query(RecoveryCase).filter_by(user_id=user.id, **f).all()


def _trace(case):
    return [(t.agent, t.decision) for t in case.trace]


def test_scan_opens_cases_with_ml_risk_traces(db, user):
    _scan(user, db)
    cases = _cases(db, user)
    assert cases
    scored = [c for c in cases if c.status not in ("security_hold",)]
    for c in scored:
        assert 0.01 <= c.recovery_probability <= 0.97
        assert abs(c.expected_recovery_value - round(c.amount * c.recovery_probability, 2)) < 0.02
        risk = [t for t in c.trace if t.agent == "RiskAssessment"][0]
        assert "risk-gbm-" in risk.reason and "static category prior" in risk.reason
    d = service.explain_case(db, scored[0])
    assert d["risk"]["factors"] and d["risk"]["model_version"].startswith("risk-gbm-")


def test_ml_off_reproduces_legacy_behaviour(db, user, monkeypatch):
    monkeypatch.setattr(settings, "ml_enabled", False)
    _scan(user, db)
    for c in _cases(db, user):
        assert not any("learned timing" in d for _, d in _trace(c))
        assert "risk-gbm" not in "".join(t.reason for t in c.trace)
    retries = [c for c in _cases(db, user) if c.recommended_action == "retry"]
    assert retries and all(c.retry_count >= 1 for c in retries)        # legacy: first retry executes immediately
    assert db.query(MLDecision).count() == 0 and db.query(BanditArm).count() == 0


def test_guardrails_hold_over_many_scan_and_time_cycles(db, user):
    """Whatever the ML layer proposes, hard caps must never be exceeded."""
    provider = get_provider(user, db)
    provider.create_failed_batch(120)
    for _ in range(9):
        _scan(user, db)
        engine.advance_clock(user, db, 20)
    for c in _cases(db, user):
        assert c.retry_count <= c.max_retries == settings.recovery_max_retries
        assert c.communications_sent <= c.max_communications
        retry_steps = [t for t in c.trace if t.decision.startswith("Retry attempt") and "initiated" in t.decision]
        assert len(retry_steps) == c.retry_count                       # every retry is audited exactly once
        if c.status == "security_hold":
            assert c.retry_count == 0 and c.communications_sent == 0


def test_bandit_learns_from_executed_retries_only(db, user):
    provider = get_provider(user, db)
    provider.create_failed_batch(100)
    for _ in range(6):
        _scan(user, db)
        engine.advance_clock(user, db, 24)
    _scan(user, db)
    resolved = db.query(MLDecision).filter(MLDecision.kind == "timing", MLDecision.outcome.in_([0, 1])).count()
    total_obs = sum(a.successes + a.failures for a in db.query(BanditArm).all())
    assert resolved > 20 and total_obs == resolved                    # every reward traces back to one logged decision
    for d in db.query(MLDecision).filter(MLDecision.kind == "timing", MLDecision.outcome.in_([0, 1])):
        assert d.executed
    # decisions that never ran are censored, not rewarded
    for d in db.query(MLDecision).filter(MLDecision.kind == "timing", MLDecision.executed.is_(False), MLDecision.outcome.isnot(None)):
        assert d.outcome == -1


def test_outcomes_become_training_labels(db, user):
    provider = get_provider(user, db)
    provider.create_failed_batch(100)
    for _ in range(6):
        _scan(user, db)
        engine.advance_clock(user, db, 24)
    _scan(user, db)
    for d in db.query(MLDecision).filter(MLDecision.kind == "risk", MLDecision.outcome.isnot(None)):
        case = db.get(RecoveryCase, d.case_id)
        st = str(getattr(case.status, "value", case.status))
        assert d.outcome == {"recovered": 1, "exhausted": 0, "expired": 0}.get(st, -1)
    from app.ml.train import load_real_rows
    real = load_real_rows(db)
    assert real is not None and set(real[1]) <= {0, 1} and real[0].shape[1] == len(json.loads(
        db.query(MLDecision).filter_by(kind="risk").first().features)) or real[0].shape[0] > 0


def test_card_testing_goes_on_hold_and_nothing_happens_automatically(db, user):
    provider = get_provider(user, db)
    provider.inject_incident("card_testing")
    _scan(user, db)
    held = _cases(db, user, status="security_hold")
    assert len(held) >= 10
    for c in held:
        assert c.retry_count == 0 and c.communications_sent == 0 and c.recovery_probability == 0.0
        assert any(a == "Security" and "Held" in d for a, d in _trace(c))
    alert = db.query(MLAlert).filter_by(kind="card_testing").one()
    assert alert.status == "open" and alert.score > 0
    # a further scan and a time jump must not touch held cases
    engine.advance_clock(user, db, 48)
    _scan(user, db)
    for c in _cases(db, user, status="security_hold"):
        assert c.retry_count == 0 and c.communications_sent == 0


def test_hold_release_and_confirm_paths(db, user):
    provider = get_provider(user, db)
    provider.inject_incident("card_testing")
    _scan(user, db)
    held = _cases(db, user, status="security_hold")
    a, b = held[0], held[1]
    engine.release_security_hold(user, db, a, actor="reviewer@x.io")
    assert a.status != "security_hold" and any(t.actor == "reviewer@x.io" for t in a.trace)
    engine.confirm_security_hold(user, db, b, actor="reviewer@x.io")
    assert b.status == "suppressed"
    with pytest.raises(ValueError):
        engine.confirm_security_hold(user, db, b, actor="x")           # not on hold any more
    # alert stays open while other held cases remain
    assert db.query(MLAlert).filter_by(kind="card_testing").one().status == "open"
    for c in _cases(db, user, status="security_hold"):
        engine.confirm_security_hold(user, db, c, actor="reviewer@x.io")
    assert db.query(MLAlert).filter_by(kind="card_testing").one().status == "acknowledged"


def test_outage_defers_retries_without_consuming_them_then_resumes(db, user, monkeypatch):
    monkeypatch.setattr(settings, "ml_bandit_enabled", False)           # make first retries immediate => deferral is observable
    provider = get_provider(user, db)
    provider.inject_incident("outage", "upi")
    _scan(user, db)
    alert = db.query(MLAlert).filter_by(kind="method_outage").one()
    assert alert.subject == "upi" and alert.status == "open"
    upi = [c for c in _cases(db, user) if c.method == "upi" and c.recommended_action == "retry"
           and c.failed_payment_created_at > __import__("datetime").datetime.utcnow() - __import__("datetime").timedelta(hours=1)]
    assert len(upi) >= 10
    for c in upi:
        assert c.retry_count == 0 and c.status == "waiting"
        assert any(d.startswith("Retry deferred") for _, d in _trace(c))
        assert sum(1 for _, d in _trace(c) if d.startswith("Retry deferred")) <= settings.ml_max_outage_deferrals
    # time passes, the outage clears, deferred retries proceed within the normal caps
    engine.advance_clock(user, db, 3)
    _scan(user, db)
    _scan(user, db)
    assert db.query(MLAlert).filter_by(kind="method_outage").one().status == "resolved"
    assert any(c.retry_count >= 1 for c in upi)
    assert all(c.retry_count <= c.max_retries for c in upi)


def test_deferral_is_bounded(db, user, monkeypatch):
    """Even a permanent 'outage' can only postpone a case a bounded number of times."""
    monkeypatch.setattr(settings, "ml_bandit_enabled", False)
    monkeypatch.setattr(settings, "ml_max_outage_deferrals", 2)
    provider = get_provider(user, db)
    provider.inject_incident("outage", "upi")
    _scan(user, db)
    for _ in range(5):
        engine.advance_clock(user, db, 0.0)
        # keep the alert fresh to simulate a never-ending outage
        for al in db.query(MLAlert).filter_by(kind="method_outage").all():
            from datetime import datetime
            al.last_seen_at = datetime.utcnow()
        for c in _cases(db, user, status="waiting"):
            c.next_action_at = __import__("datetime").datetime.utcnow()
        db.commit()
        for c in _cases(db, user, status="waiting"):
            engine._process_waiting_case(user, db, c, get_provider(user, db))
        db.commit()
    for c in _cases(db, user):
        assert sum(1 for _, d in _trace(c) if d.startswith("Retry deferred")) <= 2


def test_advance_clock_is_test_mode_only(db, live_user):
    with pytest.raises(ValueError):
        engine.advance_clock(live_user, db, 5)


def test_metrics_include_security_holds(db, user):
    get_provider(user, db).inject_incident("card_testing")
    _scan(user, db)
    assert engine.get_metrics(user, db)["security_holds"] >= 10


def test_simulated_customers_can_complete_recovery_links(db, user):
    """Link cases: approve -> simulated customer responds -> next scan verifies capture -> recovered."""
    get_provider(user, db).create_failed_batch(120)
    _scan(user, db)
    recovered = 0
    for _ in range(4):
        for c in _cases(db, user, status="pending_approval"):
            engine.approve_case(user, db, c, actor="r@x.io")
        _scan(user, db)
        engine.advance_clock(user, db, 7)
        recovered = len(_cases(db, user, status="recovered"))
    link_recovered = [c for c in _cases(db, user, status="recovered") if c.recommended_action == "request_new_method"]
    assert link_recovered and all(c.communications_sent >= 1 for c in link_recovered)
    assert any("Customer completed the payment" in d for c in link_recovered for _, d in _trace(c))
