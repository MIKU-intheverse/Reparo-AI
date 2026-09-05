from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.email import send_otp_email
from app.core.security import create_access_token, generate_otp, hash_password, verify_password
from app.database import get_db
from app.models import OtpCode, User
from app.schemas import SignIn, SignupComplete, SignupStart, TokenOut, VerifyOtp

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup/start")
def signup_start(payload: SignupStart, db: Session = Depends(get_db)):
    if payload.environment not in ("live", "test"):
        raise HTTPException(400, "environment must be 'live' or 'test'")
    if db.query(User).filter_by(email=payload.email).first():
        raise HTTPException(409, "An account with this email already exists.")

    code = generate_otp()
    otp = OtpCode(
        email=payload.email,
        code_hash=hash_password(code),
        purpose=f"signup:{payload.environment}",
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.add(otp)
    db.commit()
    send_otp_email(payload.email, code, purpose="signup")
    return {"message": "Verification code sent to your email."}


@router.post("/signup/verify")
def signup_verify(payload: VerifyOtp, db: Session = Depends(get_db)):
    otp = (
        db.query(OtpCode)
        .filter(OtpCode.email == payload.email, OtpCode.consumed == False)  # noqa: E712
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp or otp.expires_at < datetime.utcnow():
        raise HTTPException(400, "Code expired. Please request a new one.")
    if otp.attempts >= 5:
        raise HTTPException(429, "Too many attempts. Please request a new code.")

    otp.attempts += 1
    if not verify_password(payload.code, otp.code_hash):
        db.commit()
        raise HTTPException(400, "Incorrect verification code.")

    otp.consumed = True
    db.commit()
    return {"verified": True}


@router.post("/signup/complete", response_model=TokenOut)
def signup_complete(payload: SignupComplete, db: Session = Depends(get_db)):
    otp = (
        db.query(OtpCode)
        .filter(OtpCode.email == payload.email, OtpCode.consumed == True)  # noqa: E712
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp:
        raise HTTPException(400, "Please verify your email with the OTP first.")
    if db.query(User).filter_by(email=payload.email).first():
        raise HTTPException(409, "An account with this email already exists.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        email_verified=True,
        environment=payload.environment,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.environment)
    return TokenOut(access_token=token, environment=user.environment, email=user.email)


@router.post("/signin", response_model=TokenOut)
def signin(payload: SignIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    token = create_access_token(user.id, user.environment)
    return TokenOut(access_token=token, environment=user.environment, email=user.email)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"email": user.email, "environment": user.environment, "email_verified": user.email_verified}
