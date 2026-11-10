import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Environment(str, enum.Enum):
    live = "live"
    test = "test"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)


    environment: Mapped[str] = mapped_column(Enum(Environment), default=Environment.test)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    credential: Mapped["RazorpayCredential"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, index=True)
    code_hash: Mapped[str] = mapped_column(String)
    purpose: Mapped[str] = mapped_column(String, default="signup")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RazorpayCredential(Base):
    """
    Stores a user's Razorpay Live connection. key_secret_encrypted is
    Fernet-encrypted at rest with app.core.crypto and is NEVER returned by
    any API response — only key_id (masked) and status fields are.
    """

    __tablename__ = "razorpay_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    key_id: Mapped[str] = mapped_column(String)
    key_secret_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="disconnected")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="credential")


class SimCustomer(Base):
    __tablename__ = "sim_customers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    contact: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SimOrder(Base):
    __tablename__ = "sim_orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="INR")
    status: Mapped[str] = mapped_column(String, default="created")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SimPayment(Base):
    __tablename__ = "sim_payments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    order_id: Mapped[str] = mapped_column(String, ForeignKey("sim_orders.id"))
    customer_id: Mapped[str] = mapped_column(String, ForeignKey("sim_customers.id"))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="INR")
    method: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    captured: Mapped[bool] = mapped_column(Boolean, default=False)
    refund_status: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String)
    contact: Mapped[str] = mapped_column(String)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SimRefund(Base):
    __tablename__ = "sim_refunds"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    payment_id: Mapped[str] = mapped_column(String, ForeignKey("sim_payments.id"))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="processed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SimEvent(Base):
    """Operational event log that both the dashboard activity feed and the
    AI agent's get_dashboard_metrics/search tools can draw on."""

    __tablename__ = "sim_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SimSettlement(Base):
    __tablename__ = "sim_settlements"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="processed")
    settled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SimDispute(Base):
    __tablename__ = "sim_disputes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    payment_id: Mapped[str] = mapped_column(String, ForeignKey("sim_payments.id"))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String, default="open")
    reason: Mapped[str] = mapped_column(String, default="goods_or_services_not_provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LiveWebhookEvent(Base):
    __tablename__ = "live_webhook_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)


    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    razorpay_event_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(String)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RecoveryStatus(str, enum.Enum):
    failed = "failed"
    analyzing = "analyzing"
    pending_approval = "pending_approval"
    approved = "approved"
    waiting = "waiting"
    retrying = "retrying"
    verifying = "verifying"
    recovered = "recovered"
    rejected = "rejected"
    suppressed = "suppressed"
    exhausted = "exhausted"
    expired = "expired"
    manual_review = "manual_review"
    security_hold = "security_hold"


class FailureCategory(str, enum.Enum):
    soft_decline = "soft_decline"
    technical = "technical"
    hard_decline = "hard_decline"
    unknown = "unknown"


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String)
    payment_id: Mapped[str] = mapped_column(String, index=True)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)

    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="INR")
    customer_email: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_contact: Mapped[str | None] = mapped_column(String, nullable=True)
    method: Mapped[str | None] = mapped_column(String, nullable=True)

    failure_reason_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str] = mapped_column(Enum(FailureCategory), default=FailureCategory.unknown)
    status: Mapped[str] = mapped_column(Enum(RecoveryStatus), default=RecoveryStatus.failed, index=True)

    recovery_probability: Mapped[float] = mapped_column(Float, default=0.0)
    expected_recovery_value: Mapped[float] = mapped_column(Float, default=0.0)
    recommended_action: Mapped[str] = mapped_column(String, default="none")
    prepared_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    communications_sent: Mapped[int] = mapped_column(Integer, default=0)
    max_communications: Mapped[int] = mapped_column(Integer, default=3)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recovery_window_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    recovered_amount: Mapped[float] = mapped_column(Float, default=0.0)
    payment_link_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payment_link_url: Mapped[str | None] = mapped_column(String, nullable=True)

    failed_payment_created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    trace: Mapped[list["RecoveryTraceStep"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="RecoveryTraceStep.created_at"
    )
    communications: Mapped[list["RecoveryCommunication"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="RecoveryCommunication.created_at"
    )


class RecoveryTraceStep(Base):
    __tablename__ = "recovery_trace_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    agent: Mapped[str] = mapped_column(String)

    decision: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["RecoveryCase"] = relationship(back_populates="trace")


class RecoveryCommunication(Base):
    """
    One row per customer-facing message the recovery pipeline drafts or
    sends — the spec's requirement to track message generated / queued /
    sent / delivery status / timestamp / type / case id, independent of the
    coarser-grained RecoveryTraceStep audit log.
    """
    __tablename__ = "recovery_communications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(ForeignKey("recovery_cases.id"), index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)

    message_type: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String, default="email")
    to_address: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="generated")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["RecoveryCase"] = relationship(back_populates="communications")


class MLDecision(Base):
    """
    Feature store + decision log for the ML layer. One row per model decision
    (kind="risk": recovery-probability scoring; kind="timing": retry-delay arm
    chosen by the bandit). `outcome` is filled in later (1 = recovered, 0 = not,
    -1 = censored / unknown), which is what closes the learning loop: resolved
    rows are the training data for retraining and the reward stream for the
    bandit. Features are stored as JSON exactly as the model saw them, so
    every score can be reproduced and audited.
    """
    __tablename__ = "ml_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    model_version: Mapped[str] = mapped_column(String, default="rules")
    context_key: Mapped[str | None] = mapped_column(String, nullable=True)
    arm_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    features: Mapped[str] = mapped_column(Text, default="{}")
    factors: Mapped[str] = mapped_column(Text, default="[]")
    executed: Mapped[bool] = mapped_column(Boolean, default=False)   # timing decisions: did the retry actually run?
    outcome: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BanditArm(Base):
    """Beta(successes + prior, failures + prior) posterior for one
    (context, retry-delay) pair of the Thompson-sampling timing bandit."""
    __tablename__ = "bandit_arms"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    context_key: Mapped[str] = mapped_column(String, index=True)
    arm_hours: Mapped[float] = mapped_column(Float)
    successes: Mapped[float] = mapped_column(Float, default=0.0)
    failures: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MLAlert(Base):
    """Anomaly-detection output: card-testing / velocity anomalies per
    customer and failure-rate spikes (suspected outages) per payment method."""
    __tablename__ = "ml_alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)           # card_testing | method_outage
    severity: Mapped[str] = mapped_column(String, default="medium")
    subject: Mapped[str] = mapped_column(String)        # customer key or payment method
    score: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String, default="open")   # open | acknowledged | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
