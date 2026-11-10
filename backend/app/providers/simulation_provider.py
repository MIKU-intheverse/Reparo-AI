"""
SimulationProvider — Reparo AI's own stateful sandbox (distinct from
Razorpay's own test mode). Backed by real DB rows (sim_payments,
sim_orders, sim_refunds, sim_customers, sim_events) so state persists
across requests instead of being re-randomized on every page load, and so
actions (e.g. "create a payment") are visible in the next fetch, in
analytics, and to the AI agent — same as the spec's stateful-simulation
requirement.
"""
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.ml import world
from app.ml.features import smooth_rate
from app.models import SimCustomer, SimDispute, SimEvent, SimOrder, SimPayment, SimRefund, SimSettlement
from app.providers.base import DataProvider

settings = get_settings()

METHODS = ["card", "upi", "netbanking", "wallet"]
FAILURE_REASONS = list(world.REASONS)   # insufficient_funds, card_declined, otp_timeout, issuer_unavailable, ...
DISPUTE_REASONS = ["goods_or_services_not_provided", "duplicate_processing", "unrecognized", "fraudulent_transaction"]
NAMES = ["Nexura Media Group", "Solaria Energy Systems", "Vanguard Fintech Ltd", "ByteScale Software Pvt Ltd",
         "Cobalt Retail Co", "Meridian Logistics", "Orchid Health Labs", "Pinnacle Realty Group"]


def _dt(x) -> str:
    return x.isoformat() if isinstance(x, datetime) else x


def _payment_row(p: SimPayment) -> dict:
    return {
        "id": p.id, "order_id": p.order_id, "amount": p.amount, "currency": p.currency,
        "status": p.status, "method": p.method, "email": p.email, "contact": p.contact,
        "created_at": _dt(p.created_at), "captured": p.captured, "refund_status": p.refund_status,
        "failure_reason": p.failure_reason, "source": "test",
    }


def _order_row(o: SimOrder) -> dict:
    return {"id": o.id, "amount": o.amount, "currency": o.currency, "status": o.status,
            "attempts": o.attempts, "created_at": _dt(o.created_at), "source": "test"}


def _refund_row(r: SimRefund) -> dict:
    return {"id": r.id, "payment_id": r.payment_id, "amount": r.amount, "status": r.status,
            "created_at": _dt(r.created_at), "source": "test"}


def _customer_row(c: SimCustomer) -> dict:
    return {"id": c.id, "name": c.name, "email": c.email, "contact": c.contact,
            "created_at": _dt(c.created_at), "source": "test"}


def _settlement_row(s: SimSettlement) -> dict:
    return {"id": s.id, "amount": s.amount, "fees": s.fees, "status": s.status,
            "settled_at": _dt(s.settled_at), "source": "test"}


def _dispute_row(d: SimDispute) -> dict:
    return {"id": d.id, "payment_id": d.payment_id, "amount": d.amount, "status": d.status,
            "reason": d.reason, "created_at": _dt(d.created_at), "source": "test"}


class SimulationProvider(DataProvider):
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self._ensure_seeded()


    def _ensure_seeded(self):
        existing = self.db.query(SimPayment).filter_by(user_id=self.user_id).count()
        if existing > 0:
            return
        customers = []
        for name in NAMES:
            c = SimCustomer(
                user_id=self.user_id, name=name,
                email=f"{name.lower().replace(' ', '.')}@example.com",
                contact=f"+91{random.randint(7000000000, 9999999999)}",
            )
            self.db.add(c)
            customers.append(c)
        self.db.flush()

        for _ in range(60):
            days_ago = random.randint(0, 20)
            created = datetime.utcnow() - timedelta(days=days_ago, hours=random.randint(0, 23))
            amount = round(random.uniform(200, 45000), 2)
            order = SimOrder(user_id=self.user_id, amount=amount, status="paid", attempts=1, created_at=created)
            self.db.add(order)
            self.db.flush()

            customer = random.choice(customers)
            captured = random.random() > 0.22
            status = "captured" if captured else "failed"
            payment = SimPayment(
                user_id=self.user_id, order_id=order.id, customer_id=customer.id, amount=amount,
                method=random.choice(METHODS), status=status, captured=captured,
                failure_reason=None if captured else random.choice(FAILURE_REASONS),
                email=customer.email, contact=customer.contact, created_at=created,
            )
            self.db.add(payment)
            self.db.flush()

            if captured and random.random() < 0.08:
                refund_amount = amount if random.random() < 0.6 else round(amount * 0.5, 2)
                payment.refund_status = "full" if refund_amount == amount else "partial"
                self.db.add(SimRefund(
                    user_id=self.user_id, payment_id=payment.id, amount=refund_amount,
                    created_at=created + timedelta(hours=random.randint(1, 48)),
                ))

            if captured and random.random() < 0.05:
                self.db.add(SimDispute(
                    user_id=self.user_id, payment_id=payment.id, amount=amount,
                    status=random.choice(["open", "under_review", "won", "lost"]),
                    reason=random.choice(DISPUTE_REASONS),
                    created_at=created + timedelta(days=random.randint(1, 5)),
                ))

        for week in range(3):
            settled_at = datetime.utcnow() - timedelta(days=week * 7 + random.randint(0, 2))
            gross = round(random.uniform(15000, 120000), 2)
            self.db.add(SimSettlement(
                user_id=self.user_id, amount=round(gross * 0.98, 2), fees=round(gross * 0.02, 2),
                status="processed", settled_at=settled_at, created_at=settled_at,
            ))

        self.db.add(SimEvent(user_id=self.user_id, kind="seed", message="Test Mode sandbox initialized with sample data."))
        self.db.commit()


    def get_payments(self, limit: int = 20, skip: int = 0, status: str | None = None) -> dict:
        q = self.db.query(SimPayment).filter_by(user_id=self.user_id)
        if status:
            q = q.filter_by(status=status)
        total = q.count()
        rows = q.order_by(SimPayment.created_at.desc()).offset(skip).limit(limit).all()
        return {"items": [_payment_row(r) for r in rows], "count": total, "has_more": skip + limit < total}

    def get_payment(self, payment_id: str) -> dict | None:
        p = self.db.query(SimPayment).filter_by(user_id=self.user_id, id=payment_id).first()
        return _payment_row(p) if p else None

    def get_orders(self, limit: int = 20, skip: int = 0) -> dict:
        q = self.db.query(SimOrder).filter_by(user_id=self.user_id)
        total = q.count()
        rows = q.order_by(SimOrder.created_at.desc()).offset(skip).limit(limit).all()
        return {"items": [_order_row(r) for r in rows], "count": total, "has_more": skip + limit < total}

    def get_order(self, order_id: str) -> dict | None:
        o = self.db.query(SimOrder).filter_by(user_id=self.user_id, id=order_id).first()
        return _order_row(o) if o else None

    def get_refunds(self, limit: int = 20, skip: int = 0) -> dict:
        q = self.db.query(SimRefund).filter_by(user_id=self.user_id)
        total = q.count()
        rows = q.order_by(SimRefund.created_at.desc()).offset(skip).limit(limit).all()
        return {"items": [_refund_row(r) for r in rows], "count": total, "has_more": skip + limit < total}

    def get_customers(self, limit: int = 20, skip: int = 0) -> dict:
        q = self.db.query(SimCustomer).filter_by(user_id=self.user_id)
        total = q.count()
        rows = q.order_by(SimCustomer.created_at.desc()).offset(skip).limit(limit).all()
        return {"items": [_customer_row(r) for r in rows], "count": total, "has_more": skip + limit < total}

    def get_settlements(self, limit: int = 20, skip: int = 0) -> dict:
        q = self.db.query(SimSettlement).filter_by(user_id=self.user_id)
        total = q.count()
        rows = q.order_by(SimSettlement.settled_at.desc()).offset(skip).limit(limit).all()
        return {"items": [_settlement_row(r) for r in rows], "count": total, "has_more": skip + limit < total}

    def get_disputes(self, limit: int = 20, skip: int = 0) -> dict:
        q = self.db.query(SimDispute).filter_by(user_id=self.user_id)
        total = q.count()
        rows = q.order_by(SimDispute.created_at.desc()).offset(skip).limit(limit).all()
        return {"items": [_dispute_row(r) for r in rows], "count": total, "has_more": skip + limit < total}

    def get_analytics(self, days: int = 14) -> dict:
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = self.db.query(SimPayment).filter(
            SimPayment.user_id == self.user_id, SimPayment.created_at >= cutoff
        ).all()
        captured = [r for r in rows if r.status == "captured"]
        failed = [r for r in rows if r.status == "failed"]
        refunded_amount = sum(r.amount for r in rows if r.refund_status)

        series: dict[str, float] = {}
        for r in rows:
            day = r.created_at.date().isoformat()
            series[day] = series.get(day, 0) + (r.amount if r.status == "captured" else 0)

        methods: dict[str, int] = {}
        for r in rows:
            methods[r.method] = methods.get(r.method, 0) + 1

        total = len(rows) or 1
        return {
            "total_revenue": round(sum(r.amount for r in captured), 2),
            "total_payments": len(rows),
            "success_rate": round(len(captured) / total * 100, 2),
            "failed_payments": len(failed),
            "refunded_amount": round(refunded_amount, 2),
            "revenue_series": [{"date": d, "amount": round(a, 2)} for d, a in sorted(series.items())],
            "method_breakdown": [{"method": m, "count": c} for m, c in methods.items()],
        }

    def search_transactions(self, query: str, limit: int = 20) -> dict:
        ql = f"%{query.strip().lower()}%"
        rows = self.db.query(SimPayment).filter(
            SimPayment.user_id == self.user_id,
            (SimPayment.id.ilike(ql)) | (SimPayment.email.ilike(ql)) |
            (SimPayment.contact.ilike(ql)) | (SimPayment.status.ilike(ql)) | (SimPayment.method.ilike(ql))
        ).limit(limit).all()
        return {"items": [_payment_row(r) for r in rows], "count": len(rows), "has_more": False}


    def create_test_payment(self, amount: float | None = None, method: str | None = None,
                             should_fail: bool | None = None, **kwargs) -> dict:
        amount = amount or round(random.uniform(200, 20000), 2)
        method = method or random.choice(METHODS)
        fail = should_fail if should_fail is not None else random.random() < 0.15

        customer = self.db.query(SimCustomer).filter_by(user_id=self.user_id).order_by(
            SimCustomer.created_at.desc()).first()
        if not customer:
            customer = SimCustomer(user_id=self.user_id, name="Simulated Customer",
                                    email="simulated.customer@example.com", contact="+919999999999")
            self.db.add(customer)
            self.db.flush()

        order = SimOrder(user_id=self.user_id, amount=amount, status="paid", attempts=1)
        self.db.add(order)
        self.db.flush()

        payment = SimPayment(
            user_id=self.user_id, order_id=order.id, customer_id=customer.id, amount=amount, method=method,
            status="failed" if fail else "captured", captured=not fail,
            failure_reason=random.choice(FAILURE_REASONS) if fail else None,
            email=customer.email, contact=customer.contact,
        )
        self.db.add(payment)
        self.db.add(SimEvent(
            user_id=self.user_id, kind="payment_created",
            message=f"Simulated {'failed' if fail else 'captured'} payment of ₹{amount} via {method}.",
        ))
        self.db.commit()
        self.db.refresh(payment)
        return _payment_row(payment)


    # Legacy per-category success rates, used only when the ML layer is disabled.
    RECOVERY_SUCCESS_RATE = {"soft_decline": 0.55, "technical": 0.65, "hard_decline": 0.05, "unknown": 0.25}

    # ---- sandbox ground truth: the same world model the ML layer is trained on --------------
    @staticmethod
    def _world_params() -> world.WorldParams:
        return world.get_world(settings.ml_sandbox_world)

    def _customer_history(self, payment: SimPayment) -> tuple[int, int]:
        prior = self.db.query(SimPayment).filter(
            SimPayment.user_id == self.user_id, SimPayment.email == payment.email,
            SimPayment.created_at < payment.created_at, SimPayment.id != payment.id).all()
        return len(prior), sum(1 for p in prior if p.status in ("captured", "refunded", "authorized"))

    def _local_parts(self):
        local = datetime.utcnow() + timedelta(minutes=settings.ml_local_utc_offset_minutes)
        hour, dom, _, _ = world.time_parts_from_datetime(local)
        return hour, dom

    def _retry_success_probability(self, payment: SimPayment, category: str, age_hours, retry_index) -> float:
        if not settings.ml_enabled or age_hours is None:
            return self.RECOVERY_SUCCESS_RATE.get(category, 0.25)
        n, cap = self._customer_history(payment)
        hour, dom = self._local_parts()
        return world.retry_success_prob(payment.failure_reason, payment.method, payment.amount, smooth_rate(cap, n),
                                        float(age_hours), int(retry_index or 0), hour, dom, self._world_params())

    def attempt_recovery_retry(self, payment_id: str, category: str, age_hours: float | None = None,
                               retry_index: int | None = None) -> dict:
        """
        Executes a bounded retry against the sandbox. This is the Test Mode
        counterpart to a real Razorpay retry. There is no real gateway, so the
        outcome is a Bernoulli draw whose probability comes from the world model
        (app/ml/world.py): it depends on WHY the payment failed, the payment
        method, amount, how long ago it failed, the time of day, the customer's
        history and how many retries already failed. That is what makes retry
        timing a learnable problem for the bandit. With the ML layer disabled it
        falls back to the original flat per-category rates.
        """
        payment = self.db.query(SimPayment).filter_by(user_id=self.user_id, id=payment_id).first()
        if not payment:
            return {"outcome": "not_found"}
        if payment.status == "captured":
            return {"outcome": "already_resolved", "payment": _payment_row(payment)}

        payment.retry_count += 1
        success = random.random() < self._retry_success_probability(payment, category, age_hours, retry_index)

        if success:
            payment.status = "captured"
            payment.captured = True
            payment.failure_reason = None
            self.db.add(SimEvent(
                user_id=self.user_id, kind="recovery_succeeded",
                message=f"Recovery retry succeeded — ₹{payment.amount:.2f} recovered on attempt {payment.retry_count}.",
            ))
        else:
            self.db.add(SimEvent(
                user_id=self.user_id, kind="recovery_retry_failed",
                message=f"Recovery retry #{payment.retry_count} failed for ₹{payment.amount:.2f} payment.",
            ))
        self.db.commit()
        self.db.refresh(payment)
        return {"outcome": "recovered" if success else "failed_again", "payment": _payment_row(payment)}

    def simulate_customer_payment(self, payment_id: str, message_index: int) -> bool:
        """Test Mode: does the sandbox customer act on recovery message #message_index?"""
        payment = self.db.query(SimPayment).filter_by(user_id=self.user_id, id=payment_id).first()
        if not payment or payment.status == "captured":
            return False
        n, cap = self._customer_history(payment)
        resp = min(max(0.55 * smooth_rate(cap, n) + 0.45 * random.betavariate(2, 3), 0.02), 0.98)
        hour, _ = self._local_parts()
        p = world.link_success_prob(payment.failure_reason, payment.amount, resp, message_index, hour, self._world_params())
        if random.random() < p:
            payment.status, payment.captured, payment.failure_reason = "captured", True, None
            self.db.add(SimEvent(user_id=self.user_id, kind="customer_paid",
                                 message=f"Customer completed a ₹{payment.amount:.2f} payment after a recovery message."))
            self.db.commit()
            return True
        return False

    # ---- sandbox controls used by the ML demo ---------------------------------------------
    def shift_time(self, hours: float) -> None:
        """Simulate time passing: everything time-stamped moves `hours` into the past."""
        delta = timedelta(hours=hours)
        for model in (SimPayment, SimOrder, SimEvent):
            for row in self.db.query(model).filter_by(user_id=self.user_id).all():
                if getattr(row, "created_at", None) is not None:
                    row.created_at = row.created_at - delta
        self.db.flush()

    def _new_customer(self, name: str, email: str) -> SimCustomer:
        c = SimCustomer(user_id=self.user_id, name=name, email=email, contact=f"+91{random.randint(7000000000, 9999999999)}")
        self.db.add(c)
        self.db.flush()
        return c

    def _add_failed_or_ok(self, customer: SimCustomer, amount: float, method: str, failed: bool, reason: str | None,
                          created: datetime) -> SimPayment:
        order = SimOrder(user_id=self.user_id, amount=amount, status="paid", attempts=1, created_at=created)
        self.db.add(order)
        self.db.flush()
        pay = SimPayment(user_id=self.user_id, order_id=order.id, customer_id=customer.id, amount=amount, method=method,
                         status="failed" if failed else "captured", captured=not failed,
                         failure_reason=reason if failed else None, email=customer.email, contact=customer.contact,
                         created_at=created)
        self.db.add(pay)
        return pay

    def inject_incident(self, kind: str, method: str = "upi") -> dict:
        """Create a realistic burst of payments for demoing the anomaly detectors."""
        now = datetime.utcnow()
        if kind == "card_testing":
            tag = random.randint(1000, 9999)
            cust = self._new_customer(f"Guest checkout {tag}", f"probe.{tag}@tempmail.example")
            n = 14
            for i in range(n):
                created = now - timedelta(seconds=(n - i) * random.randint(25, 45))
                self._add_failed_or_ok(cust, round(random.uniform(5, 140), 2), "card", random.random() < 0.93,
                                       random.choice(["card_declined", "risk_check_failed", "do_not_honor"]), created)
            msg = f"Injected a card-testing burst: {n} small card payments from one guest within ~8 minutes."
        elif kind == "outage":
            n = 26
            for i in range(n):
                cust = self._new_customer(f"Shopper {random.randint(10000, 99999)}", f"shopper{random.randint(10000, 99999)}@example.org")
                created = now - timedelta(minutes=random.uniform(0.5, 28))
                self._add_failed_or_ok(cust, round(random.uniform(200, 6000), 2), method, random.random() < 0.9,
                                       random.choices(["gateway_timeout", "issuer_unavailable", "bank_timeout"], [.5, .25, .25])[0],
                                       created)
            msg = f"Injected a {method.upper()} outage: {n} payments from different customers in the last 30 minutes, ~90% failing with gateway/bank errors."
        else:
            raise ValueError("kind must be 'card_testing' or 'outage'")
        self.db.add(SimEvent(user_id=self.user_id, kind="incident", message=msg))
        self.db.commit()
        return {"kind": kind, "message": msg}

    def create_failed_batch(self, count: int) -> dict:
        """Sample `count` failed payments from the world's failure mix (reasons depend on method)."""
        count = max(1, min(int(count), 200))
        cases = world.generate_cases(count, random.randint(1, 10 ** 9), world.BASE_WORLD)
        customers = [c for c in self.db.query(SimCustomer).filter_by(user_id=self.user_id).all()
                     if not c.email.startswith(("probe.", "shopper"))] or [self._new_customer("Simulated Customer", "simulated.customer@example.com")]
        now = datetime.utcnow()
        for c in cases:
            created = now - timedelta(minutes=random.uniform(1, 14 * 24 * 60))   # spread over two weeks: no artificial bursts
            self._add_failed_or_ok(random.choice(customers), round(c.amount, 2), c.method, True, c.reason or "unknown_error", created)
        self.db.add(SimEvent(user_id=self.user_id, kind="batch", message=f"Generated {count} failed payments from the failure-mix model."))
        self.db.commit()
        return {"created": count}
