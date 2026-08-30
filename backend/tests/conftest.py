from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient


TEST_DB = Path(
    os.environ.get(
        "HIDDENCHAIN_TEST_DB",
        str(Path(__file__).resolve().parent / "hiddenchain_test.db"),
    )
)
if TEST_DB.exists():
    TEST_DB.unlink()

# Keep fixture payloads out of the shared development/demo Vault.  The
# directory is session-scoped because app.config reads HIDDENCHAIN_VAULT_DIR
# during import, before pytest fixtures are available.
TEST_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"
TEST_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
_TEST_VAULT_RUNTIME = TemporaryDirectory(
    prefix=".pytest-vault-",
    dir=TEST_RUNTIME_DIR,
)
os.environ["HIDDENCHAIN_VAULT_DIR"] = str(
    Path(_TEST_VAULT_RUNTIME.name) / "vault"
)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["TEST_FIXTURE_SEED"] = "true"
os.environ["TEST_COMPUTE_DELAY_MS"] = "0"
os.environ["DEEPSEEK_ENABLED"] = "false"
os.environ["PLATFORM_SIGNING_PRIVATE_KEY"] = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="

from app.database import SessionLocal, ensure_runtime_schema, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.seed import seed_test_fixtures  # noqa: E402
from app.services.rate_limit import limiter  # noqa: E402


@pytest.fixture(autouse=True)
def reset_test_database():
    """Give every test a fresh seeded database so order randomization is valid."""
    limiter.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema()
    with SessionLocal() as db:
        seed_test_fixtures(db)
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
        "oil": login("oil", "oil123"),
        "heat": login("heat", "heat123"),
        "exchange": login("exchange", "exchange123"),
        "regulator": login("regulator", "regulator123"),
        "admin": login("admin", "admin123"),
    }
