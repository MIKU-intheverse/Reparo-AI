from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret
from app.models import RazorpayCredential, User
from app.providers.razorpay_provider import RazorpayProvider
from app.providers.simulation_provider import SimulationProvider


def get_provider(user: User, db: Session):
    """
    Every data-bearing request goes through here. This is the single
    enforcement point for Live/Test isolation: a `test` account can never
    construct a RazorpayProvider, and a `live` account can never fall back
    to simulated data.
    """
    if user.environment == "test":
        return SimulationProvider(db, user.id)


    cred = db.query(RazorpayCredential).filter_by(user_id=user.id).first()
    if not cred or cred.status != "connected":
        raise HTTPException(
            status_code=428,
            detail="Razorpay is not connected yet. Connect your Razorpay account in Settings to view live data.",
        )
    secret = decrypt_secret(cred.key_secret_encrypted)
    return RazorpayProvider(cred.key_id, secret)
