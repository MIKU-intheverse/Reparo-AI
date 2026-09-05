import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import get_current_user
from app.database import get_db
from app.models import LiveWebhookEvent, RazorpayCredential, RecoveryCase, User
from app.recovery.engine import verify_live_event

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
settings = get_settings()


def _verify_signature(raw_body: bytes, signature: str) -> bool:
    if not settings.razorpay_webhook_secret:
        return False
    expected = hmac.new(settings.razorpay_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _summarize(event_type: str, payload: dict) -> tuple[str | None, str]:
    entity = event_type.split(".")[0] if event_type else "event"
    data = payload.get("payload", {}).get(entity, {}).get("entity", {})
    entity_id = data.get("id")
    amount = data.get("amount")
    amount_str = f"₹{amount / 100:.2f}" if isinstance(amount, (int, float)) else ""
    return entity_id, f"{event_type} {amount_str} {entity_id or ''}".strip()


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    Verifies the Razorpay webhook signature (Razorpay's documented
    HMAC-SHA256 scheme over the raw request body) before processing any
    event, per section 12 of the spec. Configure the same secret in the
    Razorpay dashboard and in RAZORPAY_WEBHOOK_SECRET. Unverified or
    duplicate events are dropped. Verified events are persisted to
    LiveWebhookEvent so the dashboard can show real-time activity without
    relying on polling alone.
    """
    raw_body = await request.body()

    if not x_razorpay_signature or not _verify_signature(raw_body, x_razorpay_signature):
        raise HTTPException(400, "Invalid webhook signature.")

    payload = await request.json()
    event_id = payload.get("id")
    event_type = payload.get("event", "unknown")

    if event_id and db.query(LiveWebhookEvent).filter_by(razorpay_event_id=event_id).first():
        return {"status": "duplicate_ignored"}

    entity_id, summary = _summarize(event_type, payload)


    account_key = payload.get("account_id")
    user_id = None
    if account_key:
        cred = db.query(RazorpayCredential).filter_by(key_id=account_key).first()
        if cred:
            user_id = cred.user_id

    db.add(LiveWebhookEvent(
        user_id=user_id, razorpay_event_id=event_id, event_type=event_type,
        entity_id=entity_id, summary=summary,
    ))
    db.commit()


    if entity_id:
        case = db.query(RecoveryCase).filter(
            (RecoveryCase.payment_id == entity_id) |
            (RecoveryCase.order_id == entity_id) |
            (RecoveryCase.payment_link_id == entity_id)
        ).first()
        if case and case.status in ("waiting", "retrying", "verifying", "failed"):
            verify_live_event(db, case, event_type, summary)

    return {"status": "received", "event": event_type}


@router.get("/recent")
def recent_events(limit: int = 20, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.environment != "live":
        return {"items": []}
    q = db.query(LiveWebhookEvent).filter(
        (LiveWebhookEvent.user_id == user.id) | (LiveWebhookEvent.user_id.is_(None))
    ).order_by(LiveWebhookEvent.received_at.desc()).limit(limit)
    return {"items": [
        {"id": e.id, "event_type": e.event_type, "entity_id": e.entity_id, "summary": e.summary,
         "received_at": e.received_at.isoformat()}
        for e in q.all()
    ]}
