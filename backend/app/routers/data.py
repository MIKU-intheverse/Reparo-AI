from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import LiveWebhookEvent, SimEvent, User
from app.providers.factory import get_provider
from app.providers.razorpay_provider import RazorpayAPIError

router = APIRouter(prefix="/api", tags=["data"])


def _provider(user: User, db: Session):
    try:
        return get_provider(user, db)
    except RazorpayAPIError as e:
        raise HTTPException(e.status_code, e.message)


@router.get("/payments")
def payments(limit: int = 20, skip: int = 0, status: str | None = None,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _provider(user, db).get_payments(limit=limit, skip=skip, status=status)


@router.get("/payments/{payment_id}")
def payment(payment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _provider(user, db).get_payment(payment_id)
    if not p:
        raise HTTPException(404, "Payment not found.")
    return p


@router.get("/orders")
def orders(limit: int = 20, skip: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _provider(user, db).get_orders(limit=limit, skip=skip)


@router.get("/refunds")
def refunds(limit: int = 20, skip: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _provider(user, db).get_refunds(limit=limit, skip=skip)


@router.get("/customers")
def customers(limit: int = 20, skip: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _provider(user, db).get_customers(limit=limit, skip=skip)


@router.get("/settlements")
def settlements(limit: int = 20, skip: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _provider(user, db).get_settlements(limit=limit, skip=skip)


@router.get("/disputes")
def disputes(limit: int = 20, skip: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _provider(user, db).get_disputes(limit=limit, skip=skip)


@router.get("/analytics")
def analytics(days: int = 14, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _provider(user, db).get_analytics(days=days)


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = 20,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _provider(user, db).search_transactions(q, limit=limit)


@router.get("/activity")
def activity(limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Unified recent-activity feed: Test Mode simulation events, or
    Live Mode webhook events received from Razorpay."""
    if user.environment == "test":
        rows = db.query(SimEvent).filter_by(user_id=user.id).order_by(SimEvent.created_at.desc()).limit(limit).all()
        return {"items": [{"id": r.id, "kind": r.kind, "message": r.message, "created_at": r.created_at.isoformat()}
                           for r in rows]}
    rows = db.query(LiveWebhookEvent).filter(
        (LiveWebhookEvent.user_id == user.id) | (LiveWebhookEvent.user_id.is_(None))
    ).order_by(LiveWebhookEvent.received_at.desc()).limit(limit).all()
    return {"items": [{"id": r.id, "kind": r.event_type, "message": r.summary, "created_at": r.received_at.isoformat()}
                       for r in rows]}


@router.post("/simulate/payment")
def simulate_payment(amount: float | None = None, method: str | None = None, should_fail: bool | None = None,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Test-Mode-only action: creates a stateful simulated payment so the
    sandbox behaves like a live operational environment, not static cards."""
    if user.environment != "test":
        raise HTTPException(400, "Simulated actions are only available in Test Mode.")
    return _provider(user, db).create_test_payment(amount=amount, method=method, should_fail=should_fail)
