"""
The tool layer the AI agent is allowed to call. Every tool routes through
get_provider(user, db) — the same environment-routed Live/Test provider the
dashboard uses — so the agent can never hallucinate numbers, never issue
raw HTTP requests against Razorpay directly, and never see the Razorpay
Key Secret (it isn't passed anywhere near this module).
"""
from sqlalchemy.orm import Session

from app.models import User
from app.providers.factory import get_provider

TOOL_SPECS = [
    {
        "name": "get_payments",
        "description": "List recent payments in the active environment, optionally filtered by status "
                        "(created, authorized, captured, failed, refunded).",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Optional payment status filter."},
                "limit": {"type": "integer", "description": "Max results, default 20."},
            },
        },
    },
    {
        "name": "get_failed_payments",
        "description": "List recent failed payments.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "get_orders",
        "description": "List recent orders.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "get_refunds",
        "description": "List recent refunds.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "get_customers",
        "description": "List customers known in the active environment.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "get_settlements",
        "description": "List recent settlements (bank payouts) including fees.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "get_disputes",
        "description": "List recent disputes/chargebacks.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "get_revenue_summary",
        "description": "Get revenue, success rate, failed-payment count, refunded amount, and a daily revenue "
                        "series for the trailing N days.",
        "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "description": "default 14"}}},
    },
    {
        "name": "search_transactions",
        "description": "Search payments by id, email, phone, status, or method.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "get_payment_by_id",
        "description": "Fetch a single payment by its exact payment id.",
        "input_schema": {"type": "object", "properties": {"payment_id": {"type": "string"}}, "required": ["payment_id"]},
    },
    {
        "name": "get_recovery_cases",
        "description": "List AI Revenue Recovery cases (failed payments being diagnosed/recovered), optionally "
                        "filtered by status: failed, analyzing, pending_approval, approved, recovering, "
                        "recovered, rejected, suppressed, exhausted, manual_review.",
        "input_schema": {"type": "object", "properties": {
            "status": {"type": "string"}, "limit": {"type": "integer"},
        }},
    },
    {
        "name": "get_recovery_metrics",
        "description": "Get the revenue recovery funnel: revenue at risk, attempted, recovered, recovery rate, "
                        "cases awaiting human approval.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def run_tool(name: str, tool_input: dict, user: User, db: Session) -> dict:
    provider = get_provider(user, db)

    if name == "get_payments":
        return provider.get_payments(limit=tool_input.get("limit", 20), status=tool_input.get("status"))
    if name == "get_failed_payments":
        return provider.get_payments(limit=tool_input.get("limit", 20), status="failed")
    if name == "get_orders":
        return provider.get_orders(limit=tool_input.get("limit", 20))
    if name == "get_refunds":
        return provider.get_refunds(limit=tool_input.get("limit", 20))
    if name == "get_customers":
        return provider.get_customers(limit=tool_input.get("limit", 20))
    if name == "get_settlements":
        return provider.get_settlements(limit=tool_input.get("limit", 20))
    if name == "get_disputes":
        return provider.get_disputes(limit=tool_input.get("limit", 20))
    if name == "get_revenue_summary":
        return provider.get_analytics(days=tool_input.get("days", 14))
    if name == "search_transactions":
        return provider.search_transactions(tool_input.get("query", ""))
    if name == "get_payment_by_id":
        result = provider.get_payment(tool_input.get("payment_id", ""))
        return result or {"error": "not_found"}
    if name == "get_recovery_cases":
        from app.models import RecoveryCase
        q = db.query(RecoveryCase).filter_by(user_id=user.id)
        status = tool_input.get("status")
        if status:
            q = q.filter_by(status=status)
        rows = q.order_by(RecoveryCase.updated_at.desc()).limit(tool_input.get("limit", 20)).all()
        return {"items": [
            {"id": c.id, "payment_id": c.payment_id, "amount": c.amount, "category": c.category,
             "status": c.status, "recommended_action": c.recommended_action,
             "recovery_probability": c.recovery_probability, "retry_count": c.retry_count}
            for c in rows
        ], "count": q.count()}
    if name == "get_recovery_metrics":
        from app.recovery.engine import get_metrics
        return get_metrics(user, db)

    return {"error": f"unknown tool: {name}"}
