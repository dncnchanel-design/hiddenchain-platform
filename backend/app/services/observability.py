from __future__ import annotations

import importlib.util
import logging
from typing import Any

from fastapi import FastAPI

from ..config import settings


logger = logging.getLogger(__name__)
_instrumented = False
_status: dict[str, Any] = {
    "enabled": False,
    "instrumented": False,
    "exporter": "none",
    "error": None,
}


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            headers[key] = value.strip()
    return headers


def _otlp_trace_endpoint(endpoint: str) -> str:
    if not endpoint:
        return endpoint
    return endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"


def setup_observability(app: FastAPI) -> None:
    """Install optional OpenTelemetry FastAPI tracing.

    The application intentionally keeps telemetry opt-in.  When enabled, no
    request body or business payload is added by this module; the standard
    FastAPI instrumentation records route, status and timing information only.
    """

    global _instrumented
    if _instrumented or not settings.otel_enabled:
        _status.update({"enabled": settings.otel_enabled, "instrumented": _instrumented})
        return

    if importlib.util.find_spec("opentelemetry") is None:
        _status.update(
            {
                "enabled": True,
                "instrumented": False,
                "exporter": "none",
                "error": "OPENTELEMETRY_NOT_INSTALLED",
            }
        )
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.otel_service_name})
        )
        exporters: list[str] = []
        if settings.otel_otlp_endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=_otlp_trace_endpoint(settings.otel_otlp_endpoint),
                        headers=_parse_headers(settings.otel_otlp_headers),
                    )
                )
            )
            exporters.append("otlp-http")
        if settings.otel_console_export:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            exporters.append("console")
        if not exporters:
            _status.update(
                {
                    "enabled": True,
                    "instrumented": False,
                    "exporter": "none",
                    "error": "OTEL_EXPORTER_NOT_CONFIGURED",
                }
            )
            return

        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        _instrumented = True
        _status.update(
            {
                "enabled": True,
                "instrumented": True,
                "exporter": "+".join(exporters),
                "service_name": settings.otel_service_name,
                "error": None,
            }
        )
    except Exception as exc:  # pragma: no cover - depends on deployment extras
        logger.warning("OpenTelemetry setup failed: %s", type(exc).__name__)
        _status.update(
            {
                "enabled": True,
                "instrumented": False,
                "exporter": "none",
                "error": type(exc).__name__,
            }
        )


def observability_status() -> dict[str, Any]:
    """Return safe configuration metadata without exposing OTLP credentials."""

    return {
        **_status,
        "package_available": importlib.util.find_spec("opentelemetry") is not None,
        "otlp_endpoint_configured": bool(settings.otel_otlp_endpoint),
        "console_export_configured": settings.otel_console_export,
        "trace_correlation": "audit.trace_id uses the active OpenTelemetry span when available",
    }
