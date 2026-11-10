# ML layer — design notes

This document explains **what the ML layer does, why it is built the way it is, how it was evaluated, and
where it can fail.** Code lives in `backend/app/ml/`; the engine talks to it only through
`app/ml/service.py`.

## 1. Goals and non-goals

**Goals**

1. Replace the static, rule-of-thumb parts of recovery with *learned* components that are measurable:
   a calibrated recovery-probability model, learned retry timing, and anomaly detection.
2. Keep every decision **inside deterministic guardrails** and **fail-safe** (ML off, missing or broken ⇒ the
   original rule-based engine runs unchanged).
3. Make every ML decision **auditable and reproducible**: features, model version, and outcome are logged.
4. Be honest about what the evidence does and does not show.

**Non-goals**: replacing the guardrails with a model, putting an LLM on any limit/approval decision, claiming
production accuracy from synthetic data.

## 2. Architecture

```
                         ┌────────────────────── Recovery engine (app/recovery/engine.py) ─────────────────────┐
 failed payment ─► detect ─► classify ─► SECURITY SCREEN ─► RISK SCORE ─► strategy ─► TIMING ─► approval ─► execute ─► verify
                                            │ hold?             │ p, why        │            │ delay                    │ outcome
                                            ▼                   ▼               ▼            ▼                          ▼
                                    ┌───────────────────────── app/ml/service.py (facade, fail-safe) ─────────────────────────┐
                                    │  anomaly.py        risk_model.py + features.py        bandit.py          context.py       │
                                    │  Isolation Forest  GBM + calibration + attribution    Thompson sampling  1 payment snapshot│
                                    │  binomial outage   (one feature schema, fingerprinted) Beta posteriors   per scan          │
                                    └──────────────┬────────────────────────────────────────────────────────────────────────────┘
                                                   ▼
                              ml_decisions (features + model version + outcome)   bandit_arms   ml_alerts      ← new tables
                                                   ▲
              rules.py  ── guard_probability / allowed_delay_arms / caps / cooldown / window / approvals ── final authority
```

Offline: `world.py` (generative simulator) → `episodes.py` (policies) → `train.py` / `evaluate.py` → `artifacts/`.

## 3. Components

### 3.1 Recovery-probability model (`risk_model.py`, `features.py`)

*Question answered:* "What is the probability this payment is eventually recovered inside the window, given the case's
current state?" — used to suppress hopeless cases, to rank the human review queue by **expected recovered value**
(amount × probability), and to explain the score.

* **Features** (24): failure reason, method, log amount, retries so far, messages sent, hours since failure,
  hour-of-day (sin/cos), salary window (day ≤ 7 or ≥ 28), weekend, customer history (log #payments, smoothed
  success rate). All available at decision time; none leak the outcome.
* **One schema for training and serving.** `features.build_row` is used by the trainer, the evaluator and the live
  engine. A *fingerprint* of what the features mean (vectors for canonical inputs) is stored with each model and
  verified on load; a mismatch refuses the model. A golden-value test pins the semantics.
* **Model:** `HistGradientBoostingClassifier` with **monotonic constraints** from domain knowledge (higher amount and
  more prior failures can only lower the odds; a better customer record can only raise them).
* **Calibration:** Platt or isotonic, chosen on a validation split. Calibration matters because the number is
  multiplied by the amount. The held-out **ECE is 1.4% vs 12.9%** for the old static score.
* **Splits:** time-ordered at the *case* level (65% train / 10% validation / 10% calibration / 15% test) — no case
  appears in two splits.
* **Baselines reported next to the model:** logistic regression, the previous static rule score, and prevalence.
  Logistic regression is within 0.003 AUC of boosting here — the simulated world is smooth, so the real gain is over
  the old rules, not boosting over a linear model. The model card says so.
* **Explanations:** interventional group attribution — for each feature group, resample it from a background set
  and measure how the prediction moves. Approximate (contributions need not sum to the total) but cheap, batched
  and model-agnostic. Shown in every case's detail panel.

### 3.2 Retry-timing bandit (`bandit.py`)

*Question answered:* "How long should we wait before the next silent retry?" Insufficient-funds failures recover better
after waiting (balances refill, salary windows); OTP timeouts only recover if retried fast; infrastructure errors
need a few hours. A fixed per-category delay can't capture that, and there is no historical data to fit it offline, so it
is learned **online**.

* Arms: `{15 min, 6h, 12h, 24h, 48h, 72h}`; context = failure reason × (first | later retry).
* **Thompson sampling** over Beta posteriors; weak prior (4 pseudo-observations) centred on the legacy category
  success rates, so a new merchant behaves sensibly and adapts.
* **Guardrail interaction:** `rules.allowed_delay_arms` removes any arm that would violate the cooldown (after the first
  retry) or fall outside the recovery window *before* the bandit sees the choice. Retry caps and approvals are untouched.
* **Reward integrity:** a reward is recorded only for a retry that actually executed — Test Mode immediately; Live
  Mode when the case reaches a terminal state. A retry that was scheduled but never ran (e.g. the customer paid
  first) is **censored**, never credited to the arm.

### 3.3 Anomaly detection (`anomaly.py`)

| Detector | Signal | Model | Action |
|---|---|---|---|
| Card testing | burst of small, mostly-failing payments from one customer | Isolation Forest on 9 per-customer velocity features, trained **unsupervised on benign windows only** (with hard negatives: persistent honest retriers, B2B bulk payers); threshold = 99.5th percentile of benign scores; **minimum-evidence guard** (≥ 3 failures) | **Security hold**: no retry, no message, until a human releases or confirms |
| Method outage | failure-rate spike dominated by gateway/bank errors across many customers | exact one-sided **binomial test** vs the method's own 7-day baseline (time window + last-K window), α = 1e-4, effect-size and infra-share conditions | **Defer** retries (bounded, max 6 deferrals) without consuming the retry budget; resume when the spike clears |

The card-testing window is centred on each payment, so every payment in a burst — including its first, which looked
harmless when it happened — is recognised.

### 3.4 Closing the loop

Every scored case writes an `ml_decisions` row (exact features, model version, factors). When the case ends, the
outcome is attached (`recovered`→1, `exhausted`/`expired`→0, anything else censored). `python -m app.ml.train --from-db`
(or the **Retrain** button) mixes those rows into training and reports a held-out real-data score.

## 4. Guardrail contract

ML may **propose**; `rules.py` and the engine **dispose**.

| ML output | Deterministic check before it can matter |
|---|---|
| probability | `guard_probability` clips to [0.01, 0.97]; NaN/None ⇒ rule-based score; suppression threshold still applies |
| retry delay | only from `allowed_delay_arms` (cooldown + window); empty ⇒ rule-based delay |
| security hold | pauses *all* automation on that case; only a human can release; cannot block a customer's payment |
| outage deferral | bounded count; never consumes a retry; never extends past the recovery window |
| anything raising an exception | caught in `service.py`; the engine continues with the rule-based behaviour |

Retry cap, message cap, cooldown, recovery window and human approval for customer-facing actions are **not** inputs to
any model. Property-style tests run many scan/time cycles and assert the caps are never exceeded.

## 5. Evaluation methodology

There is **no public payment-recovery dataset**, so `world.py` defines a documented, stylised world (reason-specific
timing curves, salary-window effect, amount and customer effects, retry decay, organic recovery). It is anchored so the
*marginal* per-category retry success rates match the legacy sandbox constants. Models are trained on data generated
from it, and policies are compared inside it.

`evaluate.py` replays the **same failed payments with the same random draws** (common random numbers) under five
policies and reports bootstrap 95% CIs on net value per failed payment (recovered revenue − retry, message and
human-review costs, with a daily human-review capacity limit):

| Policy | Recovery | Net ₹/case (95% CI) |
|---|---|---|
| Do nothing | 18.3% | 515 [468, 560] |
| Naive retry | 67.0% | 1,816 [1,736, 1,893] |
| Rules (before ML) | 77.3% | 2,098 [2,016, 2,189] |
| + Risk model | 77.3% | 2,098 [2,019, 2,183] |
| + Learned timing | **81.7%** | **2,243** [2,160, 2,331] |

*Lift of the full ML policy over rules: +₹145/case (+6.9%), 95% CI [+115, +177]. In a **shifted** world whose dynamics
differ from the training world: +₹136/case [+104, +170].* The bandit recovered the oracle-best first-retry delay for 4 of 5
reasons in the base world, and was within one arm for the fifth.

**A more pessimistic world, calibrated to published figures.** The base world's rules baseline recovers 77%, well above what vendors
publish (25–35% audited B2C; ≈55% the highest claim). `WorldParams.conservative()` applies one global logit shift and halves the unaided-payment
rate, with the offset chosen so the **rules** baseline lands inside that band (no ML policy was used to choose it; a test pins this). There: rules
38.7% → full ML 43.7%, **+₹134/case (+13.8%), CI [+106, +163]**.

**Real data.** No public dataset of failed payments with outcomes exists. `realdata.py` uses real UCI *Online Retail* invoices for what they can
honestly show: the simulator's amount spread matches (log-sd 1.10 real vs 1.0), and the card-testing detector's false-positive behaviour on real
customer activity (worst case, every attempt fails: 4.7% of windows from 4 wholesale customers; realistic 12% failure rate: 0 holds in 25 draws).
There are no fraud labels or recovery outcomes in that data, so it cannot validate recall or recovery accuracy.

**Read these results carefully**

* They validate the *machinery* inside a simulator the author wrote. They are not a forecast of production uplift.
* The **risk model adds nothing** when reviewers are not a bottleneck (8 reviews/day: lift 0.0). It helps when
  capacity is scarce: **+₹148/case at 2 reviews/day, +₹121 at 4**. Ranking only matters when there is something to rank.
* The bandit **trades speed for success**: mean time to recovery rises from 14.8h to 41.8h. A merchant that values cash
  speed can restrict the arms.
* Card-testing results (recall 100%, FPR 0.5%) are on synthetic attacks that are blatant by construction; a plain
  signature rule gets 93.9% recall at 0% FPR on the same data. The defensible claims are the low FPR and the
  minimum-evidence guard. Outage recall is **72% pooled** (89% on busy methods, 45% on low-volume netbanking): the detector
  stays silent when volume is too low for a sound test.

## 6. Failure modes and fallbacks

| Failure | Behaviour |
|---|---|
| Artifact missing / unreadable / sklearn version mismatch | retrain in-process once; if that fails, rule-based scoring |
| Artifact bytes modified | SHA-256 mismatch ⇒ refused, never unpickled ⇒ retrain |
| Feature semantics changed since training | fingerprint mismatch ⇒ refused ⇒ retrain |
| Payment-history fetch fails | scan continues without history features / anomaly checks |
| Model/bandit/detector raises | logged; engine continues with rules |
| Cold start | weak legacy prior; exploration is visible (and bounded by the guardrails) |
| Distribution shift | bandit adapts online; risk model should be retrained (`--from-db`) |

## 7. Security considerations specific to the ML layer

| Threat | Mitigation / residual risk |
|---|---|
| **Malicious model file** (joblib = pickle ⇒ code execution on load) | SHA-256 manifest verified before any deserialisation; unrecorded or modified artifacts refused. Residual: an attacker who can rewrite both the artifact *and* the manifest already has code execution. |
| **Training-data poisoning** via the retrain path | Outcomes come only from the merchant's own resolved cases; the endpoint is authenticated and throttled; every row is auditable in `ml_decisions`. Residual: model is process-wide (single-tenant assumption) — a multi-tenant deployment needs per-tenant models. |
| **Adversarial inputs** (customer-controlled amount, reason text) | Free text never reaches a model: reasons are mapped to a fixed vocabulary with an explicit `unknown` bucket. Worst case is a mis-scored probability, and actions stay bounded by the guardrails. |
| **Detector evasion** (slow-drip card testing, rotating emails) | Not handled: windows are one hour per customer key. Documented limitation; velocity features across devices/IPs would be the next step. |
| **Detector false positives** | Hold only *pauses automation*; a reviewer can release; minimum-evidence guard; ~0.5% FPR on synthetic hard negatives. |
| **Alert flooding / flapping** | Alerts are upserted per subject; outage alerts use hysteresis (30 quiet minutes). |
| **LLM prompt injection** | The ML layer does not use an LLM. Models consume numeric features only. |
| **Model-induced harm to customers** | No ML output can contact a customer without human approval; suspected fraud is never contacted. |
| **Unauditable decisions** | Every score, delay choice and hold is logged with features, model version, and explanation. |

## 8. Reproducing everything

```bash
cd backend
python -m app.ml.train                 # risk model  -> artifacts/risk_model.joblib + model_card.json
python -c "from app.ml.anomaly import AnomalyModel; AnomalyModel.train_and_save(quiet=False)"
python -m app.ml.evaluate              # -> artifacts/eval_report.json   (3 worlds, ≈ 17 s)
python -m app.ml.realdata              # -> artifacts/realdata_report.json (add --path for the full UCI file)
python -m pytest                       # 79 tests
```

## 9. Known limitations / next steps

* Recovery results come from simulators (one calibrated to published figures); the real data bundled has no failures. Retrain on real outcomes
  (`--from-db`) before trusting any number.
* Live-Mode bandit rewards are delayed and noisy (a payment link, not an instant retry) and were exercised only
  through shared code paths in Test Mode — not against real Razorpay.
* Outage and card-testing detectors are per-merchant/per-customer; no cross-merchant or device/IP signals.
* The bandit context is tabular (reason × first/later); a contextual model (amount, hour, salary window) is the next step.
* Counterfactual policy choice (retry vs contact the customer) needs randomised logging to learn without bias.
