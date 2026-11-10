"""
ML endpoints: model cards, offline evaluation, bandit state, anomaly alerts, a
what-if scorer, and Test-Mode simulation controls for demoing the detectors.
Everything is scoped to the authenticated user; nothing here changes how a real
(Live Mode) payment is handled.
"""
import json
from pathlib import Path
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import get_current_user
from app.database import get_db
from app.ml import evaluate as ml_eval
from app.ml import features as F
from app.ml import registry
from app.ml.bandit import DBStore, ThompsonBandit
from app.ml.episodes import COOLDOWN_H, WINDOW_H
from app.ml.world import METHOD_MIX, REASON_MIX, get_world
from app.models import BanditArm, MLAlert, MLDecision, User
from app.providers.factory import get_provider
from app.recovery import engine, rules

# Secure by default: EVERY ML endpoint requires an authenticated user (model cards included).
router = APIRouter(prefix="/api/ml", tags=["ml"], dependencies=[Depends(get_current_user)])
settings = get_settings()

_heavy_lock = threading.Lock()
_last_heavy: dict[str, float] = {}


def _throttle(name: str, seconds: float):
    now = time.time()
    if now - _last_heavy.get(name, 0.0) < seconds:
        raise HTTPException(429, f"Please wait {seconds:.0f}s between runs of this operation.")
    _last_heavy[name] = now


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    model = registry.get_risk_model()
    anomaly = registry.get_anomaly_model()
    decisions = db.query(MLDecision).filter_by(user_id=user.id)
    resolved = decisions.filter(MLDecision.outcome.in_([0, 1])).count()
    return {
        "ml_enabled": settings.ml_enabled,
        "risk_model": None if model is None else {"version": model.version, "trained_at": model.meta["trained_at"],
                                                  "calibration": model.meta["calibration"]},
        "anomaly_model": None if anomaly is None else {"version": anomaly.version},
        "bandit_enabled": settings.ml_bandit_enabled,
        "anomaly_enabled": settings.ml_anomaly_enabled,
        "decisions_logged": decisions.count(),
        "decisions_resolved": resolved,
        "open_alerts": db.query(MLAlert).filter_by(user_id=user.id, status="open").count(),
        "sandbox_world": settings.ml_sandbox_world,
        "environment": user.environment,
    }


@router.get("/model")
def model_card():
    model = registry.get_risk_model()
    if model is None:
        raise HTTPException(503, "Risk model is not available; the engine is using rule-based scoring.")
    return model.card


@router.get("/anomaly-model")
def anomaly_card():
    card = registry.read_json("anomaly_card.json")
    if card is None:
        raise HTTPException(404, "Anomaly model card not found. Run `python -m app.ml.anomaly`.")
    return card


@router.get("/evaluation")
def evaluation():
    report = registry.read_json("eval_report_latest.json") or registry.read_json("eval_report.json")
    if report is None:
        raise HTTPException(404, "No evaluation report yet. Run `python -m app.ml.evaluate` or POST /api/ml/evaluation/run.")
    return report


class EvalRequest(BaseModel):
    n_cases: int = Field(default=2000, ge=500, le=8000)
    seed: int = Field(default=2024, ge=0, le=10_000_000)
    approvals_per_day: int = Field(default=8, ge=1, le=100)


@router.post("/evaluation/run")
def run_evaluation(req: EvalRequest, user: User = Depends(get_current_user)):
    """Re-run the offline policy comparison with chosen size / seed / reviewer capacity."""
    if not _heavy_lock.acquire(blocking=False):
        raise HTTPException(409, "An evaluation is already running.")
    try:
        _throttle("eval", 10)
        report = ml_eval.run_evaluation(n_cases=req.n_cases, seed=req.seed, write=False, include_sweep=True,
                                        approvals_per_day=req.approvals_per_day)
        registry.write_json("eval_report_latest.json", report)
        return report
    finally:
        _heavy_lock.release()


@router.get("/bandit")
def bandit_state(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Learned retry-delay posteriors for this merchant, per failure-reason context."""
    bandit = ThompsonBandit(DBStore(db, user.id), settings.ml_bandit_prior_strength)
    arms = sorted(settings.ml_bandit_arms_hours)
    contexts = sorted({r.context_key for r in db.query(BanditArm).filter_by(user_id=user.id).all()})
    out = []
    for ctx in contexts:
        later = ctx.endswith("later")
        allowed = rules.allowed_delay_arms(arms, 1 if later else 0, COOLDOWN_H, WINDOW_H)
        row = {"context": ctx, "reason": ctx.split("|")[0], "stage": ctx.split("|")[1], "arms": []}
        for a in allowed:
            s, f = bandit.store.get(ctx, a)
            row["arms"].append({"arm_hours": a, "posterior_mean": round(bandit.mean(ctx, a), 4), "successes": s,
                                "failures": f, "observations": s + f})
        row["total_observations"] = sum(x["observations"] for x in row["arms"])
        # Only name a favourite once there is some evidence behind it.
        row["best_arm_hours"] = (max(row["arms"], key=lambda x: x["posterior_mean"])["arm_hours"]
                                 if row["total_observations"] >= 10 else None)
        if user.environment == "test":
            truth = ml_eval.true_arm_success(ctx.split("|")[0], _sandbox_params(), k=1 if later else 0, n=150)
            row["sandbox_truth"] = {str(a): round(truth[a], 3) for a in allowed}
            row["sandbox_best_arm_hours"] = max(allowed, key=lambda a: truth[a])
        out.append(row)
    return {"arms_hours": arms, "prior_strength": settings.ml_bandit_prior_strength, "contexts": out,
            "cooldown_hours": COOLDOWN_H, "window_hours": WINDOW_H, "sandbox_world": settings.ml_sandbox_world}


def _sandbox_params():
    return get_world(settings.ml_sandbox_world)


def _alert_row(a: MLAlert) -> dict:
    return {"id": a.id, "kind": a.kind, "severity": a.severity, "subject": a.subject, "score": round(a.score, 3),
            "status": a.status, "details": json.loads(a.details or "{}"), "created_at": a.created_at.isoformat(),
            "last_seen_at": a.last_seen_at.isoformat()}


@router.get("/alerts")
def alerts(status: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(MLAlert).filter_by(user_id=user.id)
    if status and status != "all":
        q = q.filter_by(status=status)
    rows = q.order_by(MLAlert.last_seen_at.desc()).limit(100).all()
    return {"items": [_alert_row(a) for a in rows], "count": len(rows)}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    a = db.query(MLAlert).filter_by(id=alert_id, user_id=user.id).first()
    if not a:
        raise HTTPException(404, "Alert not found.")
    a.status = "acknowledged"
    db.commit()
    return _alert_row(a)


class ScoreRequest(BaseModel):
    reason: str = "insufficient_funds"
    method: str = "upi"
    amount: float = Field(default=2000, gt=0, le=10_000_000)
    retry_count: int = Field(default=0, ge=0, le=10)
    comms_sent: int = Field(default=0, ge=0, le=10)
    age_hours: float = Field(default=0, ge=0, le=720)
    hour: int = Field(default=14, ge=0, le=23)
    day_of_month: int = Field(default=15, ge=1, le=31)
    weekend: bool = False
    customer_payments: int = Field(default=6, ge=0, le=10_000)
    customer_success_rate: float = Field(default=0.8, ge=0, le=1)


@router.post("/score")
def score(req: ScoreRequest, user: User = Depends(get_current_user)):
    """What-if scorer: price a hypothetical failed payment with the live model,
    side by side with the legacy rule-based score, plus per-factor attribution."""
    model = registry.get_risk_model()
    if model is None:
        raise HTTPException(503, "Risk model is not available.")
    captured = round(req.customer_payments * req.customer_success_rate)
    fi = F.FeatureInput(reason=req.reason, method=req.method, amount=req.amount, retry_count=req.retry_count,
                        comms_sent=req.comms_sent, age_hours=req.age_hours, local_hour_frac=float(req.hour),
                        day_of_month=req.day_of_month, weekday=5 if req.weekend else 2,
                        cust_n=req.customer_payments, cust_captured=captured)
    p = rules.guard_probability(model.predict(fi))
    category = rules.classify_failure(req.reason)
    return {"probability": p, "expected_value": round(req.amount * p, 2), "category": category,
            "rules_baseline_probability": rules.risk_assessment(category, req.retry_count),
            "factors": model.explain(fi, top_k=8), "model_version": model.version}


class IncidentRequest(BaseModel):
    kind: str = Field(pattern="^(card_testing|outage)$")
    method: str = Field(default="upi", pattern="^(card|upi|netbanking|wallet)$")


@router.post("/simulate/incident")
def simulate_incident(req: IncidentRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.environment != "test":
        raise HTTPException(403, "Incident simulation is only available in Test Mode.")
    return get_provider(user, db).inject_incident(req.kind, req.method)


class BatchRequest(BaseModel):
    count: int = Field(default=40, ge=1, le=200)


@router.post("/simulate/failures")
def simulate_failures(req: BatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.environment != "test":
        raise HTTPException(403, "Failure simulation is only available in Test Mode.")
    return get_provider(user, db).create_failed_batch(req.count)


@router.post("/retrain")
def retrain(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Retrain the risk model on synthetic data plus this merchant's resolved outcomes
    (the ml_decisions table). Single-tenant assumption: the model is process-wide."""
    from app.ml.train import load_real_rows, train_and_save
    if not _heavy_lock.acquire(blocking=False):
        raise HTTPException(409, "A training / evaluation job is already running.")
    try:
        _throttle("retrain", 30)
        real = load_real_rows(db)
        model = train_and_save(n_cases=12000, seed=int(time.time()) % 10_000, real_rows=real, quiet=True)
        return {"version": model.version, "real_rows_available": 0 if real is None else int(len(real[1])),
                "metrics": model.meta["metrics"]["gbm_calibrated"], "real_data": model.meta["real_data"]}
    finally:
        _heavy_lock.release()


class LearnRequest(BaseModel):
    cases: int = Field(default=60, ge=10, le=150)
    rounds: int = Field(default=5, ge=1, le=8)
    hours_per_round: float = Field(default=26.0, ge=6, le=48)


@router.post("/simulate/learn")
def simulate_learning(req: LearnRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One-click demo of online learning (Test Mode): generate failures, then alternate
    'run scan' and 'advance the clock' so scheduled retries come due and the bandit
    observes outcomes. Respects every normal guardrail; it just compresses time."""
    if user.environment != "test":
        raise HTTPException(403, "The learning demo is only available in Test Mode.")
    if req.rounds * req.hours_per_round > 150:
        raise HTTPException(422, "rounds x hours_per_round must stay within the 7-day recovery window (<= 150h).")
    provider = get_provider(user, db)
    provider.create_failed_batch(req.cases)
    for _ in range(req.rounds):
        engine.run_scan(user, db)
        engine.advance_clock(user, db, req.hours_per_round)
    engine.run_scan(user, db)
    m = engine.get_metrics(user, db)
    return {"cases_generated": req.cases, "rounds": req.rounds, "simulated_hours": req.rounds * req.hours_per_round,
            "recovered_amount": m["recovered_amount"], "recovery_rate": m["recovery_rate"],
            "security_holds": m["security_holds"], "awaiting_approval": m["awaiting_approval"]}


_DATA_DIR = Path(__file__).resolve().parent.parent / "ml" / "data"


@router.get("/realdata")
def realdata():
    """Result of the real-data checks (UCI Online Retail): amount-shape sanity check and detector stress tests."""
    report = registry.read_json("realdata_report.json")
    if report is None:
        raise HTTPException(404, "No real-data report yet. Run `python -m app.ml.realdata`.")
    return report


@router.get("/benchmarks")
def benchmarks():
    """Published industry figures next to what the simulator produces. Vendor-published, unaudited,
    mostly subscription billing — reality-check targets, never training data."""
    published = json.loads((_DATA_DIR / "industry_benchmarks.json").read_text())
    report = registry.read_json("eval_report_latest.json") or registry.read_json("eval_report.json") or {}
    sim_recovery = {}
    for w in ("base", "shifted", "conservative"):
        pol = {p["policy"]: p["recovery_rate"] for p in report.get(w, {}).get("policies", [])}
        if pol:
            sim_recovery[w] = {"do_nothing": pol.get("do_nothing"), "rules": pol.get("rules"), "ml_full": pol.get("ml_full")}
    mix = {r: sum(METHOD_MIX[m] * REASON_MIX[m].get(r, 0.0) for m in METHOD_MIX) for r in ("insufficient_funds",)}
    return {"published": published, "simulated": {"recovery_rate_by_world": sim_recovery,
                                                  "insufficient_funds_share": round(mix["insufficient_funds"], 3)}}
