"""
Deterministic business rules for the recovery pipeline. These are the
safety-critical boundaries called out in spec sections 7, 8, and 18:
classification, strategy, timing, and stopping rules are ALL decided here,
by plain code — never by the LLM. The LLM (app/core/llm.py) is only ever
used downstream of these decisions, to explain them in prose or draft a
customer-facing message. It cannot change a category, raise MAX_RETRIES, or
approve its own action.
"""
from datetime import datetime, timedelta

from app.config import get_settings

settings = get_settings()

SOFT_DECLINE_REASONS = {
    "insufficient_funds", "insufficient balance", "bank_timeout", "issuer_unavailable",
    "issuer temporarily unavailable", "risk_check_failed", "authentication_failed",
}
TECHNICAL_REASONS = {
    "gateway_timeout", "network_failure", "otp_timeout", "otp expired", "server_error", "timeout",
}
HARD_DECLINE_REASONS = {
    "card_declined", "expired_card", "invalid_card", "account_closed", "do_not_honor",
    "restricted_card", "invalid card", "card expired",
}


def classify_failure(reason: str | None) -> str:
    """Classifier step. Pure string-matching against known Razorpay/PSP error
    codes — deliberately simple and auditable rather than ML-based, so a
    reviewer can always see exactly why a case landed in a bucket."""
    if not reason:
        return "unknown"
    r = reason.lower().strip()
    if r in SOFT_DECLINE_REASONS or "insufficient" in r or "issuer" in r:
        return "soft_decline"
    if r in TECHNICAL_REASONS or "timeout" in r or "network" in r or "gateway" in r:
        return "technical"
    if r in HARD_DECLINE_REASONS or "declined" in r or "expired" in r or "invalid" in r or "closed" in r:
        return "hard_decline"
    return "unknown"


def risk_assessment(category: str, retry_count: int) -> float:
    """Risk/recoverability score in [0, 1], deterministic. A real deployment
    could swap this for a trained model; the interface stays the same."""
    base = {"soft_decline": 0.62, "technical": 0.71, "hard_decline": 0.22, "unknown": 0.35}.get(category, 0.3)

    decay = 0.15 * retry_count
    return max(0.03, round(base - decay, 2))


def choose_strategy(category: str, retry_count: int) -> str:
    """Strategy step. retry_count is already bounded-checked by the caller
    before this is invoked for a *new* retry — see is_within_bounds()."""
    if category == "soft_decline":
        return "retry"
    if category == "technical":
        return "retry"
    if category == "hard_decline":
        return "request_new_method"
    return "manual"


def choose_timing(category: str) -> timedelta:
    """Timing step. Hours are configurable via RECOVERY_*_RETRY_HOURS env
    vars, not hardcoded throughout the codebase (spec section 8)."""
    hours = {
        "soft_decline": settings.recovery_soft_decline_retry_hours,
        "technical": settings.recovery_technical_retry_hours,
        "hard_decline": settings.recovery_hard_decline_retry_hours,
    }.get(category, 4.0)
    return timedelta(hours=hours)


def timing_reason(category: str, delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if category == "soft_decline":
        return (f"Insufficient-funds-type failures are more likely to recover after the customer's "
                f"balance is replenished — waiting {hours:.1f}h before retrying.")
    if category == "technical":
        return f"Transient technical failure — retrying soon ({hours * 60:.0f} min) while the issue is likely resolved."
    if category == "hard_decline":
        return "Hard decline is unlikely to succeed on retry — contacting the customer for another payment method promptly instead of retrying."
    return f"Uncertain failure cause — defaulting to a conservative {hours:.1f}h window pending manual review."


def requires_approval(strategy: str) -> bool:
    """Human-in-the-loop gate (spec section 6). Silent, no-customer-contact
    retries can auto-execute up to the retry cap; anything that reaches the
    customer (a new message, a payment link) requires explicit approval."""
    return strategy in ("request_new_method", "manual")


def is_within_bounds(retry_count: int, max_retries: int) -> bool:
    """Stopping rule (spec section 9). This is the single choke point every
    retry path must pass through before attempting another one."""
    return retry_count < max_retries


def can_send_another_communication(communications_sent: int, max_communications: int) -> bool:
    """Stopping rule: caps total customer-facing messages per case."""
    return communications_sent < max_communications


def is_within_cooldown(last_action_at, cooldown_hours: float) -> bool:
    """Duplicate-action / idempotency guard: True means we must WAIT — an
    action was already taken too recently to safely take another."""
    if last_action_at is None:
        return False
    return datetime.utcnow() < last_action_at + timedelta(hours=cooldown_hours)


def is_recoverable(probability: float) -> bool:
    """Below this threshold, pursuing recovery isn't worth the customer
    contact — the case is suppressed rather than actioned."""
    return probability >= settings.recovery_min_probability


def is_expired(recovery_window_expires_at) -> bool:
    if recovery_window_expires_at is None:
        return False
    return datetime.utcnow() > recovery_window_expires_at


def next_message_type(communications_sent: int, max_communications: int) -> str:
    """First contact vs. follow-up vs. escalation (last chance before stop)."""
    if communications_sent == 0:
        return "recovery_notification"
    if communications_sent >= max_communications - 1:
        return "escalation"
    return "follow_up_reminder"


def draft_message_template(category: str, amount: float, currency: str = "INR", message_type: str = "recovery_notification") -> str:
    """Deterministic fallback message used when no LLM key is configured, or
    if the LLM call fails — the pipeline must never block on an optional
    dependency."""
    amt = f"{currency} {amount:,.2f}"

    if message_type == "escalation":
        return (f"This is a final reminder that your payment of {amt} is still incomplete. "
                f"Please complete it soon to avoid any disruption: {{link}}. If you've already paid, please disregard this message.")
    if message_type == "follow_up_reminder":
        return (f"Just following up — your payment of {amt} is still pending. "
                f"You can complete it here: {{link}}. If you've already completed it, no action is needed.")
    if message_type == "recovery_confirmation":
        return f"Good news — your payment of {amt} has been received. Thank you!"


    if category == "hard_decline":
        return (f"We noticed your payment of {amt} didn't go through. Your card may be expired, invalid, "
                f"or restricted for this transaction. You can complete your payment using another method here: {{link}}")
    return (f"We noticed your payment of {amt} didn't go through. You can complete your payment "
            f"using another method here: {{link}}")
