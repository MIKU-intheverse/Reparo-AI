import numpy as np
import pytest
from sklearn.metrics import brier_score_loss, roc_auc_score

from app.config import get_settings
from app.ml import features as F
from app.ml import registry, service
from app.ml.risk_model import RiskModel, build_synthetic_dataset, expected_calibration_error, train_risk_model

settings = get_settings()


@pytest.fixture(scope="module")
def model() -> RiskModel:
    m = registry.get_risk_model()
    assert m is not None, "shipped risk model artifact must load"
    return m


def fi(**kw):
    base = dict(reason="insufficient_funds", method="upi", amount=2000.0, retry_count=0, comms_sent=0, age_hours=0.0,
                local_hour_frac=14.0, day_of_month=15, weekday=2, cust_n=6, cust_captured=5)
    base.update(kw)
    return F.FeatureInput(**base)


def test_artifact_is_valid_and_documented(model):
    assert model.version.startswith("risk-gbm-")
    assert model.meta["feature_columns"] == F.FEATURE_COLUMNS
    assert "Synthetic" in model.meta["data_provenance"]            # the model card must say what it was trained on
    assert model.meta["calibration"] in ("platt", "isotonic")


def test_predictions_are_valid_probabilities(model):
    X = np.vstack([F.build_row(fi(reason=r, amount=a)) for r in F.REASON_VOCAB for a in (50, 5000, 150000)])
    p = model.predict_matrix(X)
    assert np.all((p > 0) & (p < 1)) and np.isfinite(p).all()
    assert np.allclose(p[0], model.predict(fi(reason=F.REASON_VOCAB[0], amount=50)))


def test_beats_rule_baseline_on_fresh_data(model):
    """Fresh seed => data the model never saw. Better ranking AND better calibration than the old rule score."""
    from app.recovery import rules
    X, y, _, rule_p, _ = build_synthetic_dataset(4000, seed=987)
    p = model.predict_matrix(X)
    assert roc_auc_score(y, p) > roc_auc_score(y, rule_p) + 0.04
    assert brier_score_loss(y, p) < brier_score_loss(y, rule_p) - 0.02
    assert expected_calibration_error(y, p) < 0.05
    assert expected_calibration_error(y, p) < expected_calibration_error(y, rule_p)


def test_domain_monotonic_constraints_hold(model):
    amounts = [model.predict(fi(amount=a)) for a in (100, 1000, 10000, 100000)]
    assert all(a >= b - 1e-9 for a, b in zip(amounts, amounts[1:]))
    retries = [model.predict(fi(retry_count=k, age_hours=24.0)) for k in range(4)]
    assert all(a >= b - 1e-9 for a, b in zip(retries, retries[1:]))
    cust = [model.predict(fi(cust_n=20, cust_captured=c)) for c in (2, 10, 20)]
    assert all(a <= b + 1e-9 for a, b in zip(cust, cust[1:]))


def test_hard_declines_are_scored_differently_from_transient_failures(model):
    # sanity of learned structure: an OTP timeout retried immediately is more promising than a day-old one
    assert model.predict(fi(reason="otp_timeout", age_hours=0.0, retry_count=0)) > \
           model.predict(fi(reason="otp_timeout", age_hours=48.0, retry_count=2))


def test_explanations_are_ranked_and_readable(model):
    ex = model.explain(fi(reason="risk_check_failed", amount=90000), top_k=4)
    assert 1 <= len(ex) <= 4
    assert [abs(e["effect"]) for e in ex] == sorted([abs(e["effect"]) for e in ex], reverse=True)
    assert all(e["factor"] in F.GROUPS and e["detail"] for e in ex)
    all8 = model.explain(fi(), top_k=20)
    assert {e["factor"] for e in all8} == set(F.GROUPS)


def test_metrics_in_model_card_are_consistent(model):
    m = model.meta["metrics"]
    assert m["gbm_calibrated"]["auc"] > m["rules_baseline"]["auc"]
    assert m["gbm_calibrated"]["brier"] < m["rules_baseline"]["brier"]
    assert m["gbm_calibrated"]["ece"] < m["rules_baseline"]["ece"]
    assert model.meta["reliability"]["model"] and model.meta["feature_importance"]


def test_training_pipeline_smoke_and_real_data_hook():
    X, y, *_ = build_synthetic_dataset(600, seed=3)
    real = (X[:300], y[:300])                                   # stand-in for logged production outcomes
    m = train_risk_model(n_cases=1200, seed=5, real_rows=real)
    assert m.meta["real_data"]["rows"] == 300 and m.meta["real_data"]["held_out"] == 60
    assert "real_holdout_metrics" in m.meta
    assert 0 < m.predict(fi()) < 1


def test_service_falls_back_to_rules_when_ml_disabled(db, user, monkeypatch):
    from app.models import RecoveryCase
    case = RecoveryCase(user_id=user.id, source="test", payment_id="p", amount=1000.0, failure_reason_raw="card_declined",
                        category="hard_decline", failed_payment_created_at=__import__("datetime").datetime.utcnow(),
                        created_at=__import__("datetime").datetime.utcnow())
    db.add(case); db.flush()
    monkeypatch.setattr(settings, "ml_enabled", False)
    r = service.assess_risk(db, case, None)
    assert r.source == "rules" and r.probability == 0.22
    monkeypatch.setattr(settings, "ml_enabled", True)
    assert service.assess_risk(db, case, None).source == "ml"


def test_corrupt_artifact_triggers_in_process_retrain(tmp_path, monkeypatch):
    (tmp_path / "risk_model.joblib").write_bytes(b"not a model")
    monkeypatch.setattr(settings, "ml_artifact_dir", str(tmp_path))
    registry.reset()
    try:
        m = registry.get_risk_model()
        assert m is not None and 0 < m.predict(fi()) < 1
        assert (tmp_path / "model_card.json").exists()
    finally:
        monkeypatch.setattr(settings, "ml_artifact_dir", None)
        registry.reset()


def test_tampered_artifact_is_refused_not_deserialised(tmp_path, monkeypatch):
    """joblib is pickle: a modified artifact must never be loaded. The registry verifies a recorded
    SHA-256 first and, on mismatch, falls back to training a fresh model in-process."""
    import shutil
    src = registry.artifact_dir()
    for f in ("risk_model.joblib", "MANIFEST.json"):
        shutil.copy(src / f, tmp_path / f)
    monkeypatch.setattr(settings, "ml_artifact_dir", str(tmp_path))
    registry.reset()
    try:
        registry.verify("risk_model.joblib")                              # untouched copy verifies
        (tmp_path / "risk_model.joblib").write_bytes((tmp_path / "risk_model.joblib").read_bytes() + b"\x00")
        with pytest.raises(RuntimeError, match="SHA-256"):
            registry.verify("risk_model.joblib")
        m = registry.get_risk_model()                                     # refused -> retrained, not unpickled
        assert m is not None and 0 < m.predict(fi()) < 1
        registry.verify("risk_model.joblib")                              # retraining re-recorded the new file
    finally:
        monkeypatch.setattr(settings, "ml_artifact_dir", None)
        registry.reset()


def test_unrecorded_artifact_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ml_artifact_dir", str(tmp_path))
    (tmp_path / "risk_model.joblib").write_bytes(b"anything")
    with pytest.raises(RuntimeError, match="not recorded"):
        registry.verify("risk_model.joblib")
    monkeypatch.setattr(settings, "ml_artifact_dir", None)


def test_scikit_learn_version_mismatch_forces_retrain(tmp_path):
    import joblib
    blob = joblib.load(registry.path("risk_model.joblib"))
    blob["meta"]["sklearn_version"] = "0.20.0"
    joblib.dump(blob, tmp_path / "old.joblib")
    with pytest.raises(RuntimeError, match="scikit-learn"):
        RiskModel.load(tmp_path / "old.joblib")
