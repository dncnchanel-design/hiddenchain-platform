from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
RUNTIME_DIR = BASE_DIR / "runtime"
VAULT_DIR = RUNTIME_DIR / "vault"


def _load_local_env() -> None:
    """Load local dotenv files without overriding explicitly supplied variables."""
    for path in (PROJECT_DIR / ".env", BASE_DIR / ".env"):
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if not name or name in os.environ:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
                value = value[1:-1]
            os.environ[name] = value


_load_local_env()


VALID_APP_ENVIRONMENTS = {"development", "test", "demo", "production"}


def _app_env() -> str:
    value = os.getenv("APP_ENV", "development").strip().lower()
    return value or "development"


def _default_environment_name(app_env: str) -> str:
    return {
        "development": "开发环境",
        "test": "测试环境",
        "demo": "公开演示环境",
        "production": "",
    }.get(app_env, "")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    app_env: str = _app_env()
    product_name: str = os.getenv("PRODUCT_NAME", "隐链明算")
    product_short_name: str = os.getenv("PRODUCT_SHORT_NAME", "隐链明算")
    product_subtitle: str = os.getenv("PRODUCT_SUBTITLE", "多能源可信数据空间")
    logo: str = os.getenv("PRODUCT_LOGO", "")
    logo_compact: str = os.getenv("PRODUCT_LOGO_COMPACT", "")
    favicon: str = os.getenv("PRODUCT_FAVICON", "")
    brand_theme_id: str = os.getenv("BRAND_THEME_ID", "trusted-space-navy")
    brand_primary: str = os.getenv("BRAND_PRIMARY", "#1768A0")
    customer_name: str = os.getenv("CUSTOMER_NAME", "")
    operator_name: str = os.getenv("OPERATOR_NAME", "")
    builder_name: str = os.getenv("BUILDER_NAME", "")
    copyright_owner: str = os.getenv("COPYRIGHT_OWNER", "")
    copyright_year: str = os.getenv("COPYRIGHT_YEAR", "")
    support_name: str = os.getenv("SUPPORT_NAME", "")
    support_contact: str = os.getenv("SUPPORT_CONTACT", "")
    environment_name: str = os.getenv(
        "ENVIRONMENT_NAME", _default_environment_name(_app_env())
    )
    login_notice: str = os.getenv("LOGIN_NOTICE", "")
    app_name: str = os.getenv("API_SERVICE_NAME", "隐链明算可信数据空间服务")
    api_prefix: str = "/api"
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{(RUNTIME_DIR / 'hiddenchain.db').as_posix()}"
    )
    # Development and test retain deterministic local secrets. Production is
    # rejected at startup until unique deployment secrets are supplied.
    jwt_secret: str = os.getenv(
        "JWT_SECRET", "hiddenchain-development-jwt-secret-local-only"
    )
    signing_secret: str = os.getenv(
        "SIGNING_SECRET", "hiddenchain-development-signing-secret-local-only"
    )
    jwt_expire_minutes: int = _int_env("JWT_EXPIRE_MINUTES", 720)
    cors_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if item.strip()
    )
    test_fixture_seed: bool = _bool_env(
        "TEST_FIXTURE_SEED", _app_env() in {"development", "test"}
    )
    demo_catalog_seed: bool = _bool_env("DEMO_CATALOG_SEED", _app_env() == "demo")
    test_compute_delay_ms: int = _int_env("TEST_COMPUTE_DELAY_MS", 0)
    opa_url: str = os.getenv("OPA_URL", "").rstrip("/")
    opa_policy_path: str = os.getenv("OPA_POLICY_PATH", "/v1/data/hiddenchain/decision")
    opa_timeout_seconds: float = _float_env("OPA_TIMEOUT_SECONDS", 1.0)
    opa_local_fallback: bool = _bool_env("OPA_LOCAL_FALLBACK", True)
    execution_policy_path: str = os.getenv(
        "EXECUTION_POLICY_PATH", str(PROJECT_DIR / "policy" / "energy_execution_policy.json")
    )
    execution_audit_workers: int = _int_env("EXECUTION_AUDIT_WORKERS", 2)
    # SlowAPI protects the credential entry point. Production deployments with
    # multiple replicas must use a shared rate-limit store.
    rate_limit_enabled: bool = _bool_env("RATE_LIMIT_ENABLED", True)
    rate_limit_storage_uri: str = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")
    auth_login_rate_limit: str = os.getenv("AUTH_LOGIN_RATE_LIMIT", "10/minute")
    # OpenTelemetry is opt-in; deployments can send traces to any
    # OTLP-compatible collector without changing application code.
    otel_enabled: bool = _bool_env("OTEL_ENABLED", False)
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "hiddenchain-platform")
    otel_otlp_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    otel_otlp_headers: str = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    otel_console_export: bool = _bool_env("OTEL_CONSOLE_EXPORT", False)
    # OpenLineage events are local JSONL by default.  They contain only data
    # product references, commitments and hashes; raw provider payloads never
    # enter the event stream.
    openlineage_enabled: bool = _bool_env("OPENLINEAGE_ENABLED", True)
    openlineage_namespace: str = os.getenv("OPENLINEAGE_NAMESPACE", "hiddenchain")
    openlineage_path: str = os.getenv(
        "OPENLINEAGE_PATH", str(RUNTIME_DIR / "lineage" / "events.jsonl")
    )
    openlineage_http_url: str = os.getenv("OPENLINEAGE_HTTP_URL", "").rstrip("/")
    # The bound is part of the DP contract.  Production deployments should
    # calibrate it to the actual meter-group domain before changing the value.
    dp_max_load_mw: float = _float_env("DP_MAX_LOAD_MW", 100.0)
    deepseek_enabled: bool = _bool_env("DEEPSEEK_ENABLED", False)
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    deepseek_timeout_seconds: float = _float_env("DEEPSEEK_TIMEOUT_SECONDS", 20.0)
    deepseek_max_tokens: int = _int_env("DEEPSEEK_MAX_TOKENS", 800)
    platform_signing_private_key: str = os.getenv("PLATFORM_SIGNING_PRIVATE_KEY", "")
    connector_endpoints_json: str = os.getenv("CONNECTOR_ENDPOINTS_JSON", "{}")
    connector_public_keys_json: str = os.getenv("CONNECTOR_PUBLIC_KEYS_JSON", "{}")
    connector_timeout_seconds: float = _float_env("CONNECTOR_TIMEOUT_SECONDS", 15.0)


settings = Settings()


def public_branding(settings_value: Settings = settings) -> dict[str, object]:
    """Return the non-sensitive runtime configuration consumed by the web UI."""

    demo_accounts = []
    if settings_value.app_env == "demo":
        demo_accounts = [
            {"label": "发电企业", "username": "generator", "password": "generator123"},
            {"label": "售电企业", "username": "retailer", "password": "retailer123"},
            {"label": "煤炭企业", "username": "coal", "password": "coal123"},
            {"label": "热能企业", "username": "heat", "password": "heat123"},
            {"label": "天然气企业", "username": "gas", "password": "gas123"},
            {"label": "石油企业", "username": "oil", "password": "oil123"},
            {"label": "电力交易中心", "username": "exchange", "password": "exchange123"},
            {"label": "煤炭交易中心", "username": "exchange_coal", "password": "exchange123"},
            {"label": "热能交易中心", "username": "exchange_heat", "password": "exchange123"},
            {"label": "天然气交易中心", "username": "exchange_gas", "password": "exchange123"},
            {"label": "石油交易中心", "username": "exchange_oil", "password": "exchange123"},
            {"label": "监管方", "username": "regulator", "password": "regulator123"},
            {"label": "平台运维", "username": "admin", "password": "admin123"},
        ]

    return {
        "productName": settings_value.product_name,
        "productShortName": settings_value.product_short_name,
        "productSubtitle": settings_value.product_subtitle,
        "logo": settings_value.logo,
        "logoCompact": settings_value.logo_compact,
        "favicon": settings_value.favicon,
        "brandTheme": {
            "themeId": settings_value.brand_theme_id,
            "primary": settings_value.brand_primary,
        },
        "customerName": settings_value.customer_name,
        "operatorName": settings_value.operator_name,
        "builderName": settings_value.builder_name,
        "copyrightOwner": settings_value.copyright_owner,
        "copyrightYear": settings_value.copyright_year,
        "supportName": settings_value.support_name,
        "supportContact": settings_value.support_contact,
        "environmentName": settings_value.environment_name,
        "loginNotice": settings_value.login_notice,
        "environment": settings_value.app_env,
        "demoAccounts": demo_accounts,
        "features": {
            "fixtureImport": settings_value.app_env in {"development", "test"},
            "anomalyInjection": settings_value.app_env in {"development", "test"},
            "testOperations": settings_value.app_env in {"development", "test"},
        },
    }


def validate_runtime_settings(settings_value: Settings = settings) -> None:
    """Fail closed when a production process is configured like a test system."""

    if settings_value.app_env not in VALID_APP_ENVIRONMENTS:
        allowed = ", ".join(sorted(VALID_APP_ENVIRONMENTS))
        raise RuntimeError(f"APP_ENV must be one of: {allowed}")
    if settings_value.app_env != "production":
        return

    errors: list[str] = []
    if settings_value.test_fixture_seed:
        errors.append("TEST_FIXTURE_SEED must be false")
    if settings_value.test_compute_delay_ms:
        errors.append("TEST_COMPUTE_DELAY_MS must be 0")
    if settings_value.opa_local_fallback:
        errors.append("OPA_LOCAL_FALLBACK must be false")
    for name, value in {
        "JWT_SECRET": settings_value.jwt_secret,
        "SIGNING_SECRET": settings_value.signing_secret,
    }.items():
        lowered = value.lower()
        if len(value) < 32 or "local-only" in lowered or "replace" in lowered:
            errors.append(f"{name} must be a unique value of at least 32 characters")
    if settings_value.jwt_secret == settings_value.signing_secret:
        errors.append("JWT_SECRET and SIGNING_SECRET must be different")
    if not settings_value.opa_url:
        errors.append("OPA_URL must identify the production policy service")
    if not settings_value.cors_origins or any(
        origin == "*" or "localhost" in origin or "127.0.0.1" in origin
        for origin in settings_value.cors_origins
    ):
        errors.append("CORS_ORIGINS must contain only explicit production origins")
    if settings_value.environment_name in {"开发环境", "测试环境", "演示环境"}:
        errors.append("ENVIRONMENT_NAME cannot identify a non-production environment")
    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
VAULT_DIR.mkdir(parents=True, exist_ok=True)
