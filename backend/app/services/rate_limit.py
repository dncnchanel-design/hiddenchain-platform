from __future__ import annotations

import importlib.util

from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import settings


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.rate_limit_storage_uri,
    enabled=settings.rate_limit_enabled,
    # FastAPI serializes dict return values after the sync endpoint returns;
    # leave optional X-RateLimit headers off rather than requiring every
    # protected handler to construct a Starlette Response explicitly.
    headers_enabled=False,
    key_prefix="hiddenchain",
)


def rate_limit_status() -> dict[str, object]:
    """Expose safe limiter metadata without returning storage credentials."""
    storage_uri = settings.rate_limit_storage_uri.lower()
    storage = "REDIS_EXTERNAL" if storage_uri.startswith(("redis://", "rediss://")) else "MEMORY_SINGLE_INSTANCE"
    return {
        "code": "SLOWAPI_RATE_LIMIT_0_1_10",
        "version": "0.1.10",
        "installed": importlib.util.find_spec("slowapi") is not None,
        "enabled": limiter.enabled,
        "storage": storage,
        "protected_routes": ["POST /api/auth/login"],
        "login_limit": settings.auth_login_rate_limit,
        "raw_data_exposed": False,
    }
