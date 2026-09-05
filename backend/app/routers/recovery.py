from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import get_current_user
from app.database import get_db
from app.models import RecoveryCase, User
from app.recovery import engine

router = APIRouter(prefix="/api/recovery", tags=["recovery"])
settings = get_settings()


def _case_row(c: RecoveryCase) -> dict:
    return {
        "id": c.id, "payment_id": c.payment_id, "order_id": c.order_id, "amount": c.amount, "currency": c.currency,
        "customer_email": c.customer_email, "customer_contact": c.customer_contact, "method": c.method,
        "failure_reason_raw": c.failure_reason_raw, "category": c.category, "status": c.status,
        "recovery_probability": c.recovery_probability, "expected_recovery_value": c.expected_recovery_value,
        "recommended_action": c.recommended_action, "retry_count": c.retry_count, "max_retries": c.max_retries,
        "communications_sent": c.communications_sent, "max_communications": c.max_communications,
        "next_action_at": c.next_action_at.isoformat() if c.next_action_at else None,
        "last_action_at": c.last_action_at.isoformat() if c.last_action_at else None,
        "recovery_window_expires_at": c.recovery_window_expires_at.isoformat() if c.recovery_window_expires_at else None,
        "recovered_amount": c.recovered_amount, "payment_link_url": c.payment_link_url,
        "prepared_message": c.prepared_message,
        "failed_payment_created_at": c.failed_payment_created_at.isoformat(),
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
    }


def _trace_row(t) -> dict:
    return {"id": t.id, "agent": t.agent, "decision": t.decision, "reason": t.reason,
            "actor": t.actor, "created_at": t.created_at.isoformat()}


def _comm_row(m) -> dict:
    return {"id": m.id, "message_type": m.message_type, "channel": m.channel, "to_address": m.to_address,
            "content": m.content, "status": m.status, "created_at": m.created_at.isoformat()}


@router.post("/scan")
def scan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Detector step — pulls failed payments from the active environment and
    opens/advances recovery cases. Safe to call repeatedly (idempotent per
    payment id)."""
    cases = engine.run_scan(user, db)
    return {"new_or_updated_cases": len(cases), "case_ids": [c.id for c in cases]}


@router.get("/cases")
def list_cases(status: str | None = None, priority: bool = False,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(RecoveryCase).filter_by(user_id=user.id)
    if status and status != "all":
        q = q.filter_by(status=status)
    cases = q.order_by(RecoveryCase.updated_at.desc()).all()
    if priority:
        cases = sorted(cases, key=lambda c: c.expected_recovery_value, reverse=True)
    return {"items": [_case_row(c) for c in cases], "count": len(cases)}


def _get_case(case_id: str, user: User, db: Session) -> RecoveryCase:
    case = db.query(RecoveryCase).filter_by(id=case_id, user_id=user.id).first()
    if not case:
        raise HTTPException(404, "Recovery case not found.")
    return case


@router.get("/cases/{case_id}")
def case_detail(case_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = _get_case(case_id, user, db)
    return {**_case_row(case), "trace": [_trace_row(t) for t in case.trace],
            "communications": [_comm_row(m) for m in case.communications]}


class RejectPayload(BaseModel):
    reason: str = ""


@router.post("/cases/{case_id}/approve")
def approve(case_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = _get_case(case_id, user, db)
    try:
        engine.approve_case(user, db, case, actor=user.email)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {**_case_row(case), "trace": [_trace_row(t) for t in case.trace], "communications": [_comm_row(m) for m in case.communications]}


@router.post("/cases/{case_id}/reject")
def reject(case_id: str, payload: RejectPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = _get_case(case_id, user, db)
    try:
        engine.reject_case(user, db, case, actor=user.email, reason=payload.reason)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {**_case_row(case), "trace": [_trace_row(t) for t in case.trace], "communications": [_comm_row(m) for m in case.communications]}


@router.get("/metrics")
def metrics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return engine.get_metrics(user, db)


@router.get("/config")
def config():
    """Bounded rules exposed read-only so the UI can display them (e.g. 'Retry 2/3')
    without duplicating the numbers on the frontend."""
    return {
        "max_retries": settings.recovery_max_retries,
        "max_communications": settings.recovery_max_communications,
        "cooldown_hours": settings.recovery_cooldown_hours,
        "window_days": settings.recovery_window_days,
        "soft_decline_retry_hours": settings.recovery_soft_decline_retry_hours,
        "technical_retry_hours": settings.recovery_technical_retry_hours,
        "hard_decline_retry_hours": settings.recovery_hard_decline_retry_hours,
    }
