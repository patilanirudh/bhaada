import os
import tempfile

os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": "sqlite://",
    "EMAIL_BACKEND": "memory",
    "STORAGE_BACKEND": "local",
    "LOCAL_UPLOAD_DIR": tempfile.mkdtemp(prefix="rent-test-uploads-"),
    "CRON_SECRET": "test-cron-secret",
    "JWT_SECRET": "test-secret-test-secret-test-secret-123",
    "FERNET_KEY": "",
})

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import database  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import email as email_service  # noqa: E402
from app.utils.formatting import set_today_override  # noqa: E402
from app.utils.ratelimit import limiter  # noqa: E402
from app.utils.validators import verhoeff_check_digit  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
PDF = b"%PDF-1.4\n" + b"0" * 100


def valid_aadhaar(prefix: str = "23456789012") -> str:
    return prefix + verhoeff_check_digit(prefix)


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(db_engine):
    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    old = database.SessionLocal
    database.SessionLocal = Session
    session = Session()
    yield session
    session.close()
    database.SessionLocal = old


@pytest.fixture()
def client(db):
    def _get_db():
        s = database.SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    email_service.OUTBOX.clear()
    email_service.FAIL_ADDRESSES.clear()
    limiter.reset()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    set_today_override(None)


def register_owner(client: TestClient, email: str, name: str = "Owner") -> dict:
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": "password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def owner_a(client):
    return register_owner(client, "a@example.com", "Suresh A")


@pytest.fixture()
def owner_b(client):
    return register_owner(client, "b@example.com", "Owner B")


def make_property(client, headers, name="Green Residency", unit="Flat 203", rent=15000, rules="<p>No smoking</p>"):
    p = client.post("/api/properties", json={"name": name, "address": "Pune", "house_rules": rules},
                    headers=headers).json()
    u = client.post(f"/api/properties/{p['id']}/units", json={"name": unit, "default_rent": rent},
                    headers=headers).json()
    return p, u


def make_tenant(client, headers, unit_id, start: date, name="Ravi Kumar", rent=15000, due_day=5,
                email="ravi@example.com", end: date | None = None, phone="9876543210"):
    body = {"full_name": name, "phone": phone, "email": email, "unit_id": unit_id, "base_rent": rent,
            "security_deposit": 30000, "agreement_start_date": start.isoformat(), "due_day": due_day,
            "increment_percent": 5}
    if end:
        body["agreement_end_date"] = end.isoformat()
    r = client.post("/api/tenants", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
