from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret, encrypt_secret, mask_key_id
from app.core.deps import get_current_user
from app.database import get_db
from app.models import RazorpayCredential, User
from app.providers.razorpay_provider import RazorpayAPIError, RazorpayProvider
from app.schemas import ConnectionStatus, ConnectRazorpay

router = APIRouter(prefix="/api/razorpay", tags=["razorpay"])


def _require_live(user: User):
    if user.environment != "live":
        raise HTTPException(400, "Razorpay connection only applies to Razorpay Client / Live Mode accounts.")


@router.get("/status", response_model=ConnectionStatus)
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.environment != "live":
        return ConnectionStatus(connected=False, environment=user.environment, status="not_applicable")
    cred = db.query(RazorpayCredential).filter_by(user_id=user.id).first()
    if not cred:
        return ConnectionStatus(connected=False, environment="live", status="disconnected")
    return ConnectionStatus(
        connected=cred.status == "connected",
        key_id=mask_key_id(cred.key_id),
        environment="live",
        status=cred.status,
        last_synced_at=cred.last_synced_at,
    )


@router.post("/connect", response_model=ConnectionStatus)
def connect(payload: ConnectRazorpay, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Validates credentials against the real Razorpay API before persisting
    anything (spec section 5/28-Test1/Test2). The Key Secret is encrypted
    at rest immediately and is never echoed back in this response.
    """
    _require_live(user)

    try:
        provider = RazorpayProvider(payload.key_id, payload.key_secret)
        provider.test_connection()
    except RazorpayAPIError as e:
        raise HTTPException(e.status_code if e.status_code in (400, 401) else 502,
                             f"Connection failed. {e.message}")

    cred = db.query(RazorpayCredential).filter_by(user_id=user.id).first()
    if not cred:
        cred = RazorpayCredential(user_id=user.id, key_id=payload.key_id,
                                   key_secret_encrypted=encrypt_secret(payload.key_secret))
        db.add(cred)
    else:
        cred.key_id = payload.key_id
        cred.key_secret_encrypted = encrypt_secret(payload.key_secret)

    cred.status = "connected"
    cred.last_synced_at = datetime.utcnow()
    db.commit()

    return ConnectionStatus(connected=True, key_id=mask_key_id(cred.key_id), environment="live",
                             status="connected", last_synced_at=cred.last_synced_at)


@router.post("/test-connection", response_model=ConnectionStatus)
def test_connection(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_live(user)
    cred = db.query(RazorpayCredential).filter_by(user_id=user.id).first()
    if not cred:
        raise HTTPException(400, "No Razorpay connection on file yet.")
    try:
        secret = decrypt_secret(cred.key_secret_encrypted)
        RazorpayProvider(cred.key_id, secret).test_connection()
        cred.status = "connected"
        cred.last_synced_at = datetime.utcnow()
    except RazorpayAPIError as e:
        cred.status = "error"
        db.commit()
        raise HTTPException(502, f"Razorpay temporarily unavailable or credentials invalid. {e.message}")
    db.commit()
    return ConnectionStatus(connected=True, key_id=mask_key_id(cred.key_id), environment="live",
                             status="connected", last_synced_at=cred.last_synced_at)


@router.post("/disconnect")
def disconnect(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_live(user)
    cred = db.query(RazorpayCredential).filter_by(user_id=user.id).first()
    if cred:
        db.delete(cred)
        db.commit()
    return {"disconnected": True}
