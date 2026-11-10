"""
Train the recovery-probability model.

    python -m app.ml.train                      # synthetic world, writes artifacts
    python -m app.ml.train --n-cases 40000      # bigger dataset
    python -m app.ml.train --from-db            # add logged production outcomes (ml_decisions)

Outputs (in app/ml/artifacts/): risk_model.joblib and model_card.json.
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from app.ml import features as F
from app.ml import registry
from app.ml.risk_model import RiskModel, train_risk_model


def load_real_rows(db) -> tuple[np.ndarray, np.ndarray] | None:
    """Resolved ml_decisions(kind='risk') rows -> (X, y). Only decisions whose
    case ended in a definite state (recovered=1, exhausted/expired=0) count."""
    from app.models import MLDecision
    rows = db.query(MLDecision).filter(MLDecision.kind == "risk", MLDecision.outcome.in_([0, 1])).all()
    if not rows:
        return None
    X = np.vstack([F.dict_to_row(json.loads(r.features)) for r in rows])
    y = np.array([r.outcome for r in rows])
    return X, y


def train_and_save(n_cases: int = 20000, seed: int = 42, real_rows=None, quiet: bool = False) -> RiskModel:
    model = train_risk_model(n_cases=n_cases, seed=seed, real_rows=real_rows, quiet=quiet)
    model.save(registry.path("risk_model.joblib"))
    registry.record("risk_model.joblib")
    registry.write_json("model_card.json", {k: v for k, v in model.meta.items()})
    registry.set_risk_model(model)
    if not quiet:
        m = model.meta["metrics"]
        print(f"Saved {model.version}")
        for name in ("gbm_calibrated", "gbm_uncalibrated", "logistic_regression", "rules_baseline"):
            print(f"  {name:20s} {m[name]}")
    return model


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-cases", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--from-db", action="store_true", help="include resolved decisions from the application database")
    args = ap.parse_args()
    real = None
    if args.from_db:
        from app.database import SessionLocal
        with SessionLocal() as db:
            real = load_real_rows(db)
        print(f"Loaded {0 if real is None else len(real[1])} resolved production decisions.")
    train_and_save(args.n_cases, args.seed, real_rows=real, quiet=False)


if __name__ == "__main__":
    main()
