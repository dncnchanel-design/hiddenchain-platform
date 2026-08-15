from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DB = Path(__file__).resolve().parent / "hiddenchain_test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["DEMO_SEED"] = "true"
os.environ["MOCK_DELAY_MS"] = "0"
os.environ["DEEPSEEK_ENABLED"] = "false"

from app.database import SessionLocal, ensure_runtime_schema, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.seed import seed_demo  # noqa: E402


@pytest.fixture(autouse=True)
def reset_demo_database():
    """Give every test a fresh seeded database so order randomization is valid."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema()
    with SessionLocal() as db:
        seed_demo(db)
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth_headers(client):
    def login(username: str, password: str) -> dict[str, str]:
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return {
        "generator": login("generator", "generator123"),
        "retailer": login("retailer", "retailer123"),
        "exchange": login("exchange", "exchange123"),
        "regulator": login("regulator", "regulator123"),
        "admin": login("admin", "admin123"),
    }
