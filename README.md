# Reparo AI

Your intelligent Razorpay operations command center — an **AI Revenue
Recovery Agent** built for the Razorpay Buildathon Track 03. Detects
revenue at risk, diagnoses why a payment failed, decides and executes a
bounded recovery strategy (retry, payment link, customer communication)
with human approval where it touches a customer, follows up on a cooldown
schedule, verifies the outcome against real payment/webhook data, stops
itself when it should, and keeps a full audit trail — on top of a Harry
Potter–inspired landing experience and a professional teal Revenue Recovery
Console, with a real Razorpay Live integration and a stateful Test Mode
sandbox.

Stack: **FastAPI + SQLAlchemy + SQLite** (backend), **Next.js 14 (App Router) +
TypeScript + Tailwind** (frontend). LLM provider: **Groq**, with a
deterministic rule-based fallback throughout the application, so both the
agent and the recovery pipeline work with zero external API keys.

## The Revenue Recovery pipeline

`app/recovery/` implements the full loop end to end:

1. **Detector** — scans failed payments from the active `DataProvider`, opens a `RecoveryCase`
2. **Classifier** — deterministic rules (`app/recovery/rules.py`) sort the failure into soft decline / technical / hard decline / unknown
3. **Risk Assessment** — recovery probability + expected recovered value; below a configurable threshold, the case is suppressed rather than pursued
4. **Strategy** — retry, request a new payment method, or manual review
5. **Timing** — configurable wait windows per category (`RECOVERY_*_RETRY_HOURS`)
6. **Communication** — drafts a short recovery message (Groq if `GROQ_API_KEY` is set, deterministic template otherwise); each message is logged in `RecoveryCommunication` with type (recovery notification / follow-up reminder / escalation / confirmation) and status (sent / simulated / failed) — never claimed as delivered unless SMTP actually sent it
7. **Approval** — silent retries auto-execute within the bounded retry cap; anything that reaches the customer requires explicit human approval via the Recovery Console
8. **Execution** — Test Mode simulates the retry outcome statefully; Live Mode creates a real Razorpay Payment Link (there's no API to replay a declined charge) and represents it honestly as "prepared" until confirmed
9. **Follow-up** — cases move to `waiting`; each scan checks whether the payment already succeeded, respects a cooldown between actions, and sends the next reminder (or retries again) only once the cooldown has elapsed and the per-case caps haven't been hit
10. **Verification** — Test Mode verifies as soon as the payment is captured; Live Mode verifies only when a signed Razorpay webhook confirms it
11. **Stop conditions** — recovered, retry cap reached (`exhausted`), communication cap reached (`exhausted`), recovery window elapsed (`expired`), classified as non-recoverable (`suppressed`), or a reviewer rejects (`suppressed`)
12. **Audit** — every step above is an immutable `RecoveryTraceStep` row, visible in the Recovery Console's case detail panel, alongside the full communication history

**Bounded by design:** `RECOVERY_MAX_RETRIES`, `RECOVERY_MAX_COMMUNICATIONS`, `RECOVERY_COOLDOWN_HOURS`, and `RECOVERY_WINDOW_DAYS` are enforced in `app/recovery/rules.py`, the one choke point every execution path passes through. The LLM is never on the path of a retry-limit, cap, cooldown, or approval decision — only used for prose.

I ran this live: seeded failed payments → scan opened cases with full classification/risk/strategy/timing trace, auto-recovering several via bounded retries (71.7% recovery rate on one run, computed from the case table, not hardcoded) → approved a `pending_approval` hard-decline case → confirmed the first recovery message was drafted and logged (honestly marked "simulated" since no SMTP was configured) → re-scanned repeatedly and confirmed the cooldown genuinely blocks repeat actions → directly forced a recovery-window expiry and confirmed the case moved to `expired` with the correct audit entries.

## What's real and tested here

- Email-OTP signup, JWT sign-in, environment selection persisted per account
- `DataProvider` abstraction: `RazorpayProvider` (real Razorpay API, official SDK, server-only) and `SimulationProvider` (stateful DB-backed sandbox — customers, orders, payments, diverse failure reasons, refunds, settlements, all seeded once per account and then queryable/mutable, never regenerated per page load)
- Razorpay Key Secret encrypted at rest (Fernet), masked key IDs, never sent back to the browser
- Connect/test-connection/disconnect flow validating real credentials against Razorpay before granting dashboard access
- Signed Razorpay webhook receiver with idempotency, feeding both a persisted activity log and the recovery pipeline's Verification step
- Conversational AI agent built on **Groq's OpenAI-compatible tool-calling API**, with tools for payments, orders, refunds, settlements, disputes, and recovery cases/metrics; falls back to a deterministic rule-based responder with zero keys
- **Recovery Console** (`/dashboard`, teal palette `#00586A #004551 #003C47 #00697C #008080`): funnel metrics (revenue at risk, recovered, recovery rate, active cases, awaiting approval, pending follow-ups), priority-sortable case queue with filters including Waiting/Retrying/Exhausted, right-side case detail panel with the full AI trace timeline, customer communication history, and Approve/Reject controls
- Dashboard: Recovery Console / Analytics / Payments / Orders / Refunds / Settlements / Disputes / Customers / AI Agent / Settings
- Landing page, System Design page, Why-to-Use page, Command Center auth flow

## What you'll need to supply to go fully live

- A **real Razorpay Key ID + Key Secret**. Live Mode recovery execution creates a real **Razorpay Payment Link** (`payment_link.create`) — needs the Payment Links API enabled; if it's not, cases are honestly routed to `manual_review` instead of falsely claiming success
- `RAZORPAY_WEBHOOK_SECRET` — required for Live Mode recovery verification; without it, executed Live cases stay in `waiting` until you check manually
- SMTP credentials to actually send recovery messages/reminders/confirmations; without them, every message is drafted, logged, and marked `simulated` rather than pretended-sent
- `GROQ_API_KEY` (+ optionally `GROQ_MODEL`) to upgrade both the conversational agent and recovery message drafting from deterministic templates to full LLM reasoning
- A generated `ENCRYPTION_KEY` for any real deployment

## Known Limitations

- **No automated test suite yet.** The recovery flow, cooldown enforcement, recovery-rate calculation, and expiry handling have been validated through manual end-to-end runs. Automated unit and integration tests would be the next step for regression coverage.

- **No baseline comparison yet.** The recovery rate is currently reported as an observed percentage without comparison against a "do nothing" or naive-retry baseline. Adding these benchmarks would make the incremental impact of the recovery strategy easier to quantify.

- **Risk assessment is currently static.** `risk_assessment()` uses fixed base rates for each failure category with a per-retry decay factor. It does not yet learn from historical recovery outcomes, so risk estimates remain rule-based rather than adapting over time.

- **Webhook replay protection is partial.** The webhook handler verifies the HMAC signature and deduplicates events using `event_id`, but does not currently validate the payload timestamp. Adding timestamp-based freshness validation would provide stronger replay protection.

- **Test Mode verification uses the simulation state.** In Test Mode, verification reads the persisted state maintained by `SimulationProvider`, which is also updated by the simulated recovery action. This provides deterministic end-to-end testing, but does not provide the independent confirmation available in Live Mode through Razorpay webhook events.

- **Single app-wide webhook secret.** The current implementation uses one `RAZORPAY_WEBHOOK_SECRET`. A multi-merchant production deployment would require webhook-secret management at the individual account level.

- **Recovery scan is manually triggered.** `next_action_at` is calculated and enforced as a cooldown, but the current environment does not run a background scheduler to trigger actions automatically. A production deployment would add a scheduled worker or background job.

- **LLM message quality depends on Groq availability and prompting.** When `GROQ_API_KEY` is unavailable, the system safely falls back to deterministic templates. The AI-generated messaging experience therefore depends on the configured LLM provider.

## Running locally

### Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit as needed
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Visit `http://localhost:3000`. Pick **Test Mode** to explore immediately with
no Razorpay credentials and no Groq key — the sandbox seeds itself with
realistic (including failed) payments on first login, and every deterministic
fallback path is exercised automatically. Open the **Recovery Console** and
click **Run Recovery Scan** to watch detect → diagnose → decide → communicate
→ act → follow up → verify → stop play out, then check a case's audit trail
and communication history in the detail panel.
