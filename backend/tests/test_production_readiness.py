from __future__ import annotations

import subprocess
import sys
import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings, public_branding, validate_runtime_settings
from app.database import SessionLocal
from app.production import assert_production_database_clean


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def production_settings(**changes) -> Settings:
    base = Settings(
        app_env="production",
        test_fixture_seed=False,
        test_compute_delay_ms=0,
        opa_local_fallback=False,
        jwt_secret="production-jwt-secret-value-00000001",
        signing_secret="production-signing-secret-value-0002",
        opa_url="https://policy.example.com",
        cors_origins=("https://settlement.example.com",),
        environment_name="",
    )
    return replace(base, **changes)


def test_valid_production_configuration_passes() -> None:
    validate_runtime_settings(production_settings())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"test_fixture_seed": True}, "TEST_FIXTURE_SEED"),
        ({"test_compute_delay_ms": 50}, "TEST_COMPUTE_DELAY_MS"),
        ({"opa_local_fallback": True}, "OPA_LOCAL_FALLBACK"),
        ({"jwt_secret": "replace-me"}, "JWT_SECRET"),
        ({"cors_origins": ("http://localhost:8080",)}, "CORS_ORIGINS"),
        ({"environment_name": "测试环境"}, "ENVIRONMENT_NAME"),
    ],
)
def test_unsafe_production_configuration_fails(changes: dict, message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        validate_runtime_settings(production_settings(**changes))


def test_public_branding_contains_white_label_fields_and_safe_feature_flags() -> None:
    payload = public_branding(
        production_settings(
            product_name="客户结算平台",
            product_short_name="客户结算",
            customer_name="示例客户",
            operator_name="示例运营方",
            logo="/branding/logo.svg",
            brand_theme_id="neutral-blue",
            brand_primary="#1769AA",
        )
    )
    assert payload["productName"] == "客户结算平台"
    assert payload["productShortName"] == "客户结算"
    assert payload["customerName"] == "示例客户"
    assert payload["operatorName"] == "示例运营方"
    assert payload["logo"] == "/branding/logo.svg"
    assert payload["brandTheme"] == {
        "themeId": "neutral-blue",
        "primary": "#1769AA",
    }
    assert payload["environment"] == "production"
    assert payload["features"] == {
        "fixtureImport": False,
        "anomalyInjection": False,
        "testOperations": False,
    }


def test_production_database_guard_rejects_seeded_test_records() -> None:
    with SessionLocal() as db, pytest.raises(RuntimeError, match="non-production records"):
        assert_production_database_clean(db, production_settings())


def test_static_production_build_guard_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "backend" / "scripts" / "check_production.py")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_production_route_table_excludes_test_operations() -> None:
    blocked = {
        "/api/auth/test-users",
        "/api/settlement/import-and-run",
        "/api/anomalies/inject",
        "/api/trusted-execution/example",
    }
    program = (
        "from app.main import app; "
        f"blocked={blocked!r}; "
        "paths=set(app.openapi()['paths']); "
        "assert not (blocked & paths), sorted(blocked & paths)"
    )
    environment = {
        **os.environ,
        "APP_ENV": "production",
        "TEST_FIXTURE_SEED": "false",
        "TEST_COMPUTE_DELAY_MS": "0",
        "OPA_LOCAL_FALLBACK": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=PROJECT_ROOT / "backend",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
