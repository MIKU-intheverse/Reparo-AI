import json
import re

from sqlalchemy.orm import Session

from app.agent.tools import TOOL_SPECS, run_tool
from app.config import get_settings
from app.models import User

settings = get_settings()

SYSTEM_PROMPT = (
    "You are the Reparo AI operations agent, embedded in a Razorpay operations dashboard. "
    "You answer questions about payments, orders, refunds, customers and revenue by calling the "
    "provided tools — you never invent figures. Always call a tool before stating any number. "
    "Currency is INR (₹). Be concise and operational, like a finance-ops analyst, not a generic chatbot. "
    "State clearly which environment (Live Razorpay account or Test Mode sandbox) the data came from "
    "if it's relevant."
)


def _openai_style_tools() -> list[dict]:
    """Groq's chat completions API uses OpenAI-style function-calling tool
    definitions rather than Anthropic's input_schema format — convert once."""
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in TOOL_SPECS
    ]


def _groq_chat(message: str, history: list[dict], user: User, db: Session) -> dict:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    messages = [{"role": "system", "content": SYSTEM_PROMPT + f" Active environment: {user.environment}."}]
    messages += history + [{"role": "user", "content": message}]
    tools = _openai_style_tools()
    trace = []

    for _ in range(4):
        resp = client.chat.completions.create(
            model=settings.groq_model,
            max_tokens=1024,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            return {"reply": msg.content or "", "trace": trace}

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = run_tool(tc.function.name, args, user, db)
            trace.append({"tool": tc.function.name, "input": args})
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(result, default=str)[:6000],
            })

    return {"reply": "I gathered the data but ran out of steps summarizing it — try a narrower question.",
            "trace": trace}


def _heuristic_chat(message: str, user: User, db: Session) -> dict:
    """
    Runs with zero external API keys so the agent works out of the box.
    Handles the common operational questions directly against the tool
    layer instead of hallucinating. Set GROQ_API_KEY to upgrade to full
    free-form reasoning via _groq_chat.
    """
    m = message.lower()
    trace = []

    def call(name, **kwargs):
        trace.append({"tool": name, "input": kwargs})
        return run_tool(name, kwargs, user, db)

    if "recover" in m or "at risk" in m or "recovery rate" in m:
        data = call("get_recovery_metrics")
        return {
            "reply": (
                f"Revenue at risk: ₹{data['revenue_at_risk']:.2f} across {data['total_failed_payments']} case(s). "
                f"Recovered: ₹{data['recovered_amount']:.2f} ({data['recovery_rate']}% recovery rate). "
                f"{data['awaiting_approval']} case(s) awaiting your approval."
            ),
            "trace": trace,
        }

    if "failed" in m:
        data = call("get_failed_payments", limit=10)
        if not data["items"]:
            return {"reply": "No failed payments in the recent window.", "trace": trace}
        lines = [f"• {p['id']} — ₹{p['amount']:.2f} via {p['method']} ({p.get('failure_reason') or 'unknown reason'})"
                 for p in data["items"][:10]]
        return {"reply": f"Found {data['count']} recent failed payment(s):\n" + "\n".join(lines), "trace": trace}

    if "revenue" in m or "how much" in m or "summary" in m:
        days = 1 if "today" in m or "yesterday" in m else (7 if "week" in m else 14)
        data = call("get_revenue_summary", days=days)
        return {
            "reply": (
                f"Over the last {days} day(s): revenue ₹{data['total_revenue']:.2f} from "
                f"{data['total_payments']} payment(s), {data['success_rate']}% success rate, "
                f"{data['failed_payments']} failed, ₹{data['refunded_amount']:.2f} refunded."
            ),
            "trace": trace,
        }

    if "refund" in m:
        data = call("get_refunds", limit=10)
        if not data["items"]:
            return {"reply": "No refunds on record.", "trace": trace}
        lines = [f"• {r['id']} — ₹{r['amount']:.2f} ({r['status']})" for r in data["items"][:10]]
        return {"reply": f"{data['count']} refund(s) on record:\n" + "\n".join(lines), "trace": trace}

    pay_id = re.search(r"(pay_[A-Za-z0-9]+)", message)
    if pay_id:
        result = call("get_payment_by_id", payment_id=pay_id.group(1))
        if result.get("error"):
            return {"reply": f"Couldn't find payment {pay_id.group(1)}.", "trace": trace}
        return {"reply": f"{result['id']}: ₹{result['amount']:.2f}, status {result['status']}, "
                          f"method {result.get('method')}, created {result['created_at']}.", "trace": trace}

    if "settlement" in m or "payout" in m:
        data = call("get_settlements", limit=10)
        if not data["items"]:
            return {"reply": "No settlements on record.", "trace": trace}
        lines = [f"• {s['id']} — ₹{s['amount']:.2f} net (₹{s['fees']:.2f} fees), {s['status']}" for s in data["items"][:10]]
        return {"reply": f"{data['count']} settlement(s) on record:\n" + "\n".join(lines), "trace": trace}

    if "dispute" in m or "chargeback" in m:
        data = call("get_disputes", limit=10)
        if not data["items"]:
            return {"reply": "No disputes on record.", "trace": trace}
        lines = [f"• {d['id']} — ₹{d['amount']:.2f} ({d['status']}, {d['reason']})" for d in data["items"][:10]]
        return {"reply": f"{data['count']} dispute(s) on record:\n" + "\n".join(lines), "trace": trace}

    if "order" in m:
        data = call("get_orders", limit=10)
        lines = [f"• {o['id']} — ₹{o['amount']:.2f} ({o['status']})" for o in data["items"][:10]]
        return {"reply": f"{data['count']} recent order(s):\n" + "\n".join(lines) if lines else "No orders yet.",
                "trace": trace}

    if "customer" in m:
        data = call("get_customers", limit=10)
        lines = [f"• {c.get('name') or c.get('email')}" for c in data["items"][:10]]
        return {"reply": f"{data['count']} customer(s):\n" + "\n".join(lines) if lines else "No customers yet.",
                "trace": trace}

    data = call("get_revenue_summary", days=14)
    return {
        "reply": (
            "I can help with payments, orders, refunds, customers and revenue. Here's a quick pulse of the "
            f"last 14 days: ₹{data['total_revenue']:.2f} revenue, {data['success_rate']}% success rate. "
            "Try asking things like \"show me today's failed payments\" or \"what was my revenue this week\"."
        ),
        "trace": trace,
    }


def chat(message: str, history: list[dict], user: User, db: Session) -> dict:
    if settings.groq_api_key:
        try:
            return _groq_chat(message, history, user, db)
        except Exception:
            pass
    return _heuristic_chat(message, user, db)
