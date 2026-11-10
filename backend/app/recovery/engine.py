"""
The AI Revenue Recovery pipeline. Every function here either reads/writes a
RecoveryCase and appends RecoveryTraceStep rows (the audit trail), or is a
thin orchestration wrapper around app/recovery/rules.py (deterministic
decisions) and app/core/llm.py (optional prose only — Groq, never on the
path of a safety-critical decision).

Entry points used by the router:
  run_scan(user, db)                 -> Detector + follow-up/verification pass
  approve_case(user, db, case, actor)-> human approval -> triggers execution
  reject_case(user, db, case, actor, reason)
  release_security_hold / confirm_security_hold -> human decision on an anomaly hold
  advance_clock(user, db, hours)     -> Test Mode only: simulate time passing
  get_metrics(user, db)              -> revenue recovery funnel, computed from DB

ML layer (app/ml, reached only through app.ml.service): a calibrated risk model
scores recoverability, a Thompson-sampling bandit chooses retry delays, and
anomaly detectors place suspected card-testing on a security hold and defer
retries during payment-method outages. All of it sits INSIDE the deterministic
guardrails of rules.py and falls back to them if anything fails.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import llm
from app.core.email import send_notification_email
from app.ml import service as ml
from app.models import RecoveryCase, RecoveryCommunication, RecoveryTraceStep, User
from app.providers.factory import get_provider
from app.providers.razorpay_provider import RazorpayAPIError
from app.recovery import rules

settings = get_settings()


def _trace(db: Session, case: RecoveryCase, agent: str, decision: str, reason: str, actor: str = "system"):
    db.add(RecoveryTraceStep(case_id=case.id, agent=agent, decision=decision, reason=reason, actor=actor))
    case.updated_at = datetime.utcnow()


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except Exception:
        return datetime.utcnow()


_TERMINAL_OR_GATED = {"recovered", "rejected", "suppressed", "exhausted", "expired",
                      "manual_review", "pending_approval", "security_hold"}


def _fmt_delay(delta: timedelta) -> str:
    h = delta.total_seconds() / 3600
    return f"{h * 60:.0f} min" if h < 1 else (f"{h:.0f}h" if abs(h - round(h)) < 0.05 else f"{h:.1f}h")


def run_scan(user: User, db: Session) -> list[RecoveryCase]:
    """Detector step, plus a follow-up/verification sweep over cases already
    in flight. Pulls recent failed payments from the active environment's
    provider (real Razorpay data in Live Mode, the sandbox in Test Mode —
    never mixed)."""
    provider = get_provider(user, db)
    result = provider.get_payments(limit=settings.recovery_max_cases_per_scan, status="failed")

    # ML: one payment snapshot per scan (features + anomaly checks), and outage alerts
    # refreshed BEFORE any case is processed so retries can be deferred in the same pass.
    ctx = ml.build_context(user, db, provider)
    ml.sync_outage_alerts(db, user, ctx)

    processed: list[RecoveryCase] = []
    for p in result["items"]:
        case = db.query(RecoveryCase).filter_by(user_id=user.id, payment_id=p["id"]).first()
        if case is None:
            case = _open_case(user, db, p, ctx)
            processed.append(case)
        elif case.status == "failed":
            _trace(db, case, "Detector", "Re-checked after unsuccessful retry",
                   "Payment is still in a failed state on the latest sync; re-running the recovery pipeline.")
            _run_pipeline(user, db, case, ctx)
            processed.append(case)

    waiting_cases = db.query(RecoveryCase).filter_by(user_id=user.id, status="waiting").all()
    for case in waiting_cases:
        _process_waiting_case(user, db, case, provider)
        processed.append(case)

    ml.sweep_outcomes(db, user.id)
    db.commit()
    return processed


def _open_case(user: User, db: Session, payment: dict, ctx=None) -> RecoveryCase:
    case = RecoveryCase(
        user_id=user.id, source=user.environment, payment_id=payment["id"], order_id=payment.get("order_id"),
        amount=payment["amount"], currency=payment.get("currency", "INR"),
        customer_email=payment.get("email"), customer_contact=payment.get("contact"), method=payment.get("method"),
        failure_reason_raw=payment.get("failure_reason"),
        max_retries=settings.recovery_max_retries, max_communications=settings.recovery_max_communications,
        recovery_window_expires_at=datetime.utcnow() + timedelta(days=settings.recovery_window_days),
        failed_payment_created_at=_parse_dt(payment.get("created_at")),
        status="analyzing",
    )
    db.add(case)
    db.flush()

    _trace(db, case, "Detector", "Revenue at risk detected",
           f"Failed payment of {case.currency} {case.amount:,.2f} detected "
           f"(reason: {case.failure_reason_raw or 'not provided'}). Recovery window: "
           f"{settings.recovery_window_days:.0f} day(s).")

    _run_pipeline(user, db, case, ctx)
    return case


def _run_pipeline(user: User, db: Session, case: RecoveryCase, ctx=None, skip_security: bool = False):
    category = rules.classify_failure(case.failure_reason_raw)
    case.category = category
    _trace(db, case, "Classifier", f"Classified as {category.replace('_', ' ')}",
           f"Failure reason '{case.failure_reason_raw or 'unknown'}' matched the {category.replace('_', ' ')} pattern.")

    # ---- Security screen: suspected card testing is NEVER retried or messaged -------------
    if not skip_security:
        screen = ml.screen_case(db, user, case, ctx)
        if screen.hold:
            case.status = "security_hold"
            case.recovery_probability = 0.0
            case.expected_recovery_value = 0.0
            case.recommended_action = "none"
            _trace(db, case, "Security", "Held for security review",
                   f"This customer's recent activity looks like card testing (anomaly score {screen.score:.2f} ≥ "
                   f"threshold {screen.threshold:.2f}, detector: {screen.source.replace('_', ' ')}). "
                   + ("; ".join(screen.reasons) + ". " if screen.reasons else "")
                   + "No retry or customer contact will happen until a reviewer releases or confirms the hold.")
            return

    risk = ml.assess_risk(db, case, ctx)
    probability = risk.probability
    case.recovery_probability = probability
    case.expected_recovery_value = round(case.amount * probability, 2)

    if not rules.is_recoverable(probability):
        case.status = "suppressed"
        _trace(db, case, "RiskAssessment", "Marked non-recoverable",
               f"{probability * 100:.0f}% recovery probability is below the "
               f"{settings.recovery_min_probability * 100:.0f}% threshold — not pursuing further action."
               + risk.factor_text())
        return

    if risk.source == "ml":
        baseline = rules.risk_assessment(category, case.retry_count)
        _trace(db, case, "RiskAssessment", f"{probability * 100:.0f}% recovery probability — recoverable",
               f"Expected recovered value ≈ {case.currency} {case.expected_recovery_value:,.2f}. Calibrated model "
               f"{risk.version} (the static category prior would have said {baseline * 100:.0f}%)." + risk.factor_text())
    else:
        _trace(db, case, "RiskAssessment", f"{probability * 100:.0f}% recovery probability — recoverable",
               f"Expected recovered value ≈ {case.currency} {case.expected_recovery_value:,.2f} "
               f"based on category and {case.retry_count} prior attempt(s).")

    strategy = rules.choose_strategy(category, case.retry_count)
    case.recommended_action = strategy
    strategy_reason = {
        "retry": "Failure pattern suggests the transaction is likely to succeed if attempted again.",
        "request_new_method": "This decline type rarely succeeds on retry — the customer should be asked for a different payment method.",
        "manual": "Cause is unclear — routing to conservative, manually-reviewed recovery rather than an automated action.",
    }.get(strategy, "")
    _trace(db, case, "Strategy", f"Recommend: {strategy.replace('_', ' ')}", strategy_reason)

    timing = ml.choose_timing(db, user, case, strategy)
    delta = timing.delay
    case.next_action_at = datetime.utcnow() + delta
    if timing.source == "bandit":
        _trace(db, case, "Timing", f"Retry in {_fmt_delay(delta)} (learned timing)", timing.explanation)
    else:
        _trace(db, case, "Timing", f"Act at {case.next_action_at.strftime('%H:%M:%S')}",
               rules.timing_reason(category, delta))

    if rules.requires_approval(strategy):
        message_type = rules.next_message_type(case.communications_sent, case.max_communications)
        case.prepared_message = _draft_message(case, message_type)
        _trace(db, case, "Communication", "Recovery message prepared",
               "This action reaches the customer directly, so a message was drafted for review before sending.")
        case.status = "pending_approval"
        _trace(db, case, "Approval", "Awaiting human approval",
               f"'{strategy.replace('_', ' ')}' contacts the customer and requires reviewer sign-off before execution.")
    else:
        _trace(db, case, "Communication", "No customer message required",
               "Silent retry does not involve contacting the customer.")
        if rules.is_within_bounds(case.retry_count, case.max_retries):
            case.status = "approved"
            _trace(db, case, "Approval", "Auto-approved — bounded silent retry",
                   f"Retry {case.retry_count + 1}/{case.max_retries}: no customer contact, within the configured retry cap.")
            if timing.source == "bandit" and delta > timedelta(hours=settings.ml_immediate_threshold_hours):
                case.status = "waiting"
                _trace(db, case, "Execution", f"Retry scheduled for +{_fmt_delay(delta)}",
                       "Waiting for the learned retry delay before attempting; recovery is verified on the next scan after that.")
            else:
                _execute_case(user, db, case)
        else:
            case.status = "exhausted"
            _trace(db, case, "Approval", "Retry limit reached",
                   f"Maximum retries ({case.max_retries}) already attempted for this payment; "
                   f"suppressing further automated retries and communication.")


def _draft_message(case: RecoveryCase, message_type: str) -> str:
    link_placeholder = case.payment_link_url or "{link}"
    template = rules.draft_message_template(case.category, case.amount, case.currency, message_type).replace(
        "{link}", link_placeholder)

    tone = {
        "recovery_notification": "This is the first message about this failed payment — friendly and clear.",
        "follow_up_reminder": "This is a gentle follow-up reminder — the customer hasn't acted yet.",
        "escalation": "This is the final reminder before automated recovery stops — polite but a little more urgent.",
        "recovery_confirmation": "This confirms the payment succeeded — short and warm, no action needed from the customer.",
    }.get(message_type, "")

    generated = llm.generate(
        system=(
            "You draft short, polite, action-oriented payment-recovery messages for Reparo AI, an "
            "operations agent for Razorpay merchants. Under 40 words. No subject line, no greeting "
            "beyond a brief opener. Never expose internal reasoning, scores, or classifications to the "
            "customer. Include the placeholder {link} exactly once if a payment link is relevant. "
            "Never invent an amount, currency, or reason beyond what's given."
        ),
        prompt=(
            f"Message type: {message_type}. {tone} Amount: {case.currency} {case.amount:,.2f}. "
            f"Failure category: {case.category}. Draft the message."
        ),
        max_tokens=120,
    )
    return generated if generated else template


def approve_case(user: User, db: Session, case: RecoveryCase, actor: str) -> RecoveryCase:
    if case.status != "pending_approval":
        raise ValueError(f"Case is '{case.status}', not awaiting approval.")
    case.status = "approved"
    _trace(db, case, "Approval", "Approved by reviewer", "Reviewer approved the recommended recovery action.", actor=actor)
    _execute_case(user, db, case)
    ml.sweep_outcomes(db, user.id)
    db.commit()
    return case


def reject_case(user: User, db: Session, case: RecoveryCase, actor: str, reason: str) -> RecoveryCase:
    if case.status != "pending_approval":
        raise ValueError(f"Case is '{case.status}', not awaiting approval.")
    case.status = "suppressed"
    _trace(db, case, "Approval", "Rejected by reviewer", reason or "No reason provided.", actor=actor)
    _trace(db, case, "Audit", "Case suppressed",
           "Automated recovery for this payment is suppressed after human rejection. No further action will be taken.")
    ml.sweep_outcomes(db, user.id)
    db.commit()
    return case


def release_security_hold(user: User, db: Session, case: RecoveryCase, actor: str) -> RecoveryCase:
    """A reviewer judged the flagged activity legitimate: resume the normal pipeline
    (security screening is skipped for this one pass; every other guardrail still applies)."""
    if case.status != "security_hold":
        raise ValueError(f"Case is '{case.status}', not on security hold.")
    _trace(db, case, "Security", "Hold released by reviewer",
           "Reviewer judged the activity legitimate; resuming normal recovery under all standard limits.", actor=actor)
    ml.resolve_alerts_for_case(db, case, "acknowledged")
    case.status = "analyzing"
    _run_pipeline(user, db, case, ml.build_context(user, db), skip_security=True)
    ml.sweep_outcomes(db, user.id)
    db.commit()
    return case


def confirm_security_hold(user: User, db: Session, case: RecoveryCase, actor: str) -> RecoveryCase:
    """A reviewer confirmed the activity is suspicious: recovery stops permanently."""
    if case.status != "security_hold":
        raise ValueError(f"Case is '{case.status}', not on security hold.")
    case.status = "suppressed"
    _trace(db, case, "Security", "Hold confirmed — treated as suspicious", "Reviewer confirmed the pattern is suspicious.", actor=actor)
    _trace(db, case, "Audit", "Case suppressed",
           "No retry or customer contact will ever be made for this payment. Escalate through your fraud process.")
    ml.resolve_alerts_for_case(db, case, "acknowledged")
    ml.sweep_outcomes(db, user.id)
    db.commit()
    return case


def advance_clock(user: User, db: Session, hours: float) -> dict:
    """Test Mode only: simulate `hours` passing by moving every timestamp the
    pipeline reasons about into the past (cases, sandbox payments, alerts)."""
    if user.environment != "test":
        raise ValueError("Time can only be advanced in Test Mode.")
    hours = float(min(max(hours, 0.0), 24 * 14))
    delta = timedelta(hours=hours)
    n = 0
    for c in db.query(RecoveryCase).filter_by(user_id=user.id).all():
        for attr in ("created_at", "next_action_at", "last_action_at", "recovery_window_expires_at",
                     "failed_payment_created_at"):
            v = getattr(c, attr)
            if v is not None:
                setattr(c, attr, v - delta)
        n += 1
    provider = get_provider(user, db)
    if hasattr(provider, "shift_time"):
        provider.shift_time(hours)
    ml.shift_alerts(db, user.id, delta)
    db.commit()
    return {"advanced_hours": hours, "cases_shifted": n}


def _execute_case(user: User, db: Session, case: RecoveryCase):
    if rules.is_expired(case.recovery_window_expires_at):
        case.status = "expired"
        _trace(db, case, "Execution", "Recovery window expired",
               f"No recovery within {settings.recovery_window_days:.0f} day(s); stopping further automated action.")
        return
    if rules.is_within_cooldown(case.last_action_at, settings.recovery_cooldown_hours):


        case.status = "waiting"
        _trace(db, case, "Execution", "Skipped — cooldown active",
               "An action was already taken recently for this case; waiting for the cooldown window to elapse.")
        return

    # ML: retrying into a detected payment-method outage would burn the bounded retry
    # budget for nothing. Defer (bounded) without consuming a retry or touching the cooldown.
    if case.recommended_action == "retry":
        outage = ml.active_outage(db, user.id, case.method)
        if outage is not None and ml.deferrals_used(db, case) < settings.ml_max_outage_deferrals:
            case.status = "waiting"
            case.next_action_at = datetime.utcnow() + timedelta(minutes=settings.ml_outage_hold_minutes)
            _trace(db, case, "Anomaly", "Retry deferred — payment method outage",
                   f"Failures on '{case.method}' are spiking across customers (suspected gateway/bank outage). Retrying now "
                   f"would likely fail and use up one of {case.max_retries} bounded retries, so the retry is postponed "
                   f"{settings.ml_outage_hold_minutes} min and no attempt is consumed "
                   f"(deferral {ml.deferrals_used(db, case) + 1}/{settings.ml_max_outage_deferrals}).")
            return

    case.last_action_at = datetime.utcnow()
    provider = get_provider(user, db)

    if case.recommended_action == "retry":
        if not rules.is_within_bounds(case.retry_count, case.max_retries):
            case.status = "exhausted"
            _trace(db, case, "Execution", "Retry limit reached", "Bounded retry cap hit at execution time; no action taken.")
            return

        case.status = "retrying"
        case.retry_count += 1
        ml.mark_timing_executed(db, case)
        _trace(db, case, "Execution", f"Retry attempt {case.retry_count}/{case.max_retries} initiated",
               "Executing the bounded automatic retry against the payment gateway.")

        if user.environment == "test":
            age_h = max((datetime.utcnow() - case.created_at).total_seconds() / 3600.0, 0.0)
            result = provider.attempt_recovery_retry(case.payment_id, case.category, age_hours=age_h,
                                                     retry_index=case.retry_count - 1)
            _verify_retry_outcome(db, case, result, user)
        else:
            _create_live_recovery_link(db, case, provider,
                                        reason_prefix="Retry could not be replayed directly via the Razorpay API")

    elif case.recommended_action == "request_new_method":
        case.status = "waiting"
        if user.environment == "test":
            case.payment_link_url = f"https://pay.reparo.test/link/{case.id}"
            _trace(db, case, "Execution", "Simulated payment link prepared",
                   f"Test Mode: prepared a simulated payment link ({case.payment_link_url}) instead of a real Razorpay charge.")
        else:
            _create_live_recovery_link(db, case, provider, reason_prefix="Customer needs an alternate payment method")
        if case.status == "waiting":
            _dispatch_message(db, case, provider)

    else:
        case.status = "manual_review"
        _trace(db, case, "Execution", "Routed to manual review", "Cause of failure is unclear — no automated action taken.")


def _create_live_recovery_link(db: Session, case: RecoveryCase, provider, reason_prefix: str):
    try:
        link = provider.create_payment_link(
            amount=case.amount, currency=case.currency,
            description="Complete your payment — Reparo AI recovery",
            customer_email=case.customer_email, customer_contact=case.customer_contact,
        )
        case.payment_link_id = link["id"]
        case.payment_link_url = link["short_url"]
        case.status = "waiting"
        _trace(db, case, "Execution", "Payment link created",
               f"{reason_prefix}; a real Razorpay payment link was created and prepared for the customer: {link['short_url']}. "
               f"Recovery is confirmed only once payment/webhook data verifies it was paid.")
    except RazorpayAPIError as e:
        case.status = "manual_review"
        _trace(db, case, "Execution", "Payment link could not be created",
               f"Razorpay Payment Links unavailable or failed ({e.message}). Routed to manual review rather than "
               f"falsely reporting that a recovery action was taken.")


def _dispatch_message(db: Session, case: RecoveryCase, provider=None):
    message_type = rules.next_message_type(case.communications_sent, case.max_communications)
    message = _draft_message(case, message_type)
    if case.payment_link_url:
        message = message.replace("{link}", case.payment_link_url)
    case.prepared_message = message
    case.communications_sent += 1
    case.next_action_at = datetime.utcnow() + timedelta(hours=settings.recovery_cooldown_hours)

    label = message_type.replace("_", " ").title()
    status = "generated"
    if settings.smtp_host and case.customer_email:
        try:
            send_notification_email(case.customer_email, "Complete your payment", message)
            status = "sent"
            _trace(db, case, "Communication", f"{label} sent",
                   f"Email dispatched to {case.customer_email} via configured SMTP provider "
                   f"({case.communications_sent}/{case.max_communications}).")
        except Exception as e:
            status = "failed"
            _trace(db, case, "Communication", f"{label} prepared (send failed)",
                   f"SMTP dispatch failed ({e}); message is prepared and can be resent manually.")
    else:
        status = "simulated"
        _trace(db, case, "Communication", f"{label} prepared (not sent)",
               "No email provider is configured, so the message was drafted and logged, not delivered. "
               "Configure SMTP_* to enable real dispatch — the same code path sends it once available.")

    db.add(RecoveryCommunication(
        case_id=case.id, user_id=case.user_id, message_type=message_type,
        to_address=case.customer_email, content=message, status=status,
    ))

    # Test Mode only: simulate whether the customer acts on the message, using the same world
    # model as retries. Recovery is still confirmed only by the next scan's payment verification.
    if provider is not None and case.source == "test" and hasattr(provider, "simulate_customer_payment"):
        try:
            if provider.simulate_customer_payment(case.payment_id, case.communications_sent - 1):
                _trace(db, case, "Simulation", "Customer completed the payment (Test Mode)",
                       "The sandbox customer responded to the message and paid. The next scan will verify the "
                       "captured payment before marking the case recovered.")
        except Exception:
            pass


def _dispatch_confirmation(db: Session, case: RecoveryCase):
    if not case.customer_email:
        return
    message = _draft_message(case, "recovery_confirmation")
    status = "generated"
    if settings.smtp_host:
        try:
            send_notification_email(case.customer_email, "Payment received", message)
            status = "sent"
        except Exception:
            status = "failed"
    else:
        status = "simulated"
    db.add(RecoveryCommunication(
        case_id=case.id, user_id=case.user_id, message_type="recovery_confirmation",
        to_address=case.customer_email, content=message, status=status,
    ))
    _trace(db, case, "Communication", "Confirmation " + ("sent" if status == "sent" else "prepared"),
           "Customer notified that their payment was received." if status == "sent" else
           "Confirmation drafted and logged; no email provider configured to deliver it.")


def _verify_retry_outcome(db: Session, case: RecoveryCase, result: dict, user: User | None = None):
    outcome = result.get("outcome")
    if outcome in ("recovered", "failed_again"):
        ml.record_retry_outcome(db, case, outcome == "recovered")   # bandit reward
    if outcome == "recovered":
        case.status = "recovered"
        case.recovered_amount = case.amount
        _trace(db, case, "Verification", "Payment recovered",
               f"Verified against sandbox state: retry succeeded, {case.currency} {case.amount:,.2f} recovered.")
        _trace(db, case, "Audit", "Recovery complete",
               f"{case.currency} {case.amount:,.2f} recovered after {case.retry_count} retry attempt(s). "
               f"Future reminders and retries are cancelled.")
        _dispatch_confirmation(db, case)
    elif outcome == "failed_again":
        if rules.is_within_bounds(case.retry_count, case.max_retries):
            case.status = "waiting"
            timing = ml.choose_timing(db, user, case, "retry") if user is not None else None
            delay = timing.delay if timing else rules.choose_timing(case.category)
            case.next_action_at = datetime.utcnow() + delay
            _trace(db, case, "Verification", "Retry unsuccessful",
                   f"Retry attempt {case.retry_count} did not recover the payment. "
                   f"Eligible for another attempt after the cooldown window.")
            if timing is not None and timing.source == "bandit":
                _trace(db, case, "Timing", f"Next retry in {_fmt_delay(delay)} (learned timing)", timing.explanation)
        else:
            case.status = "exhausted"
            _trace(db, case, "Verification", "Retry unsuccessful", f"Retry attempt {case.retry_count} did not recover the payment.")
            _trace(db, case, "Audit", "Retry limit reached",
                   f"Maximum retries ({case.max_retries}) reached; suppressing further automated retries for this payment.")
    else:
        case.status = "manual_review"
        _trace(db, case, "Verification", "Unable to verify outcome", "Routed to manual review.")


def verify_live_event(db: Session, case: RecoveryCase, event_type: str, summary: str):
    """Called from the webhook handler when a real Razorpay event references
    a case's payment/order/payment-link id (spec section 12/19: recovery must
    be confirmed via payment/webhook data, not assumed)."""
    if "captured" in event_type or "paid" in event_type:
        case.status = "recovered"
        case.recovered_amount = case.amount
        _trace(db, case, "Verification", "Payment recovered",
               f"Verified via Razorpay webhook ({event_type}): {case.currency} {case.amount:,.2f} recovered.")
        _trace(db, case, "Audit", "Recovery complete",
               f"{case.currency} {case.amount:,.2f} recovered — confirmed by Razorpay. Future reminders cancelled.")
        _dispatch_confirmation(db, case)
        ml.sweep_outcomes(db, case.user_id)
    elif "failed" in event_type:
        if rules.is_within_bounds(case.retry_count, case.max_retries):
            case.status = "waiting"
        else:
            case.status = "exhausted"
        _trace(db, case, "Verification", "Payment still failing", f"Razorpay webhook ({event_type}) reported continued failure.")
    db.commit()


def _process_waiting_case(user: User, db: Session, case: RecoveryCase, provider):
    if rules.is_expired(case.recovery_window_expires_at):
        case.status = "expired"
        _trace(db, case, "Audit", "Recovery window expired",
               f"No recovery within {settings.recovery_window_days:.0f} day(s) of detection; stopping further automated action.")
        return


    payment = provider.get_payment(case.payment_id)
    if payment and payment.get("status") == "captured":
        case.status = "recovered"
        case.recovered_amount = case.amount
        _trace(db, case, "Verification", "Payment recovered",
               f"Verified: payment status is now captured. {case.currency} {case.amount:,.2f} recovered. "
               f"Future reminders and retries are cancelled.")
        _trace(db, case, "Audit", "Recovery complete", f"{case.currency} {case.amount:,.2f} recovered.")
        _dispatch_confirmation(db, case)
        return

    if case.next_action_at and datetime.utcnow() < case.next_action_at:
        return

    if case.recommended_action == "retry":
        if rules.is_within_bounds(case.retry_count, case.max_retries):
            _trace(db, case, "Timing", "Retry window reached", "Cooldown elapsed; attempting another bounded retry.")
            _execute_case(user, db, case)
        else:
            case.status = "exhausted"
            _trace(db, case, "Audit", "Retry limit reached",
                   f"Maximum retries ({case.max_retries}) reached without recovery; suppressing further automated retries.")
    else:
        if rules.can_send_another_communication(case.communications_sent, case.max_communications):
            _trace(db, case, "Timing", "Follow-up window reached",
                   "Cooldown elapsed and payment is still pending; sending the next scheduled communication.")
            _dispatch_message(db, case)
        else:
            case.status = "exhausted"
            _trace(db, case, "Audit", "Communication limit reached",
                   f"Maximum communications ({case.max_communications}) sent without recovery; suppressing further contact.")


def get_metrics(user: User, db: Session) -> dict:
    cases = db.query(RecoveryCase).filter_by(user_id=user.id).all()
    communications = db.query(RecoveryCommunication).filter_by(user_id=user.id).all()

    total_at_risk_amount = sum(c.amount for c in cases)
    attempted_amount = sum(c.amount for c in cases if c.status in ("retrying", "waiting", "verifying", "recovered", "exhausted"))
    recovered_amount = sum(c.recovered_amount for c in cases if c.status == "recovered")
    unrecovered_amount = max(total_at_risk_amount - recovered_amount, 0)
    awaiting_approval = sum(1 for c in cases if c.status == "pending_approval")
    recovery_attempts = sum(1 for c in cases if c.retry_count > 0 or c.status in ("retrying", "waiting", "verifying", "recovered", "exhausted"))
    recovery_rate = round((recovered_amount / total_at_risk_amount) * 100, 1) if total_at_risk_amount > 0 else 0.0

    return {
        "total_failed_payments": len(cases),
        "failed_payments": sum(1 for c in cases if c.status == "failed"),
        "recoverable_payments": sum(1 for c in cases if c.status not in ("suppressed", "rejected")),
        "revenue_at_risk": round(total_at_risk_amount, 2),
        "attempted_amount": round(attempted_amount, 2),
        "recovered_amount": round(recovered_amount, 2),
        "unrecovered_amount": round(unrecovered_amount, 2),
        "recovery_attempts": recovery_attempts,
        "awaiting_approval": awaiting_approval,
        "active_recovery_cases": sum(1 for c in cases if c.status in ("analyzing", "pending_approval", "approved", "waiting", "retrying", "verifying")),
        "pending_followups": sum(1 for c in cases if c.status == "waiting"),
        "security_holds": sum(1 for c in cases if c.status == "security_hold"),
        "exhausted_cases": sum(1 for c in cases if c.status == "exhausted"),
        "communications_sent": sum(1 for m in communications if m.status in ("sent", "simulated")),
        "recovery_rate": recovery_rate,
        "max_retries": settings.recovery_max_retries,
        "max_communications": settings.recovery_max_communications,
    }
