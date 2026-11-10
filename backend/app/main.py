from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.routers import agent, auth, data, ml, razorpay, recovery, webhooks

settings = get_settings()

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(razorpay.router)
app.include_router(data.router)
app.include_router(agent.router)
app.include_router(recovery.router)
app.include_router(ml.router)
app.include_router(webhooks.router)


@app.on_event("startup")
def _warm_ml():
    """Load (or, if the shipped artifact is incompatible, retrain) the ML artifacts at startup so the
    first request is never slow. Failure is non-fatal: the engine falls back to deterministic rules."""
    try:
        from app.ml import registry
        registry.get_risk_model()
        registry.get_anomaly_model()
    except Exception:  # pragma: no cover
        pass


@app.get("/api/health")
def health():
    from app.ml import registry
    risk = registry.get_risk_model()
    return {"status": "ok", "app": settings.app_name, "ml": {"enabled": settings.ml_enabled,
            "risk_model": risk.version if risk else None}}
