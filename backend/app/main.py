from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.routers import agent, auth, data, razorpay, recovery, webhooks

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
app.include_router(webhooks.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name}
