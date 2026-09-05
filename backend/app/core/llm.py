"""
LLM abstraction used exclusively for prose: explaining a decision in plain
language, or drafting a customer-facing recovery message. It is never on
the path of a safety-critical decision — those all live in
app/recovery/rules.py and are computed before this module is ever called.

Provider: Groq only (per project decision — the Anthropic integration was
replaced). If GROQ_API_KEY is unset, or the call fails for any reason,
callers fall back to their own deterministic text rather than propagating
the error — a missing/invalid API key must never break the recovery
pipeline or the conversational agent.
"""
from app.config import get_settings

settings = get_settings()


def generate(system: str, prompt: str, max_tokens: int = 300) -> str | None:
    if not settings.groq_api_key:
        return None
    try:
        return _groq_generate(system, prompt, max_tokens)
    except Exception:
        return None


def _groq_generate(system: str, prompt: str, max_tokens: int) -> str:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    resp = client.chat.completions.create(
        model=settings.groq_model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()
