"""Artifact locations + process-wide singletons for loaded ML artifacts."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

from app.config import get_settings

log = logging.getLogger("reparo.ml")
settings = get_settings()

_LOCK = threading.RLock()
_STATE: dict = {"risk": None, "risk_tried": False, "anomaly": None, "anomaly_tried": False}


def artifact_dir() -> Path:
    d = Path(settings.ml_artifact_dir) if settings.ml_artifact_dir else Path(__file__).parent / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path(name: str) -> Path:
    return artifact_dir() / name


def read_json(name: str) -> dict | None:
    p = path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:  # pragma: no cover - corrupt file
        log.warning("Could not parse %s", p)
        return None


def write_json(name: str, data: dict) -> None:
    path(name).write_text(json.dumps(data, indent=2, default=str))


# ---- Artifact integrity -------------------------------------------------------------------
# Model files are serialised with joblib (pickle), and unpickling untrusted bytes executes
# code. Every artifact we write is recorded in MANIFEST.json with its SHA-256, and every
# load verifies it first: a tampered, swapped or unrecorded file is refused (the caller then
# retrains from scratch or falls back to rules) instead of being deserialised.
MANIFEST = "MANIFEST.json"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def record(name: str) -> None:
    """Register the current bytes of an artifact we just wrote as trusted."""
    manifest = read_json(MANIFEST) or {}
    manifest[name] = _sha256(path(name))
    write_json(MANIFEST, manifest)


def verify(name: str) -> None:
    manifest = read_json(MANIFEST) or {}
    expected = manifest.get(name)
    if expected is None:
        raise RuntimeError(f"{name} is not recorded in {MANIFEST}; refusing to deserialise an unverified artifact.")
    if _sha256(path(name)) != expected:
        raise RuntimeError(f"{name} does not match its recorded SHA-256; refusing to deserialise a modified artifact.")


def check_sklearn_version(meta: dict) -> None:
    """Pickled scikit-learn objects are only guaranteed to load correctly under the version that wrote
    them. A different major.minor could unpickle into subtly wrong behaviour, so refuse and retrain."""
    import sklearn
    trained = str(meta.get("sklearn_version", ""))
    if trained.split(".")[:2] != sklearn.__version__.split(".")[:2]:
        raise RuntimeError(f"Artifact was trained with scikit-learn {trained or '?'}, runtime has {sklearn.__version__}; retrain required.")


def get_risk_model():
    """Return the loaded RiskModel or None (callers then fall back to rules).
    If the shipped artifact can't be loaded (e.g. different scikit-learn
    version) we retrain a model in-process once rather than silently losing ML."""
    if not settings.ml_enabled:
        return None
    with _LOCK:
        if _STATE["risk"] is not None or _STATE["risk_tried"]:
            return _STATE["risk"]
        _STATE["risk_tried"] = True
        from app.ml.risk_model import RiskModel
        try:
            verify("risk_model.joblib")
            _STATE["risk"] = RiskModel.load(path("risk_model.joblib"))
        except Exception as e:
            log.warning("Risk model artifact unavailable (%s); training a fresh one in-process.", e)
            try:
                from app.ml.train import train_and_save
                _STATE["risk"] = train_and_save(n_cases=12000, seed=42, quiet=True)
            except Exception as e2:  # pragma: no cover
                log.error("Risk model training failed (%s); using rule-based scoring.", e2)
                _STATE["risk"] = None
        return _STATE["risk"]


def set_risk_model(model) -> None:
    with _LOCK:
        _STATE["risk"] = model
        _STATE["risk_tried"] = True


def get_anomaly_model():
    if not settings.ml_enabled or not settings.ml_anomaly_enabled:
        return None
    with _LOCK:
        if _STATE["anomaly"] is not None or _STATE["anomaly_tried"]:
            return _STATE["anomaly"]
        _STATE["anomaly_tried"] = True
        from app.ml.anomaly import AnomalyModel
        try:
            verify("anomaly_model.joblib")
            _STATE["anomaly"] = AnomalyModel.load(path("anomaly_model.joblib"))
        except Exception as e:
            log.warning("Anomaly model artifact unavailable (%s); training a fresh one in-process.", e)
            try:
                _STATE["anomaly"] = AnomalyModel.train_and_save(quiet=True)
            except Exception as e2:  # pragma: no cover
                log.error("Anomaly model training failed (%s); only signature rules active.", e2)
                _STATE["anomaly"] = None
        return _STATE["anomaly"]


def reset() -> None:
    """Test helper."""
    with _LOCK:
        _STATE.update({"risk": None, "risk_tried": False, "anomaly": None, "anomaly_tried": False})
