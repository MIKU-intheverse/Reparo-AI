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



Stack: ****FastAPI + SQLAlchemy + SQLite**** (backend), **Next.js 14 (App Router) +

TypeScript + Tailwind** (frontend), ****scikit-learn / NumPy / SciPy**** (ML layer). LLM provider: ****Groq****, with a

deterministic rule-based fallback throughout the application, so both the

agent and the recovery pipeline work with zero external API keys.



****New: an ML layer**** that makes the recovery engine measurably smarter **without** loosening any guardrail — a calibrated

recovery-probability model with per-case explanations, a Thompson-sampling bandit that learns when to retry, and anomaly

detection that puts suspected card-testing on a security hold and defers retries during payment-method outages.

It is evaluated against baselines with confidence intervals, tested (79 tests incl. guardrail property tests and mutation-checked

safety tests), and every component falls back to the original rules. See [****The ML layer****](#the-ml-layer) and

[`docs/ML_DESIGN.md`](docs/ML_DESIGN.md).



## The Revenue Recovery pipeline**



`app/recovery/` implements the full loop end to end:



1\. ****Detector**** — scans failed payments from the active `DataProvider`, opens a `RecoveryCase`

2\. ****Classifier**** — deterministic rules (`app/recovery/rules.py`) sort the failure into soft decline / technical / hard decline / unknown

3\. ****Security screen**** **(ML)** — an Isolation Forest over per-customer velocity features puts suspected ****card testing**** on a `security_hold`: no retry, no message, until a human releases or confirms

3\. ****Risk Assessment**** **(ML)** — a calibrated gradient-boosted model estimates recovery probability and expected recovered value (with a per-case explanation of **why**); below a configurable threshold, the case is suppressed rather than pursued. Falls back to the static category score if the model is unavailable

4\. ****Strategy**** — retry, request a new payment method, or manual review

5\. ****Timing**** **(ML)** — a Thompson-sampling bandit learns the best retry delay per failure reason, ****inside**** the cooldown and recovery-window limits; falls back to the configurable per-category windows (`RECOVERY_*_RETRY_HOURS`). During a detected payment-method ****outage****, retries are deferred without consuming the retry budget

6\. ****Communication**** — drafts a short recovery message (Groq if `GROQ_API_KEY` is set, deterministic template otherwise); each message is logged in `RecoveryCommunication` with type (recovery notification / follow-up reminder / escalation / confirmation) and status (sent / simulated / failed) — never claimed as delivered unless SMTP actually sent it

7\. ****Approval**** — silent retries auto-execute within the bounded retry cap; anything that reaches the customer requires explicit human approval via the Recovery Console

8\. ****Execution**** — Test Mode simulates the retry outcome statefully; Live Mode creates a real Razorpay Payment Link (there's no API to replay a declined charge) and represents it honestly as "prepared" until confirmed

9\. ****Follow-up**** — cases move to `waiting`; each scan checks whether the payment already succeeded, respects a cooldown between actions, and sends the next reminder (or retries again) only once the cooldown has elapsed and the per-case caps haven't been hit

10\. ****Verification**** — Test Mode verifies as soon as the payment is captured; Live Mode verifies only when a signed Razorpay webhook confirms it

11\. ****Stop conditions**** — recovered, retry cap reached (`exhausted`), communication cap reached (`exhausted`), recovery window elapsed (`expired`), classified as non-recoverable (`suppressed`), or a reviewer rejects (`suppressed`)

12\. ****Audit**** — every step above is an immutable `RecoveryTraceStep` row, visible in the Recovery Console's case detail panel, alongside the full communication history



****Bounded by design:**** `RECOVERY_MAX_RETRIES`, `RECOVERY_MAX_COMMUNICATIONS`, `RECOVERY_COOLDOWN_HOURS`, and `RECOVERY_WINDOW_DAYS` are enforced in `app/recovery/rules.py`, the one choke point every execution path passes through. The LLM is never on the path of a retry-limit, cap, cooldown, or approval decision — only used for prose.



****How this is verified.**** The flow is covered by an automated suite (see [Tests](#tests)): scan → classify → score → schedule → retry →

verify → stop, cooldown enforcement, expiry, approval gating, security holds and their release/confirm paths, outage deferral and

resumption, and property tests that run many scan/time-travel cycles and assert the retry and message caps are never exceeded. Test

Mode also supports a fast-forward clock so scheduled retries come due in seconds.



> An earlier version of this README quoted a single-run "71.7% recovery rate". That number was a property of the sandbox's flat

> success probabilities, not evidence of anything, so it has been replaced by the baseline-controlled evaluation below.



## The ML layer**



All code is in `backend/app/ml/`; the engine reaches it only through `app/ml/service.py`, which is fail-safe (any error ⇒ the

original rule-based behaviour). Set `ML_ENABLED=false` to run the original engine exactly.



| Component | What it does | Method | Where to see it |

|---|---|---|---|

| ****Recovery model**** | P(recovered within window \| case state); drives suppression, expected value, review-queue ranking | Monotonic-constrained gradient boosting + Platt/isotonic calibration; time-ordered case-level splits; group attribution for explanations | ML Insights → **Recovery model**; every case's **Why X% recoverable** panel |

| ****Retry-timing bandit**** | Learns how long to wait before each silent retry, per failure reason | Thompson sampling over Beta posteriors; arms filtered by `rules.allowed_delay_arms`; rewards only for retries that ran | ML Insights → **Retry timing**; case **Learned retry timing** panel |

| ****Card-testing detector**** | Holds bursts of small failing payments for human review | Isolation Forest (unsupervised, benign-only) + minimum-evidence guard | ML Insights → **Security**; Recovery Console filter **Security Hold** |

| ****Outage detector**** | Defers retries into a failing payment method | Exact binomial test vs the method's own baseline (time + last-K windows) | ML Insights → **Security**; traces show **Retry deferred** |

| ****Offline evaluation**** | Compares policies with 95% CIs, incl. a drifted world | Common-random-number replay, bootstrap | ML Insights → **Policy evaluation** |

| ****Real-data checks**** | Sanity-checks the simulator's amount spread and stress-tests the card-testing detector for false positives on ****real customer activity**** | UCI **Online Retail** transactions (bundled 1-week sample; full file via `--path`) — real invoices, but ****no failures or recovery outcomes**** | ML Insights → **Security** ("Real-data check"); `python -m app.ml.realdata` |

| ****Industry reality check**** | Compares the simulator to published industry recovery rates and failure mix, and adds a **conservative** world calibrated to them | Cited vendor statistics in `app/ml/data/industry_benchmarks.json` | ML Insights → **Policy evaluation** |

| ****Decision log**** | Features + model version + outcome for every ML decision; feeds retraining and bandit rewards | `ml_decisions`, `bandit_arms`, `ml_alerts` tables | ML Insights header; `python -m app.ml.train --from-db` |



****Results**** (6,000 simulated failed payments, same draws for every policy; net = recovered revenue − retry/message/review costs;

all numbers reproducible with `python -m app.ml.evaluate`):



| Policy | Recovery rate | Net ₹ per failed payment (95% CI) |

|---|---|---|

| Do nothing | 18.3% | 515 [468, 560] |

| Naive retry | 67.0% | 1,816 [1,736, 1,893] |

| Rules (the engine before ML) | 77.3% | 2,098 [2,016, 2,189] |

| Rules + risk model | 77.3% | 2,098 [2,019, 2,183] |

| ****Rules + risk model + learned timing**** | ****81.7%**** | ****2,243 [2,160, 2,331]**** |



* Full ML policy vs rules: ****+₹145 per failed payment (+6.9%), 95% CI [+115, +177]****; in a **shifted** world whose dynamics differ from

  the training world: ****+₹136 [+104, +170]****.

* ****Conservative world**** (calibrated to published industry recovery rates, see below): rules recover ****38.7%****, the full ML policy ****43.7%****;

  ****+₹134 per failed payment (+13.8%), CI [+106, +163]**** — the lift does not depend on the base world's optimism.

* Risk model vs the old static score on held-out data: ****AUC 0.780 vs 0.695, Brier 0.187 vs 0.232, calibration error 1.4% vs 12.9%****

  (logistic regression is within 0.003 AUC of boosting — the simulated world is smooth).

* Card-testing detector: 100% recall at 0.5% false positives on synthetic attacks (a simple signature rule gets 93.9% / 0%); outage

  detector: 72% recall pooled (89% on busy methods), 30 min median delay, \~0 false-alarm episodes per month.



****Real data, and why the base world is not the whole story****



* ****No public dataset of failed payments with recovery outcomes exists**** (processors keep them private; only vendor aggregates are published).

  So the recovery model and the policy comparison cannot be trained or scored on real recoveries. This README does not pretend otherwise.

* ****What&#x20;**_*is*_**&#x20;real and bundled:**** a one-week slice of the UCI **Online Retail** transactions (552 invoices, 413 customers; attribution in

  `backend/app/ml/data/DATA_LICENSE.md`). It is used for two honest purposes only: (1) the real invoice-total spread (log-sd ****1.10****) is close to the

  simulator's assumption (****1.0****); (2) a false-positive stress test of the card-testing detector on real customer behaviour — if ****every****

  real attempt failed, 4.7% of windows (4 wholesale customers placing many invoices within minutes) would be held; at a realistic 12% failure rate,

  ****0 holds in 25 random draws****. It has no fraud labels, so it says nothing about recall on real fraud.

* ****What is published:**** vendor figures — insufficient funds ≈ 40.5% of subscription failures (Churnkey–Stripe), recovery of 25–35% on audited B2C

  accounts (Redux) up to \~55% (Stripe's claim). They are unaudited, subscription-card figures, not Razorpay/UPI. They exposed a real problem:

  the base world's rules baseline recovers ****77%****, well above that band. Hence the ****conservative world**** — one global shift plus a lower

  unaided-payment rate, chosen **only** so the rules baseline lands inside the published band (no ML policy was used). Sources and caveats:

  `app/ml/data/industry_benchmarks.json`.



****What these numbers do and do not mean**** — please read:



* There is ****no public payment-recovery dataset****. The models are trained, and the policies compared, inside a documented, stylised

  simulator (`app/ml/world.py`). The results validate the machinery and show **why** each component helps; they are ****not**** a forecast of

  production uplift. `ml_decisions` logs features and outcomes so the same code retrains on real data (`--from-db`).

* The ****risk model adds nothing when reviewers are not a bottleneck**** (lift 0.0 at 8 reviews/day). It helps when capacity is scarce:

  +₹148/case at 2 reviews/day, +₹121 at 4. The evaluation page shows the full sweep.

* The bandit ****trades speed for success****: mean time to recovery rises from 14.8h to 41.8h.

* On a cold start the bandit explores, so early first retries may wait hours. In Test Mode use ****+24H & SCAN**** or the one-click

  ****Run learning demo**** (ML Insights → **Retry timing**) to watch it converge on the sandbox ground truth.



****Guardrails**** (unchanged, and not inputs to any model): `RECOVERY_MAX_RETRIES`, `RECOVERY_MAX_COMMUNICATIONS`, `RECOVERY_COOLDOWN_HOURS`,

`RECOVERY_WINDOW_DAYS`, and human approval for anything customer-facing. ML output is sanitised (`rules.guard_probability`,

`rules.allowed_delay_arms`) before it can influence a case.



****ML-specific hardening****: model artifacts are verified against a SHA-256 manifest **before** deserialisation (joblib is pickle); a

feature-semantics fingerprint refuses models trained on different feature engineering; free text never reaches a model; a security hold

only pauses automation and can be released by a human. Threat model in [`docs/ML_DESIGN.md`](docs/ML_DESIGN.md#7-security-considerations-specific-to-the-ml-layer).



****Reproduce****



```bash

cd backend

python -m app.ml.train                                                            # risk model + model card

python -c "from app.ml.anomaly import AnomalyModel; AnomalyModel.train_and_save(quiet=False)"

python -m app.ml.evaluate                                                         # policy comparison (3 worlds) -> artifacts/eval_report.json

python -m app.ml.realdata                                                         # real-data checks (add --path Online_Retail.csv for the full UCI file)

python -m app.ml.train --from-db                                                  # retrain with logged production outcomes

```



Trained artifacts are committed (`app/ml/artifacts/`) so everything works out of the box; if they can't be loaded (different

scikit-learn version, tampering) the app retrains in-process or falls back to rules.



## What's real and tested here**



- Email-OTP signup, JWT sign-in, environment selection persisted per account

- `DataProvider` abstraction: `RazorpayProvider` (real Razorpay API, official SDK, server-only) and `SimulationProvider` (stateful DB-backed sandbox — customers, orders, payments, diverse failure reasons, refunds, settlements, all seeded once per account and then queryable/mutable, never regenerated per page load)

- Razorpay Key Secret encrypted at rest (Fernet), masked key IDs, never sent back to the browser

- Connect/test-connection/disconnect flow validating real credentials against Razorpay before granting dashboard access

- Signed Razorpay webhook receiver with idempotency, feeding both a persisted activity log and the recovery pipeline's Verification step

- Conversational AI agent built on ****Groq's OpenAI-compatible tool-calling API****, with tools for payments, orders, refunds, settlements, disputes, and recovery cases/metrics; falls back to a deterministic rule-based responder with zero keys

- ****Recovery Console**** (`/dashboard`, teal palette `#00586A #004551 #003C47 #00697C #008080`): funnel metrics (revenue at risk, recovered, recovery rate, active cases, awaiting approval, pending follow-ups), priority-sortable case queue with filters including Waiting/Retrying/Exhausted, right-side case detail panel with the full AI trace timeline, customer communication history, and Approve/Reject controls

- ****ML Insights**** (`/dashboard/ml`): model card with held-out metrics vs baselines and a reliability diagram; policy evaluation with CIs, ablation, learning curve, capacity sweep and a shifted-world run (re-runnable from the UI); the bandit's learned posteriors next to sandbox ground truth; anomaly alerts with one-click sandbox incidents (card-testing burst, UPI outage); and a live ****what-if scorer****

- Recovery Console additions: **Security Hold** queue with release/confirm, per-case **why this score** and **learned timing** panels, ****+24H & SCAN**** fast-forward (Test Mode)

- Dashboard: Recovery Console / ML Insights / Analytics / Payments / Orders / Refunds / Settlements / Disputes / Customers / AI Agent / Settings

- Landing page, System Design page, Why-to-Use page, Command Center auth flow



## What you'll need to supply to go fully live**



- A ****real Razorpay Key ID + Key Secret****. Live Mode recovery execution creates a real ****Razorpay Payment Link**** (`payment_link.create`) — needs the Payment Links API enabled; if it's not, cases are honestly routed to `manual_review` instead of falsely claiming success

- `RAZORPAY_WEBHOOK_SECRET` — required for Live Mode recovery verification; without it, executed Live cases stay in `waiting` until you check manually

- SMTP credentials to actually send recovery messages/reminders/confirmations; without them, every message is drafted, logged, and marked `simulated` rather than pretended-sent

- `GROQ_API_KEY` (+ optionally `GROQ_MODEL`) to upgrade both the conversational agent and recovery message drafting from deterministic templates to full LLM reasoning

- A generated `ENCRYPTION_KEY` for any real deployment



## Known Limitations

### ML layer

- **Synthetic training/evaluation data.** Results validate the ML pipeline inside a documented simulator, not production performance. Retrain on real payment recovery outcomes before relying on production predictions.
- **Live Mode ML paths are not fully tested against real Razorpay.** They share code with Test Mode, but real-world end-to-end validation requires Razorpay credentials and live transactions.
- **Detector scope.** Card-testing detection uses per-customer one-hour velocity windows, so slow-drip attacks and rotating identities may evade it. Outage detection requires sufficient transaction volume; low-volume methods stay silent by design.
- **No real recovery outcomes yet.** The bundled real transactions contain no payment failures or recovery labels. Real-data checks validate assumptions and false-positive behaviour, not recovery accuracy.
- **Single-tenant retraining.** The risk model is process-wide. Multi-tenant deployments require per-tenant models and isolated outcome data.
- **Tabular bandit context.** Retry timing is learned per failure reason and retry stage. Amount, hour and salary-window context are not yet incorporated. Learning when to retry versus contacting a customer would require randomized logging to avoid bias.
- **Approximate explanations.** Group attributions use interventional resampling and need not sum to the total deviation from the base rate.

### Platform

- **Webhook replay protection is partial.** The webhook handler verifies HMAC signatures and deduplicates events using `event_id`, but does not validate payload timestamps.
- **Test Mode verification uses simulation state.** Verification reads persisted state maintained by `SimulationProvider`, which is also updated by simulated recovery actions and customer responses. This enables deterministic end-to-end testing but does not provide independent confirmation like Live Mode Razorpay webhooks.
- **Single app-wide webhook secret.** The current implementation uses one `RAZORPAY_WEBHOOK_SECRET`. A multi-merchant deployment requires account-level webhook-secret management.
- **Recovery scan is manually triggered.** `next_action_at` is calculated and enforced as a cooldown, but the current environment does not run a background scheduler. Production deployment would add a scheduled worker or background job.
- **LLM message quality depends on Groq availability and prompting.** Without `GROQ_API_KEY`, the application safely falls back to deterministic templates.
- **Default secrets are for development.** Configure real `AUTH_SECRET` and `ENCRYPTION_KEY` values before deployment.

## Datasets Worth Adding Next

The following datasets could further improve validation. Only the Online Retail sample is currently bundled; the other datasets are not wired into the project.

| Dataset | What it could validate | Caveat |
|---|---|---|
| **IEEE-CIS Fraud Detection** (Kaggle) | Card-testing and transaction-fraud detection using card identifiers, timestamps and fraud labels | Requires Kaggle access; fraud labels are not specifically card-testing labels |
| **ULB Credit Card Fraud** (Kaggle/OpenML) | Amount and anomaly behaviour | PCA-anonymised features do not provide customer/card identifiers, so velocity features are unavailable |
| **UCI Online Retail (full)** | Larger real-data false-positive stress test using `python -m app.ml.realdata --path Online_Retail.csv` | Retail invoices, not payment attempts; no payment failures or recovery outcomes |
| **Your own Razorpay export** | Real payment failures and recovery outcomes; retraining with `--from-db` once cases resolve | Requires live transaction traffic and is the only direct source of real recovery labels |

## Tests

Run the backend test suite:

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

The project includes **79 automated tests** covering:

- Simulated-world behaviour, feature schema, train/serve parity and golden values.
- Recovery prediction, calibration, monotonic constraints, explanations, fallbacks and artifact-tamper refusal.
- Thompson-sampling bandit convergence, persistence, guardrail-respecting delays and reward integrity.
- Card-testing and outage detectors, including hard negatives, minimum evidence and low-volume silence.
- Evaluation reproducibility, queue capacity, retry/message caps and outcome labelling.
- End-to-end recovery workflows, security-hold release/confirmation, outage deferral/resumption and bounded execution.
- Backend HTTP API integration.

Safety-critical tests are mutation-checked: deliberately breaking cooldown filters, outage deferral, security holds, reward attribution or feature semantics causes tests to fail. GitHub Actions CI (`.github/workflows/ci.yml`) runs backend tests, a retraining and re-evaluation smoke check, and frontend type-checking and builds.

## Running locally**



### Backend**



```bash

cd backend

python3 -m venv venv && source venv/bin/activate

pip install -r requirements.txt          # includes numpy / scipy / scikit-learn for the ML layer

cp .env.example .env   # edit as needed (all ML options are documented there)

uvicorn app.main:app --reload --port 8000

```



### Frontend**



```bash

cd frontend

npm install

cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http\://localhost:8000

npm run dev

```



Tested with Python 3.12 / Node 20.



Visit `http\://localhost:3000`. Pick ****Test Mode**** to explore immediately with

no Razorpay credentials and no Groq key — the sandbox seeds itself with

realistic (including failed) payments on first login, and every deterministic

fallback path is exercised automatically. Open the ****Recovery Console**** and

click ****Run Recovery Scan**** to watch detect → diagnose → decide → communicate

→ act → follow up → verify → stop play out, then check a case's audit trail

and communication history in the detail panel.



Then open ****ML Insights**** to see the model card and evaluation, hit ****Run learning demo**** on the **Retry timing** tab to watch the bandit

learn, and try the **Security & anomalies** tab: inject a card-testing burst or a UPI outage and see the pipeline respond. Set

`ML_SANDBOX_WORLD=shifted` in `backend/.env` to change the sandbox's ground truth and watch the bandit adapt.
