"""
ML service facade — the ONLY module the recovery engine talks to.

Everything here is fail-safe: if a model is missing, a provider call fails, or
anything raises, the function returns a result tagged source="rules" so the
engine continues with the deterministic rule-based behaviour. ML can improve a
decision; it can never be the reason the pipeline stops.

Guardrail contract (enforced in app/recovery/rules.py and the engine):
  * probabilities are sanitised by rules.guard_probability,
  * retry delays only come from rules.allowed_delay_arms (cooldown / window safe),
  * retry caps, message caps and human-approval requirements are untouched,
  * a security hold stops ALL automated action on a case until a human releases it.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.ml import anomaly as A
from app.ml import features as F
from app.ml import registry
from app.ml.bandit import DBStore, ThompsonBandit, context_key
from app.ml.context import ScanContext, customer_key, to_ts
from app.ml.world import time_parts_from_datetime
from app.models import MLAlert, MLDecision, RecoveryCase, RecoveryTraceStep, User
from app.providers.factory import get_provider
from app.recovery import rules

log = logging.getLogger("reparo.ml")
settings = get_settings()

TERMINAL_POSITIVE = {"recovered"}
TERMINAL_NEGATIVE = {"exhausted", "expired"}
TERMINAL_CENSORED = {"suppressed", "rejected", "manual_review"}


def _status(case: RecoveryCase) -> str:
    return str(getattr(case.status, "value", case.status))


def ml_active() -> bool:
    return bool(settings.ml_enabled)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
def build_context(user: User, db: Session, provider=None) -> ScanContext | None:
    """Fetch recent payments ONCE for features + anomaly checks. None => features degrade gracefully."""
    if not ml_active():
        return None
    try:
        provider = provider or get_provider(user, db)
        items = provider.get_payments(limit=settings.ml_history_fetch_limit)["items"]
        return ScanContext(items, now=datetime.utcnow())
    except Exception as e:  # network / provider problem must never break a scan
        log.warning("ML context unavailable (%s); continuing without history features.", e)
        return None


def feature_input(case: RecoveryCase, ctx: ScanContext | None, now: datetime | None = None) -> F.FeatureInput:
    now = now or datetime.utcnow()
    local = now + timedelta(minutes=settings.ml_local_utc_offset_minutes)
    _, dom, wd, frac = time_parts_from_datetime(local)
    n = cap = 0
    if ctx is not None:
        key = customer_key(case.customer_email, case.customer_contact)
        n, cap = ctx.customer_history(key, to_ts(case.failed_payment_created_at), case.payment_id)
    age = max((now - case.created_at).total_seconds() / 3600.0, 0.0) if case.created_at else 0.0
    return F.FeatureInput(reason=case.failure_reason_raw, method=case.method, amount=float(case.amount),
                          retry_count=int(case.retry_count), comms_sent=int(case.communications_sent), age_hours=age,
                          local_hour_frac=frac, day_of_month=dom, weekday=wd, cust_n=n, cust_captured=cap)


# ---------------------------------------------------------------------------
# 1. Risk scoring
# ---------------------------------------------------------------------------
@dataclass
class RiskResult:
    probability: float
    source: str                      # "ml" | "rules"
    version: str
    factors: list[dict] = field(default_factory=list)

    def factor_text(self) -> str:
        if not self.factors:
            return ""
        parts = [f"{f['factor']} ({f['detail']}) {f['effect'] * 100:+.0f} pts" for f in self.factors[:3]]
        return " Main drivers: " + "; ".join(parts) + "."


def assess_risk(db: Session, case: RecoveryCase, ctx: ScanContext | None) -> RiskResult:
    model = registry.get_risk_model() if ml_active() else None
    if model is not None:
        try:
            fi = feature_input(case, ctx)
            p = rules.guard_probability(model.predict(fi))
            if p is not None:
                factors = model.explain(fi)
                db.add(MLDecision(user_id=case.user_id, case_id=case.id, kind="risk", model_version=model.version,
                                  probability=p, features=json.dumps(F.row_to_dict(F.build_row(fi))),
                                  factors=json.dumps(factors)))
                return RiskResult(round(p, 4), "ml", model.version, factors)
        except Exception:
            log.exception("Risk model failed; falling back to rule-based score.")
    return RiskResult(rules.risk_assessment(case.category, case.retry_count), "rules", "rules-v1")


# ---------------------------------------------------------------------------
# 2. Retry timing (Thompson-sampling bandit)
# ---------------------------------------------------------------------------
@dataclass
class TimingChoice:
    delay: timedelta
    source: str                      # "bandit" | "rules"
    explanation: str
    context: str | None = None
    arm: float | None = None


def _fmt_hours(h: float) -> str:
    return f"{h * 60:.0f} min" if h < 1 else (f"{h:.0f}h" if h == int(h) else f"{h:.1f}h")


def choose_timing(db: Session, user: User, case: RecoveryCase, strategy: str) -> TimingChoice:
    legacy = rules.choose_timing(case.category)
    legacy_choice = TimingChoice(legacy, "rules", rules.timing_reason(case.category, legacy))
    if strategy != "retry" or not (ml_active() and settings.ml_bandit_enabled):
        return legacy_choice
    try:
        now = datetime.utcnow()
        remaining = ((case.recovery_window_expires_at - now).total_seconds() / 3600.0
                     if case.recovery_window_expires_at else settings.recovery_window_days * 24)
        arms = rules.allowed_delay_arms(settings.ml_bandit_arms_hours, case.retry_count,
                                        settings.recovery_cooldown_hours, remaining)
        if not arms:
            return legacy_choice
        bandit = ThompsonBandit(DBStore(db, user.id), settings.ml_bandit_prior_strength)
        ctx_key = context_key(case.failure_reason_raw, case.retry_count)
        ch = bandit.choose(ctx_key, arms)
        db.add(MLDecision(user_id=user.id, case_id=case.id, kind="timing", model_version="thompson-v1",
                          context_key=ctx_key, arm_hours=ch.arm, probability=ch.posterior_mean,
                          features=json.dumps({"retry_count": case.retry_count}), factors=json.dumps(ch.alternatives)))
        best = max(ch.alternatives, key=lambda a: a["posterior_mean"])
        why = (f"Thompson sampling over {len(arms)} allowed delays for '{ctx_key.split('|')[0].replace('_', ' ')}' "
               f"failures ({ctx_key.split('|')[1]} retry) picked {_fmt_hours(ch.arm)}: estimated retry success "
               f"{ch.posterior_mean * 100:.0f}% from {ch.observations:.0f} similar attempt(s). "
               f"Currently strongest on average: {_fmt_hours(best['arm_hours'])} ({best['posterior_mean'] * 100:.0f}%). "
               f"Bounded by the cooldown and recovery window.")
        return TimingChoice(timedelta(hours=ch.arm), "bandit", why, ctx_key, ch.arm)
    except Exception:
        log.exception("Timing bandit failed; using rule-based delay.")
        return legacy_choice


def mark_timing_executed(db: Session, case: RecoveryCase) -> None:
    db.flush()
    d = (db.query(MLDecision).filter_by(case_id=case.id, kind="timing", outcome=None)
         .order_by(MLDecision.created_at.desc()).first())
    if d is not None:
        d.executed = True


def record_retry_outcome(db: Session, case: RecoveryCase, success: bool) -> None:
    """Immediate-feedback path (Test Mode): the retry result is known right away,
    so it becomes the bandit's reward for the delay that preceded it."""
    db.flush()
    d = (db.query(MLDecision).filter_by(case_id=case.id, kind="timing", outcome=None)
         .order_by(MLDecision.created_at.desc()).first())
    if d is None:
        return
    d.executed, d.outcome, d.resolved_at = True, 1 if success else 0, datetime.utcnow()
    if d.context_key and d.arm_hours is not None:
        ThompsonBandit(DBStore(db, d.user_id), settings.ml_bandit_prior_strength).update(
            d.context_key, d.arm_hours, 1 if success else 0)


def sweep_outcomes(db: Session, user_id: str) -> int:
    """Resolve decisions whose case has reached a terminal state. Idempotent.
    risk decisions -> training labels; timing decisions that actually ran ->
    bandit rewards (never credited for retries that were never executed)."""
    if not ml_active():
        return 0
    db.flush()
    n = 0
    pending = db.query(MLDecision).filter(MLDecision.user_id == user_id, MLDecision.outcome.is_(None)).all()
    cases: dict[str, RecoveryCase | None] = {}
    for d in pending:
        if d.case_id not in cases:
            cases[d.case_id] = db.get(RecoveryCase, d.case_id)
        case = cases[d.case_id]
        if case is None:
            continue
        st = _status(case)
        if st in TERMINAL_POSITIVE:
            label = 1
        elif st in TERMINAL_NEGATIVE:
            label = 0
        elif st in TERMINAL_CENSORED:
            label = -1
        else:
            continue
        if d.kind == "timing" and not d.executed:
            label = -1
        d.outcome, d.resolved_at = label, datetime.utcnow()
        if d.kind == "timing" and label in (0, 1) and d.context_key and d.arm_hours is not None:
            ThompsonBandit(DBStore(db, user_id), settings.ml_bandit_prior_strength).update(d.context_key, d.arm_hours, label)
        n += 1
    return n


# ---------------------------------------------------------------------------
# 3. Anomaly detection: security holds + outage deferral
# ---------------------------------------------------------------------------
@dataclass
class Screening:
    hold: bool = False
    score: float = 0.0
    threshold: float = 0.0
    reasons: list[str] = field(default_factory=list)
    source: str = "none"
    alert_id: str | None = None


def screen_case(db: Session, user: User, case: RecoveryCase, ctx: ScanContext | None) -> Screening:
    if not (ml_active() and settings.ml_anomaly_enabled) or ctx is None:
        return Screening()
    try:
        key = customer_key(case.customer_email, case.customer_contact)
        if not key:
            return Screening()
        # A burst must be recognised from ANY payment inside it (even its first one, which looked
        # harmless when it happened), so the window is the hour centred on this payment.
        t_ref = to_ts(case.failed_payment_created_at)
        w = settings.ml_fraud_window_minutes * 60.0
        window = ctx.customer_window(key, t_ref + w / 2, w)
        day_f = ctx.customer_failures_since(key, t_ref + 43200.0, 86400.0)
        model = registry.get_anomaly_model()
        if model is not None:
            a = model.assess(window, day_f)
        else:
            f = A.velocity_features(window, day_f)
            hold = A.signature_rule(f) and f["n_failed"] >= settings.ml_fraud_min_failures
            a = A.FraudAssessment(hold, 1.0 if hold else 0.0, 0.5, f, [], "signature_rule")
        if not a.hold:
            return Screening(False, a.score, a.threshold, [], a.source)
        alert = _upsert_alert(db, user.id, "card_testing", key, a.score, "high",
                              {"case_id": case.id, "payment_id": case.payment_id, "features": a.features,
                               "reasons": a.reasons, "threshold": a.threshold, "detector": a.source})
        return Screening(True, a.score, a.threshold, a.reasons, a.source, alert.id)
    except Exception:
        log.exception("Security screening failed; continuing without it.")
        return Screening()


def _upsert_alert(db: Session, user_id: str, kind: str, subject: str, score: float, severity: str, details: dict) -> MLAlert:
    db.flush()
    now = datetime.utcnow()
    existing = (db.query(MLAlert).filter(MLAlert.user_id == user_id, MLAlert.kind == kind, MLAlert.subject == subject,
                                         MLAlert.status == "open").first())
    if existing:
        existing.last_seen_at, existing.score = now, score
        old = json.loads(existing.details or "{}")
        ids = set(old.get("case_ids", [])) | ({details["case_id"]} if details.get("case_id") else set())
        existing.details = json.dumps({**details, "case_ids": sorted(ids)})
        return existing
    alert = MLAlert(user_id=user_id, kind=kind, severity=severity, subject=subject, score=score, status="open",
                    details=json.dumps({**details, "case_ids": [details["case_id"]] if details.get("case_id") else []}))
    db.add(alert)
    db.flush()
    return alert


def sync_outage_alerts(db: Session, user: User, ctx: ScanContext | None) -> list[A.OutageSignal]:
    """Run the outage detector on the scan's payment snapshot and keep alerts in
    step: refresh active ones, open new ones, and resolve those that stayed
    quiet for 30 minutes (hysteresis avoids flapping)."""
    if not (ml_active() and settings.ml_anomaly_enabled) or ctx is None:
        return []
    try:
        db.flush()
        now = ctx.now
        sigs = A.detect_outages(ctx, to_ts(now))
        active = set()
        for s in sigs:
            active.add(s.method)
            _upsert_alert(db, user.id, "method_outage", s.method, s.z, "high" if s.rate >= 0.6 else "medium",
                          {"attempts": s.attempts, "failures": s.failures, "failure_rate": s.rate,
                           "baseline_rate": s.baseline_rate, "z": s.z, "infra_share": s.technical_share})
        for al in db.query(MLAlert).filter_by(user_id=user.id, kind="method_outage", status="open").all():
            if al.subject not in active and (now - al.last_seen_at) >= timedelta(minutes=30):
                al.status = "resolved"
        return sigs
    except Exception:
        log.exception("Outage detection failed; continuing without it.")
        return []


def active_outage(db: Session, user_id: str, method: str | None) -> MLAlert | None:
    if not (ml_active() and settings.ml_anomaly_enabled) or not method:
        return None
    db.flush()
    cutoff = datetime.utcnow() - timedelta(minutes=settings.ml_outage_alert_ttl_minutes)
    return (db.query(MLAlert).filter(MLAlert.user_id == user_id, MLAlert.kind == "method_outage",
                                     MLAlert.subject == method, MLAlert.status == "open",
                                     MLAlert.last_seen_at >= cutoff).first())


def deferrals_used(db: Session, case: RecoveryCase) -> int:
    db.flush()
    return db.query(RecoveryTraceStep).filter(RecoveryTraceStep.case_id == case.id,
                                              RecoveryTraceStep.decision.like("Retry deferred%")).count()


# ---------------------------------------------------------------------------
# Explanation payload for the API / UI
# ---------------------------------------------------------------------------
def explain_case(db: Session, case: RecoveryCase) -> dict:
    db.flush()
    risk = (db.query(MLDecision).filter_by(case_id=case.id, kind="risk")
            .order_by(MLDecision.created_at.desc()).first())
    timing = (db.query(MLDecision).filter_by(case_id=case.id, kind="timing")
              .order_by(MLDecision.created_at.desc()).first())
    alert = (db.query(MLAlert).filter(MLAlert.user_id == case.user_id, MLAlert.kind == "card_testing",
                                      MLAlert.details.like(f"%{case.id}%")).order_by(MLAlert.created_at.desc()).first())
    return {
        "risk": None if risk is None else {
            "probability": risk.probability, "model_version": risk.model_version,
            "factors": json.loads(risk.factors or "[]"), "scored_at": risk.created_at.isoformat()},
        "timing": None if timing is None else {
            "context": timing.context_key, "arm_hours": timing.arm_hours, "posterior_mean": timing.probability,
            "alternatives": json.loads(timing.factors or "[]"), "executed": timing.executed, "outcome": timing.outcome},
        "security": None if alert is None else {
            "alert_id": alert.id, "status": alert.status, "score": alert.score,
            "reasons": json.loads(alert.details or "{}").get("reasons", [])},
    }


def resolve_alerts_for_case(db: Session, case: RecoveryCase, status: str = "acknowledged") -> None:
    """Close card-testing alerts that referenced this case — but only once no OTHER case
    covered by the same alert is still on security hold."""
    db.flush()
    for al in (db.query(MLAlert).filter(MLAlert.user_id == case.user_id, MLAlert.kind == "card_testing",
                                        MLAlert.status == "open", MLAlert.details.like(f"%{case.id}%")).all()):
        ids = [i for i in json.loads(al.details or "{}").get("case_ids", []) if i != case.id]
        still_held = ids and db.query(RecoveryCase).filter(RecoveryCase.id.in_(ids), RecoveryCase.status == "security_hold").count()
        if not still_held:
            al.status = status


def shift_alerts(db: Session, user_id: str, delta: timedelta) -> None:
    """Test-Mode clock advance: age alerts along with everything else."""
    for al in db.query(MLAlert).filter_by(user_id=user_id).all():
        al.created_at -= delta
        al.last_seen_at -= delta
