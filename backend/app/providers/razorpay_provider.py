"""
RazorpayProvider — the ONLY place in the codebase that talks to the real
Razorpay API. It is instantiated per-request in providers/factory.py using
the authenticated user's decrypted credentials, and the decrypted secret
never leaves this module (it's handed straight to the razorpay SDK client
and discarded).

Uses the official `razorpay` Python SDK against https://api.razorpay.com/v1
per Razorpay's documented authentication (HTTP Basic Auth with
key_id:key_secret) — see https://razorpay.com/docs/api/.
"""
from datetime import datetime, timedelta

import razorpay
from razorpay.errors import BadRequestError, GatewayError, ServerError

from app.providers.base import DataProvider


class RazorpayAPIError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _normalize_payment(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "order_id": p.get("order_id"),
        "amount": (p.get("amount") or 0) / 100,
        "currency": p.get("currency", "INR"),
        "status": p.get("status"),
        "method": p.get("method"),
        "email": p.get("email"),
        "contact": p.get("contact"),
        "created_at": datetime.utcfromtimestamp(p["created_at"]).isoformat() if p.get("created_at") else None,
        "captured": bool(p.get("captured")),
        "refund_status": p.get("refund_status"),
        "failure_reason": p.get("error_description"),
        "source": "live",
    }


def _normalize_order(o: dict) -> dict:
    return {
        "id": o.get("id"),
        "amount": (o.get("amount") or 0) / 100,
        "currency": o.get("currency", "INR"),
        "status": o.get("status"),
        "attempts": o.get("attempts", 0),
        "created_at": datetime.utcfromtimestamp(o["created_at"]).isoformat() if o.get("created_at") else None,
        "source": "live",
    }


def _normalize_refund(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "payment_id": r.get("payment_id"),
        "amount": (r.get("amount") or 0) / 100,
        "status": r.get("status", "processed"),
        "created_at": datetime.utcfromtimestamp(r["created_at"]).isoformat() if r.get("created_at") else None,
        "source": "live",
    }


def _normalize_customer(c: dict) -> dict:
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "email": c.get("email"),
        "contact": c.get("contact"),
        "created_at": datetime.utcfromtimestamp(c["created_at"]).isoformat() if c.get("created_at") else None,
        "source": "live",
    }


def _normalize_settlement(s: dict) -> dict:
    return {
        "id": s.get("id"),
        "amount": (s.get("amount") or 0) / 100,
        "fees": (s.get("fees") or 0) / 100,
        "status": s.get("status", "processed"),
        "settled_at": datetime.utcfromtimestamp(s["created_at"]).isoformat() if s.get("created_at") else None,
        "source": "live",
    }


def _normalize_dispute(d: dict) -> dict:
    return {
        "id": d.get("id"),
        "payment_id": d.get("payment_id"),
        "amount": (d.get("amount") or 0) / 100,
        "status": d.get("status", "open"),
        "reason": (d.get("reason_code") or d.get("respond_by") or "unspecified"),
        "created_at": datetime.utcfromtimestamp(d["created_at"]).isoformat() if d.get("created_at") else None,
        "source": "live",
    }


class RazorpayProvider(DataProvider):
    def __init__(self, key_id: str, key_secret: str):
        self.client = razorpay.Client(auth=(key_id, key_secret))

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BadRequestError as e:
            raise RazorpayAPIError(f"Razorpay rejected the request: {e}", 400)
        except (GatewayError, ServerError) as e:
            raise RazorpayAPIError("Razorpay is temporarily unavailable. Please try refreshing in a moment.", 502)
        except Exception as e:
            msg = str(e)
            if "key_id" in msg.lower() or "authentication" in msg.lower() or "unauthorized" in msg.lower():
                raise RazorpayAPIError("Razorpay authentication failed. Check your Key ID and Key Secret.", 401)
            raise RazorpayAPIError("Unable to reach Razorpay. Please try again.", 502)

    def test_connection(self) -> bool:

        self._call(self.client.payment.all, {"count": 1})
        return True

    def get_payments(self, limit: int = 20, skip: int = 0, status: str | None = None) -> dict:
        params = {"count": min(limit, 100), "skip": skip}
        res = self._call(self.client.payment.all, params)
        items = [_normalize_payment(p) for p in res.get("items", [])]
        if status:
            items = [i for i in items if i["status"] == status]
        return {"items": items, "count": res.get("count", len(items)), "has_more": len(items) == limit}

    def get_payment(self, payment_id: str) -> dict | None:
        try:
            p = self._call(self.client.payment.fetch, payment_id)
            return _normalize_payment(p)
        except RazorpayAPIError:
            return None

    def get_orders(self, limit: int = 20, skip: int = 0) -> dict:
        res = self._call(self.client.order.all, {"count": min(limit, 100), "skip": skip})
        items = [_normalize_order(o) for o in res.get("items", [])]
        return {"items": items, "count": res.get("count", len(items)), "has_more": len(items) == limit}

    def get_order(self, order_id: str) -> dict | None:
        try:
            o = self._call(self.client.order.fetch, order_id)
            return _normalize_order(o)
        except RazorpayAPIError:
            return None

    def get_refunds(self, limit: int = 20, skip: int = 0) -> dict:
        res = self._call(self.client.refund.all, {"count": min(limit, 100), "skip": skip})
        items = [_normalize_refund(r) for r in res.get("items", [])]
        return {"items": items, "count": res.get("count", len(items)), "has_more": len(items) == limit}

    def get_customers(self, limit: int = 20, skip: int = 0) -> dict:
        try:
            res = self._call(self.client.customer.all, {"count": min(limit, 100), "skip": skip})
            items = [_normalize_customer(c) for c in res.get("items", [])]
            return {"items": items, "count": res.get("count", len(items)), "has_more": len(items) == limit}
        except RazorpayAPIError:

            return {"items": [], "count": 0, "has_more": False, "unavailable": True}

    def get_settlements(self, limit: int = 20, skip: int = 0) -> dict:
        try:
            res = self._call(self.client.settlement.all, {"count": min(limit, 100), "skip": skip})
            items = [_normalize_settlement(s) for s in res.get("items", [])]
            return {"items": items, "count": res.get("count", len(items)), "has_more": len(items) == limit}
        except RazorpayAPIError:

            return {"items": [], "count": 0, "has_more": False, "unavailable": True}

    def get_disputes(self, limit: int = 20, skip: int = 0) -> dict:
        try:
            res = self._call(self.client.dispute.all, {"count": min(limit, 100), "skip": skip})
            items = [_normalize_dispute(d) for d in res.get("items", [])]
            return {"items": items, "count": res.get("count", len(items)), "has_more": len(items) == limit}
        except RazorpayAPIError:

            return {"items": [], "count": 0, "has_more": False, "unavailable": True}

    def get_analytics(self, days: int = 14) -> dict:
        res = self._call(self.client.payment.all, {"count": 100})
        items = [_normalize_payment(p) for p in res.get("items", [])]
        cutoff = datetime.utcnow() - timedelta(days=days)
        in_range = [i for i in items if i["created_at"] and datetime.fromisoformat(i["created_at"]) >= cutoff]

        captured = [i for i in in_range if i["status"] == "captured"]
        failed = [i for i in in_range if i["status"] == "failed"]
        refunded_amount = sum(i["amount"] for i in in_range if i.get("refund_status") in ("full", "partial"))

        series: dict[str, float] = {}
        for i in in_range:
            day = i["created_at"][:10]
            series[day] = series.get(day, 0) + (i["amount"] if i["status"] == "captured" else 0)

        methods: dict[str, int] = {}
        for i in in_range:
            m = i.get("method") or "unknown"
            methods[m] = methods.get(m, 0) + 1

        total = len(in_range) or 1
        return {
            "total_revenue": sum(i["amount"] for i in captured),
            "total_payments": len(in_range),
            "success_rate": round(len(captured) / total * 100, 2),
            "failed_payments": len(failed),
            "refunded_amount": refunded_amount,
            "revenue_series": [{"date": d, "amount": a} for d, a in sorted(series.items())],
            "method_breakdown": [{"method": m, "count": c} for m, c in methods.items()],
        }

    def search_transactions(self, query: str, limit: int = 20) -> dict:
        q = query.strip()

        if q.startswith("pay_"):
            p = self.get_payment(q)
            return {"items": [p] if p else [], "count": 1 if p else 0, "has_more": False}
        if q.startswith("order_"):
            o = self.get_order(q)
            return {"items": [o] if o else [], "count": 1 if o else 0, "has_more": False}

        res = self._call(self.client.payment.all, {"count": 100})
        items = [_normalize_payment(p) for p in res.get("items", [])]
        ql = q.lower()
        matched = [
            i for i in items
            if ql in (i.get("email") or "").lower()
            or ql in (i.get("contact") or "")
            or ql in (i.get("status") or "")
            or ql in (i.get("method") or "")
        ][:limit]
        return {"items": matched, "count": len(matched), "has_more": False}

    def create_test_payment(self, **kwargs) -> dict:
        raise RazorpayAPIError("Cannot create simulated data while connected to Razorpay Client / Live Mode.", 400)

    def create_payment_link(self, amount: float, currency: str, description: str,
                             customer_email: str | None, customer_contact: str | None) -> dict:
        """
        Real Razorpay Payment Links API call. This is the actual mechanism
        Live Mode uses to "recover" a failed payment — Razorpay has no API
        to replay/retry a declined payment on the merchant's behalf, so the
        legitimate recovery action is generating a fresh payment link for
        the customer to complete. If the account/API doesn't support it
        (permissions, plan), this raises and the caller must represent the
        action as "prepared" rather than claim it happened.
        """
        payload = {
            "amount": int(round(amount * 100)),
            "currency": currency,
            "description": description,
            "customer": {},
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
        }
        if customer_email:
            payload["customer"]["email"] = customer_email
        if customer_contact:
            payload["customer"]["contact"] = customer_contact

        link = self._call(self.client.payment_link.create, payload)
        return {"id": link.get("id"), "short_url": link.get("short_url"), "status": link.get("status")}
