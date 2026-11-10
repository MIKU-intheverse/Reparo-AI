"""Test configuration. Environment is set BEFORE the app is imported so the settings
singleton picks up an isolated SQLite file; every test starts from empty tables."""
import os
import random
import tempfile

_DB = tempfile.mktemp(suffix=".db", prefix="reparo_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ.setdefault("AUTH_SECRET", "test-secret-not-for-production")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

settings = get_settings()


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    random.seed(1234)
    yield


@pytest.fixture(autouse=True)
def _restore_settings():
    snapshot = settings.model_dump()
    yield
    for k, v in snapshot.items():
        setattr(settings, k, v)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _make_user(db, env: str, email: str) -> User:
    u = User(email=email, password_hash=hash_password("pw"), email_verified=True, environment=env)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def user(db) -> User:
    return _make_user(db, "test", "merchant@example.com")


@pytest.fixture
def live_user(db) -> User:
    return _make_user(db, "live", "live@example.com")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth(user):
    return {"Authorization": "Bearer " + create_access_token(user.id, "test")}


@pytest.fixture
def live_auth(live_user):
    return {"Authorization": "Bearer " + create_access_token(live_user.id, "live")}
