from __future__ import annotations

import importlib.metadata
import importlib.util


HEADER_NAME = "X-Request-ID"
VERSION = "5.0.1"


def correlation_status() -> dict[str, object]:
    """Expose request-correlation capability without returning request data."""
    installed = importlib.util.find_spec("asgi_correlation_id") is not None
    version = VERSION
    if installed:
        try:
            version = importlib.metadata.version("asgi-correlation-id")
        except importlib.metadata.PackageNotFoundError:
            pass
    return {
        "code": "ASGI_CORRELATION_ID_5_0_1",
        "version": version,
        "installed": installed,
        "header": HEADER_NAME,
        "validation": "UUID_COMPATIBLE_32_HEX",
        "raw_data_exposed": False,
    }
