"""A real completed startup produces one tenant-free technical audit event."""
import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app import seed
from app.database import get_db
from app.models import AuditLog, Base, Organization, User
from app.security import create_access_token


@pytest.fixture(autouse=True)
def reset_test_database():
    """Each test below owns an in-memory database; never seed the shared DB."""
    yield


@pytest.fixture
def technical_runtime(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    stages = []
    monkeypatch.setattr(main_module, "SessionLocal", sessions)
    monkeypatch.setattr(main_module, "settings", replace(
        main_module.settings, app_env="test", test_fixture_seed=False, demo_catalog_seed=False,
        demo_business_seed=False, signing_secret="configuration-secret-canary",
        opa_url="https://private-configuration-canary.invalid",
    ))
    monkeypatch.setattr(main_module, "validate_runtime_settings", lambda: stages.append("validate"))
    monkeypatch.setattr(main_module, "assert_production_runtime_clean", lambda _settings: stages.append("runtime"))
    monkeypatch.setattr(main_module, "ensure_runtime_schema", lambda: stages.append("schema"))
    monkeypatch.setattr(main_module, "assert_production_database_clean", lambda _db, _settings: stages.append("database"))
    monkeypatch.setattr(seed, "ensure_agent_identities", lambda _db: stages.append("identities"))
    monkeypatch.setattr(main_module, "ensure_agent_tool_catalog", lambda _db, **_kwargs: stages.append("tools"))
    monkeypatch.setattr(main_module, "version_payload", lambda: {
        "service_version": main_module.VERSION, "build_sha": "a" * 40,
        "private_extra": "version-extra-canary",
    })

    def isolated_db():
        with sessions() as db:
            yield db

    monkeypatch.setitem(main_module.app.dependency_overrides, get_db, isolated_db)
    try:
        yield sessions, stages
    finally:
        engine.dispose()


def _start():
    async def enter_and_exit():
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(enter_and_exit())


def test_completed_lifespan_records_one_real_technical_startup_event(technical_runtime):
    sessions, stages = technical_runtime
    _start()
    assert stages == ["validate", "runtime", "schema", "database", "identities", "tools"]
    with sessions() as db:
        rows = db.scalars(select(AuditLog)).all()
        assert len(rows) == 1
        event = rows[0]
        assert event.action_code == "SYSTEM_STARTUP" and event.target_type == "SYSTEM"
        assert event.result == "SUCCESS" and event.actor_name == "SYSTEM"
        assert event.actor_user_id is None and event.actor_org_id is None
        assert event.trace_id and event.occurred_at
        assert event.details_json == {
            "service": main_module.settings.app_name, "service_version": main_module.VERSION,
            "build_sha": "a" * 40, "environment": "test", "startup_state": "INITIALIZED",
        }
        assert "canary" not in str(event.details_json)


def test_admin_can_read_startup_event_only_through_existing_sanitized_projection(technical_runtime):
    sessions, _stages = technical_runtime
    with sessions() as db:
        for account, role in (("admin", "ADMIN"), ("generator", "GENERATOR")):
            db.add(Organization(org_id=account, org_name=account, org_type=role, energy_domain="electricity"))
            db.flush()
            db.add(User(user_id=account, org_id=account, username=account, password_hash="unused",
                        display_name=account, role_code=role))
        db.flush()
        db.add(AuditLog(actor_user_id="generator", actor_org_id="generator", actor_name="tenant-private-canary",
                        action_code="LOGIN", target_type="USER", target_id="tenant-private-canary",
                        result="SUCCESS", trace_id="business-private-canary", details_json={"private": "business-private-canary"}))
        db.commit()
    _start()
    client = TestClient(main_module.app)  # Lifespan was already exercised above.
    try:
        admin = {"Authorization": "Bearer " + create_access_token("admin", "ADMIN", "admin")}
        response = client.get("/api/audit/logs", headers=admin)
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1
        item = response.json()[0]
        assert set(item) == {"log_id", "occurred_at", "actor_name", "action_code", "target_type", "target_id", "result", "trace_id", "details_json"}
        assert item["action_code"] == "SYSTEM_STARTUP" and item["target_type"] == "SYSTEM"
        assert item["actor_name"] == "平台服务" and item["target_id"] == "已脱敏"
        assert item["details_json"] == {"message": "业务内容不向平台运维账号开放"}
        assert "canary" not in response.text and "build_sha" not in response.text
        assert client.get("/api/audit/logs?action_code=LOGIN", headers=admin).json() == []
        repeated = client.get("/api/audit/logs?action_code=SYSTEM_STARTUP", headers=admin)
        assert repeated.status_code == 200 and repeated.json() == [item]
        provider = {"Authorization": "Bearer " + create_access_token("generator", "GENERATOR", "generator")}
        assert client.get("/api/audit/logs", headers=provider).status_code == 403
    finally:
        client.close()
    with sessions() as db:
        assert len(db.scalars(select(AuditLog).where(AuditLog.action_code == "SYSTEM_STARTUP")).all()) == 1


@pytest.mark.parametrize("failed_stage", ["validate_runtime_settings", "ensure_runtime_schema", "ensure_agent_tool_catalog"])
def test_failed_startup_never_records_a_false_success(technical_runtime, monkeypatch, failed_stage):
    sessions, _stages = technical_runtime

    def fail(*_args, **_kwargs):
        raise RuntimeError("startup stage failed")

    monkeypatch.setattr(main_module, failed_stage, fail)
    with pytest.raises(RuntimeError, match="startup stage failed"):
        _start()
    with sessions() as db:
        assert db.scalars(select(AuditLog).where(AuditLog.action_code == "SYSTEM_STARTUP")).all() == []
