def test_auth_required(client):
    for path in ("/api/ml/overview", "/api/ml/model", "/api/ml/anomaly-model", "/api/ml/evaluation", "/api/ml/bandit",
                 "/api/ml/alerts", "/api/ml/realdata", "/api/ml/benchmarks"):
        assert client.get(path).status_code == 401, path
    for path in ("/api/ml/score", "/api/ml/evaluation/run", "/api/ml/retrain", "/api/ml/simulate/incident",
                 "/api/ml/simulate/failures", "/api/ml/simulate/learn", "/api/ml/alerts/x/acknowledge"):
        assert client.post(path, json={}).status_code == 401, path
    # a forged token is rejected too
    assert client.get("/api/ml/model", headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401


def test_health_reports_model(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["ml"]["risk_model"].startswith("risk-gbm-")


def test_overview_model_and_cards(client, auth):
    o = client.get("/api/ml/overview", headers=auth).json()
    assert o["ml_enabled"] and o["risk_model"]["version"] and o["anomaly_model"]["version"]
    m = client.get("/api/ml/model", headers=auth).json()
    assert m["metrics"]["gbm_calibrated"]["auc"] > m["metrics"]["rules_baseline"]["auc"]
    assert "Synthetic" in m["data_provenance"]
    a = client.get("/api/ml/anomaly-model", headers=auth).json()
    assert a["card_testing"]["auc_benign_vs_attack"] > 0.9 and a["outage_detection"]["recall"] > 0.5
    e = client.get("/api/ml/evaluation", headers=auth).json()
    assert {"base", "shifted", "conservative", "notes"} <= set(e) and len(e["base"]["policies"]) == 5


def test_what_if_scorer(client, auth):
    body = {"reason": "insufficient_funds", "method": "upi", "amount": 1500, "age_hours": 24}
    r = client.post("/api/ml/score", headers=auth, json=body).json()
    assert 0 < r["probability"] < 1 and r["rules_baseline_probability"] == 0.62 and len(r["factors"]) == 8
    cheap = client.post("/api/ml/score", headers=auth, json={**body, "amount": 100}).json()["probability"]
    big = client.post("/api/ml/score", headers=auth, json={**body, "amount": 90000}).json()["probability"]
    assert cheap > big
    assert client.post("/api/ml/score", headers=auth, json={**body, "amount": -5}).status_code == 422
    assert client.post("/api/ml/score", headers=auth, json={**body, "hour": 30}).status_code == 422


def test_simulation_flow_through_the_api(client, auth):
    assert client.post("/api/ml/simulate/incident", headers=auth, json={"kind": "bogus"}).status_code == 422
    assert client.post("/api/ml/simulate/incident", headers=auth, json={"kind": "card_testing"}).status_code == 200
    assert client.post("/api/recovery/scan", headers=auth).status_code == 200
    held = client.get("/api/recovery/cases?status=security_hold", headers=auth).json()["items"]
    assert len(held) >= 10
    d = client.get(f"/api/recovery/cases/{held[0]['id']}", headers=auth).json()
    assert d["ml"]["security"]["reasons"] and any(t["agent"] == "Security" for t in d["trace"])
    alerts = client.get("/api/ml/alerts?status=open", headers=auth).json()["items"]
    assert alerts and alerts[0]["kind"] == "card_testing"
    assert client.post(f"/api/ml/alerts/{alerts[0]['id']}/acknowledge", headers=auth).json()["status"] == "acknowledged"
    assert client.post(f"/api/recovery/cases/{held[0]['id']}/security/release", headers=auth).status_code == 200
    assert client.post(f"/api/recovery/cases/{held[0]['id']}/security/release", headers=auth).status_code == 409
    assert client.post(f"/api/recovery/cases/{held[1]['id']}/security/confirm", headers=auth).json()["status"] == "suppressed"


def test_learning_demo_and_bandit_endpoint(client, auth):
    r = client.post("/api/ml/simulate/learn", headers=auth, json={"cases": 60, "rounds": 4, "hours_per_round": 24}).json()
    assert r["cases_generated"] == 60
    b = client.get("/api/ml/bandit", headers=auth).json()
    assert b["contexts"]
    for ctx in b["contexts"]:
        allowed = [a["arm_hours"] for a in ctx["arms"]]
        if ctx["stage"] == "later":
            assert min(allowed) >= b["cooldown_hours"]                  # arms forbidden by the cooldown are never shown
        assert ctx["best_arm_hours"] is None or ctx["best_arm_hours"] in allowed
        assert "sandbox_truth" in ctx
    assert client.post("/api/ml/simulate/learn", headers=auth, json={"cases": 60, "rounds": 8, "hours_per_round": 48}).status_code == 422


def test_simulation_endpoints_blocked_in_live_mode(client, live_auth):
    assert client.post("/api/ml/simulate/incident", headers=live_auth, json={"kind": "outage"}).status_code == 403
    assert client.post("/api/ml/simulate/failures", headers=live_auth, json={"count": 5}).status_code == 403
    assert client.post("/api/ml/simulate/learn", headers=live_auth, json={}).status_code == 403
    assert client.post("/api/recovery/simulate/advance", headers=live_auth, json={"hours": 5}).status_code == 403


def test_evaluation_run_endpoint_validation_and_throttle(client, auth, monkeypatch):
    from app.ml import registry
    monkeypatch.setattr(registry, "write_json", lambda *a, **k: None)      # never touch shipped artifacts from tests
    r = client.post("/api/ml/evaluation/run", headers=auth, json={"n_cases": 500, "seed": 7, "approvals_per_day": 4})
    assert r.status_code == 200 and r.json()["config"]["n_cases"] == 500
    assert client.post("/api/ml/evaluation/run", headers=auth, json={"n_cases": 50}).status_code == 422
    assert client.post("/api/ml/evaluation/run", headers=auth, json={"n_cases": 500}).status_code == 429   # throttled


def test_benchmarks_and_realdata_endpoints(client, auth):
    b = client.get("/api/ml/benchmarks", headers=auth).json()
    assert "unaudited" in b["published"]["disclaimer"] and b["published"]["calibration_band"]["low"] == 0.25
    rec = b["simulated"]["recovery_rate_by_world"]
    assert set(rec) == {"base", "shifted", "conservative"}
    band = b["published"]["calibration_band"]
    assert rec["base"]["rules"] > band["high"] and band["low"] <= rec["conservative"]["rules"] <= band["high"]
    assert 0.2 < b["simulated"]["insufficient_funds_share"] < 0.4
    r = client.get("/api/ml/realdata", headers=auth).json()
    assert r["dataset"]["is_bundled_sample"] and r["detector_stress"]["realistic"]["hold_rate_mean"] < 0.02
    assert client.get("/api/ml/realdata").status_code == 401
