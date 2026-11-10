import math
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.ml import features as F
from app.ml import service
from app.ml.world import (BASE_WORLD, EPOCH, REASONS, generate_cases, retry_success_prob, time_parts_from_datetime,
                          time_parts_from_hours)
from app.recovery import rules


def test_generation_is_deterministic_and_time_ordered():
    a, b = generate_cases(300, 5), generate_cases(300, 5)
    assert [(c.reason, c.method, round(c.amount, 4), c.t0) for c in a] == [(c.reason, c.method, round(c.amount, 4), c.t0) for c in b]
    assert all(x.t0 <= y.t0 for x, y in zip(a, a[1:]))
    assert [c.cid for c in a] == list(range(300))


def test_sandbox_preserves_legacy_marginal_success_rates():
    """The new world is anchored to the legacy flat sandbox rates at the legacy timings."""
    legacy = {"soft_decline": 0.55, "technical": 0.65, "hard_decline": 0.05, "unknown": 0.25}
    delay = {"soft_decline": 18.0, "technical": 0.25}
    by_cat = {k: [] for k in legacy}
    for c in generate_cases(8000, 11):
        cat = rules.classify_failure(c.reason)
        age = delay.get(cat, 0.02)
        h, d, _, _ = time_parts_from_hours(c.t0 + age)
        by_cat[cat].append(retry_success_prob(c.reason, c.method, c.amount, c.cust_rate, age, 0, h, d))
    for cat, target in legacy.items():
        assert abs(np.mean(by_cat[cat]) - target) < 0.08, (cat, np.mean(by_cat[cat]), target)


def test_world_structure_matches_documented_mechanisms():
    cases = generate_cases(3000, 3)

    def avg(reason, age, k=0):
        ps = [retry_success_prob(reason, c.method, c.amount, c.cust_rate, age, k, *time_parts_from_hours(c.t0 + age)[:2])
              for c in cases]
        return float(np.mean(ps))

    assert avg("insufficient_funds", 48) > avg("insufficient_funds", 0.25) + 0.1       # waiting helps
    assert avg("otp_timeout", 0.25) > avg("otp_timeout", 24) + 0.15                      # urgency decays
    assert avg("issuer_unavailable", 6) > avg("issuer_unavailable", 0.25) + 0.1          # not instantly
    assert avg("card_declined", 24) < 0.1 and avg("expired_card", 24) < 0.1              # hard declines
    assert avg("gateway_timeout", 1, k=2) < avg("gateway_timeout", 1, k=0)               # repeated failure decays
    assert all(0.0 < retry_success_prob(r, "card", 1000, 0.8, 5, 0, 12, 10) < 1.0 for r in REASONS)


def test_time_parts_are_identical_for_hours_and_datetimes():
    rng = random.Random(0)
    for _ in range(300):
        t = rng.uniform(0, 24 * 700)
        assert time_parts_from_hours(t)[:3] == time_parts_from_datetime(EPOCH + timedelta(hours=t))[:3]
        assert abs(time_parts_from_hours(t)[3] - time_parts_from_datetime(EPOCH + timedelta(hours=t))[3]) < 1e-6


def test_feature_vector_schema():
    fi = F.FeatureInput("insufficient_funds", "upi", 1500, 1, 0, 12.0, 14.5, 3, 2, 6, 5)
    x = F.build_row(fi)
    assert x.shape == (F.N_FEATURES,) and np.isfinite(x).all()
    assert x[[i for i, c in enumerate(F.FEATURE_COLUMNS) if c.startswith("reason=")]].sum() == 1
    assert x[[i for i, c in enumerate(F.FEATURE_COLUMNS) if c.startswith("method=")]].sum() == 1
    assert len(F.monotonic_vector()) == F.N_FEATURES
    # unseen vocabulary maps to the explicit 'unknown' / 'other' buckets rather than failing
    y = F.build_row(F.FeatureInput("weird_new_error", "crypto", 10, 0, 0, 0, 3, 1, 0, 0, 0))
    assert y[F.FEATURE_COLUMNS.index("reason=unknown")] == 1 and y[F.FEATURE_COLUMNS.index("method=other")] == 1
    # round trip through the JSON representation stored in ml_decisions
    assert np.allclose(F.dict_to_row(F.row_to_dict(x)), x, atol=1e-5)


def test_train_serve_feature_parity():
    """The engine's live feature builder must produce exactly what the training pipeline builds
    for the same situation (no train/serve skew)."""
    now = datetime(2025, 3, 3, 8, 45)                     # a Monday, salary window, 14:15 IST
    case = SimpleNamespace(failure_reason_raw="otp_timeout", method="upi", amount=2500.0, retry_count=1,
                           communications_sent=0, created_at=now - timedelta(hours=7), customer_email=None,
                           customer_contact=None, failed_payment_created_at=now - timedelta(hours=7), payment_id="p1")
    live = F.build_row(service.feature_input(case, None, now))
    local = now + timedelta(minutes=330)
    _, dom, wd, frac = time_parts_from_datetime(local)
    offline = F.build_row(F.FeatureInput("otp_timeout", "upi", 2500.0, 1, 0, 7.0, frac, dom, wd, 0, 0))
    assert np.allclose(live, offline)
    assert F.smooth_rate(0, 0) == 0.8                      # no history -> neutral prior, not 0% or NaN


def test_golden_feature_values_pin_the_semantics():
    """Hard-coded expectations, computed independently of build_row: if feature engineering changes,
    previously trained models would silently mis-score, so this must fail loudly."""
    x = F.build_row(F.FeatureInput("insufficient_funds", "upi", 1500.0, 1, 0, 12.0, 14.5, 3, 2, 6, 5))
    col = lambda n: x[F.FEATURE_COLUMNS.index(n)]
    ang = 2 * math.pi * 14.5 / 24
    assert col("log_amount") == pytest.approx(math.log(1500.0))
    assert col("hour_sin") == pytest.approx(math.sin(ang)) and col("hour_cos") == pytest.approx(math.cos(ang))
    assert col("salary_window") == 1 and col("weekend") == 0
    assert col("cust_log_n") == pytest.approx(math.log(7)) and col("cust_success_rate") == pytest.approx((5 + 3.2) / (6 + 4))
    assert col("age_hours") == 12.0 and col("retry_count") == 1 and col("comms_sent") == 0
    assert col("reason=insufficient_funds") == 1 and col("method=upi") == 1


def test_model_load_rejects_changed_feature_semantics(tmp_path, monkeypatch):
    from app.ml import registry
    from app.ml.risk_model import RiskModel
    m = registry.get_risk_model()
    assert m.meta["feature_fingerprint"] == F.fingerprint()
    m.save(tmp_path / "m.joblib")
    monkeypatch.setattr(F, "fingerprint", lambda: "deadbeefdeadbeef")      # simulate a silent feature-engineering change
    with pytest.raises(RuntimeError, match="semantics"):
        RiskModel.load(tmp_path / "m.joblib")


def test_conservative_world_matches_published_band():
    """The base world is more optimistic than published recovery figures; the conservative world is calibrated
    so the RULES baseline lands inside the published 25-55% band (and no ML policy was used to choose it)."""
    import json
    from pathlib import Path
    from app.ml.evaluate import DEFAULTS, run_policy
    from app.ml.episodes import RulesPolicy, DoNothingPolicy
    from app.ml.world import get_world
    band = json.loads((Path(__file__).parent.parent / "app/ml/data/industry_benchmarks.json").read_text())["calibration_band"]
    costs = {k: DEFAULTS[k] for k in ("cost_retry", "cost_message", "cost_review", "review_hour")}
    rec = {}
    for name in ("base", "conservative"):
        w = get_world(name)
        cases = generate_cases(3000, 31, w)
        rec[name] = {"rules": run_policy(RulesPolicy(), cases, w, 8, costs)["recovered"].mean(),
                     "nothing": run_policy(DoNothingPolicy(), cases, w, 8, costs)["recovered"].mean()}
    assert rec["base"]["rules"] > band["high"]                                   # base world is too optimistic ...
    assert band["low"] <= rec["conservative"]["rules"] <= band["high"]           # ... the conservative one is not
    assert rec["conservative"]["nothing"] < rec["conservative"]["rules"] < rec["base"]["rules"]


def test_get_world_names():
    from app.ml.world import get_world
    assert get_world("base").name == "base" and get_world("shifted").name == "shifted"
    assert get_world("conservative").name == "conservative" and get_world("nonsense").name == "base"
