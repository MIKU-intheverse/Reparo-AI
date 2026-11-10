import random
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.config import get_settings
from app.ml import anomaly as A
from app.ml import registry
from app.ml.context import PaymentRecord, ScanContext, is_infra_reason, to_ts

settings = get_settings()
T0 = datetime(2026, 1, 10, 12, 0, 0)


@pytest.fixture(scope="module")
def model() -> A.AnomalyModel:
    m = registry.get_anomaly_model()
    assert m is not None
    return m


def recs(n, failed_ratio, amount, gap_s, reasons=("card_declined",), method="card"):
    base = to_ts(T0)
    out = []
    for i in range(n):
        failed = i < round(n * failed_ratio)
        out.append(PaymentRecord(f"r{i}", "c", method, amount, "failed" if failed else "captured",
                                 reasons[i % len(reasons)] if failed else None, base + i * gap_s))
    return out


def test_card_testing_burst_is_held_and_explained(model):
    burst = recs(18, 0.95, 40.0, 12.0, reasons=("card_declined", "risk_check_failed", "do_not_honor"))
    a = model.assess(burst, day_failures=20)
    assert a.hold and a.score >= a.threshold and a.reasons


def test_ordinary_failures_are_not_held(model):
    assert not model.assess(recs(1, 1.0, 2400.0, 0), 1).hold
    assert not model.assess(recs(2, 1.0, 2400.0, 300), 2).hold                    # honest retry
    bulk = recs(9, 0.1, 25000.0, 300, reasons=("insufficient_funds",)); bulk[-1].status = "failed"
    assert not model.assess(bulk, 1).hold                                         # B2B bulk payer


def test_minimum_evidence_guard_blocks_hold_with_too_few_failures(model):
    two_failures = recs(2, 1.0, 5.0, 1.0)
    assert not model.assess(two_failures, 2, min_failures=3).hold
    assert A.velocity_features(two_failures, 2)["n_failed"] == 2


def test_card_model_quality_in_card(model):
    c = model.meta["card_testing"]
    assert c["auc_benign_vs_attack"] > 0.95 and c["deployed_rule_recall"] > 0.9 and c["deployed_rule_false_positive_rate"] < 0.02
    assert "Synthetic" in model.meta["data_provenance"]


def _ctx(items, now=T0):
    return ScanContext(items, now=now)


def _stream(method="upi", baseline_n=300, baseline_fail=0.1, burst_n=0, burst_fail=0.9, burst_reasons=("gateway_timeout", "issuer_unavailable")):
    rng = random.Random(4)
    items = []
    for i in range(baseline_n):                                       # last 6 days
        t = T0 - timedelta(days=6) + timedelta(minutes=i * (6 * 1440 / baseline_n))
        failed = rng.random() < baseline_fail
        items.append({"id": f"b{i}", "email": f"u{i}@x.io", "method": method, "amount": 500, "status": "failed" if failed else "captured",
                      "failure_reason": "insufficient_funds" if failed else None, "created_at": t.isoformat()})
    for j in range(burst_n):                                          # last 25 minutes
        t = T0 - timedelta(minutes=25 - j * 25 / max(burst_n, 1))
        failed = rng.random() < burst_fail
        items.append({"id": f"x{j}", "email": f"v{j}@x.io", "method": method, "amount": 500, "status": "failed" if failed else "captured",
                      "failure_reason": burst_reasons[j % len(burst_reasons)] if failed else None, "created_at": t.isoformat()})
    return items


def test_outage_detected_on_infra_failure_spike():
    sig = A.detect_outages(_ctx(_stream(burst_n=24)), to_ts(T0))
    assert len(sig) == 1 and sig[0].method == "upi" and sig[0].rate > 0.6 and sig[0].technical_share > 0.9


def test_calm_traffic_raises_no_outage_alert():
    assert A.detect_outages(_ctx(_stream(burst_n=24, burst_fail=0.1)), to_ts(T0)) == []
    assert A.detect_outages(_ctx(_stream()), to_ts(T0)) == []


def test_spike_of_ordinary_declines_is_not_an_outage():
    """A burst of customer-side declines (e.g. card testing) is not an infrastructure outage."""
    items = _stream(burst_n=24, burst_reasons=("card_declined", "insufficient_funds"))
    assert A.detect_outages(_ctx(items), to_ts(T0)) == []


def test_too_little_data_means_silence_not_guessing():
    assert A.detect_outages(_ctx(_stream(burst_n=5, burst_fail=1.0)), to_ts(T0)) == []


def test_infra_reason_classifier():
    assert all(is_infra_reason(r) for r in ("gateway_timeout", "issuer_unavailable", "bank_timeout", "Network failure"))
    assert not any(is_infra_reason(r) for r in ("card_declined", "insufficient_funds", None, "otp_expired_by_user"))


def test_outage_detector_quality_in_card(model):
    o = model.meta["outage_detection"]
    assert o["recall"] >= 0.6 and o["false_alarm_episodes_per_month"] <= 1.0 and o["median_detection_delay_min"] <= 60
