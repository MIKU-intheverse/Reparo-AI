"""
Reparo AI — machine-learning layer.

Components (each degrades gracefully to the rules in app/recovery/rules.py):

  world.py       Generative model of payment-failure recovery (ground truth for the
                 sandbox, for training data and for offline policy evaluation).
  features.py    One feature schema shared by training and live serving.
  episodes.py    Episode runner + baseline policies (do nothing / naive / current rules).
  risk_model.py  Calibrated gradient-boosted recovery-probability model + explanations.
  train.py       `python -m app.ml.train`      -> trains and saves the risk model.
  bandit.py      Thompson-sampling bandit that learns the best retry delay online.
  anomaly.py     Card-testing (Isolation Forest) and outage (binomial z-test) detection.
  evaluate.py    `python -m app.ml.evaluate`   -> offline policy comparison with CIs.
  service.py     The facade the recovery engine calls.

IMPORTANT (honesty note): there is no public payment-recovery dataset, so the
models are trained on data from `world.py`. Reported metrics describe how well
the machinery learns a documented, stylised world — not production performance.
The `ml_decisions` table logs features and outcomes so the same code retrains on
real outcomes (`python -m app.ml.train --from-db`).
"""
