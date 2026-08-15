from __future__ import annotations

from typing import Any

try:
    from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest
except (ImportError, ModuleNotFoundError):  # pragma: no cover - exercised by minimal offline installs
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    _REGISTRY = None
    _REQUEST_COUNT = None
    _REQUEST_DURATION = None
else:
    _REGISTRY = CollectorRegistry(auto_describe=True)
    _REQUEST_COUNT = Counter(
        "hiddenchain_http_requests",
        "HTTP requests observed by the HiddenChain API",
        labelnames=("method", "path", "status"),
        registry=_REGISTRY,
    )
    _REQUEST_DURATION = Histogram(
        "hiddenchain_http_request_duration_seconds",
        "HTTP request duration observed by the HiddenChain API",
        labelnames=("method", "path"),
        registry=_REGISTRY,
    )


def _safe_path(path: str | None) -> str:
    """Keep route labels bounded and free of raw IDs or query strings."""
    if not path or len(path) > 128 or not path.startswith("/"):
        return "/unmatched"
    return path


def observe_http_request(*, method: str, path: str | None, status_code: int, duration_seconds: float) -> None:
    if _REGISTRY is None or _REQUEST_COUNT is None or _REQUEST_DURATION is None:
        return
    safe_method = method.upper() if method else "UNKNOWN"
    safe_path = _safe_path(path)
    _REQUEST_COUNT.labels(method=safe_method, path=safe_path, status=str(status_code)).inc()
    _REQUEST_DURATION.labels(method=safe_method, path=safe_path).observe(max(duration_seconds, 0.0))


def render_metrics() -> bytes:
    if _REGISTRY is None:
        raise RuntimeError("PROMETHEUS_NOT_INSTALLED")
    return generate_latest(_REGISTRY)


def prometheus_status() -> dict[str, Any]:
    installed = _REGISTRY is not None
    return {
        "enabled": installed,
        "package_available": installed,
        "endpoint": "/api/metrics/prometheus" if installed else None,
        "registry": "dedicated_hiddenchain_registry" if installed else None,
        "raw_data_policy": "method, route template, status and duration only; no query or payload labels",
    }
