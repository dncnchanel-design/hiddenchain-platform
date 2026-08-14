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
    app_name: str = "隐链明算可信数据协同平台"
    api_prefix: str = "/api"
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{(RUNTIME_DIR / 'hiddenchain.db').as_posix()}"
    )
    jwt_secret: str = os.getenv("JWT_SECRET", "hiddenchain-demo-jwt-secret")
    signing_secret: str = os.getenv("SIGNING_SECRET", "hiddenchain-demo-signing-secret")
    jwt_expire_minutes: int = _int_env("JWT_EXPIRE_MINUTES", 720)
    cors_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if item.strip()
    )
    demo_seed: bool = _bool_env("DEMO_SEED", True)
    mock_delay_ms: int = _int_env("MOCK_DELAY_MS", 80)
    opa_url: str = os.getenv("OPA_URL", "").rstrip("/")
    opa_policy_path: str = os.getenv("OPA_POLICY_PATH", "/v1/data/hiddenchain/decision")
    opa_timeout_seconds: float = _float_env("OPA_TIMEOUT_SECONDS", 1.0)
    opa_local_fallback: bool = _bool_env("OPA_LOCAL_FALLBACK", True)
    execution_policy_path: str = os.getenv(
        "EXECUTION_POLICY_PATH", str(PROJECT_DIR / "policy" / "energy_execution_policy.json")
    )
    execution_audit_workers: int = _int_env("EXECUTION_AUDIT_WORKERS", 2)
    deepseek_enabled: bool = _bool_env("DEEPSEEK_ENABLED", False)
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    deepseek_timeout_seconds: float = _float_env("DEEPSEEK_TIMEOUT_SECONDS", 20.0)
    deepseek_max_tokens: int = _int_env("DEEPSEEK_MAX_TOKENS", 800)


settings = Settings()
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
VAULT_DIR.mkdir(parents=True, exist_ok=True)
