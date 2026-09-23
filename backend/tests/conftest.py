"""Test fixtures. Integration tests run against PostgreSQL (migrated with Alembic) so the
partitioned tables, triggers and JSONB behave exactly like production.

Set NOM_TEST_DATABASE_URL to point elsewhere (CI uses a postgres service container).
"""

from __future__ import annotations

import os
import tempfile

TEST_DB = os.environ.get("NOM_TEST_DATABASE_URL", "postgresql+psycopg://nom:nom@localhost:5432/nom_test")
os.environ["NOM_DATABASE_URL"] = TEST_DB
os.environ["NOM_ENVIRONMENT"] = "test"
os.environ["NOM_BACKUP_REPO_ROOT"] = tempfile.mkdtemp(prefix="nom-configs-")
os.environ.setdefault("NOM_JWT_SECRET", "test-secret-test-secret-test-secret-123")
os.environ["NOM_RATE_LIMIT_LOGIN"] = "1000"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.workers.celery_app import celery_app  # noqa: E402

celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

ADMIN_PW = "Sup3r-Secret-Pass!"


@pytest.fixture(scope="session", autouse=True)
def migrated():
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_db(migrated, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "backup_repo_root", str(tmp_path / "configs"))
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {tables} CASCADE"))
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def tenant(db):
    from app.services.bootstrap import create_tenant

    t = create_tenant(db, "DE-CIX Test", "decix", "admin", ADMIN_PW, "admin@example.net")
    db.commit()
    return t


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def login(client, username="admin", password=ADMIN_PW, tenant="decix", otp=None) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password, "tenant": tenant, "otp": otp})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin(client, tenant):
    tok = login(client)
    client.headers["Authorization"] = f"Bearer {tok['access_token']}"
    return client


def as_user(client, username, password, tenant="decix"):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {login(client, username, password, tenant)['access_token']}"
    return c
