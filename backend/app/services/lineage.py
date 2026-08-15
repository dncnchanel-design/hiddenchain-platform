from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import settings


logger = logging.getLogger(__name__)
SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json"
PRODUCER = "https://github.com/dncnchanel-design/hiddenchain-platform"
_write_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_uuid(run_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{settings.openlineage_namespace}:{run_id}"))


def _facet(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "_producer": PRODUCER,
        "_schemaURL": f"{SCHEMA_URL}#/$defs/BaseFacet",
        **values,
    }


def _dataset(
    *,
    namespace: str,
    name: str,
    direction: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    facet_name = "inputFacets" if direction == "input" else "outputFacets"
    return {
        "namespace": namespace,
        "name": name,
        facet_name: {"hiddenchain": _facet(metadata)},
    }


def input_dataset(
    *,
    namespace: str,
    name: str,
    data_product_id: str,
    asset_type: str,
    data_hash: str | None,
    commitment: str | None,
) -> dict[str, Any]:
    """Build a redacted OpenLineage input dataset descriptor."""

    return _dataset(
        namespace=namespace,
        name=name,
        direction="input",
        metadata={
            "dataProductId": data_product_id,
            "assetType": asset_type,
            "dataHash": data_hash,
            "commitment": commitment,
            "rawDataExposed": False,
        },
    )


def _write_event(event: dict[str, Any]) -> str | None:
    if not settings.openlineage_enabled:
        return None
    path = Path(settings.openlineage_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        return str(path)
    except OSError as exc:
        # Lineage is a diagnostic/audit export and must never make the trusted
        # execution path fail after its database transaction has succeeded.
        logger.warning("OpenLineage local write failed: %s", type(exc).__name__)
        return None


def _post_event(event: dict[str, Any]) -> str | None:
    if not settings.openlineage_enabled or not settings.openlineage_http_url:
        return None
    try:
        import httpx

        response = httpx.post(settings.openlineage_http_url, json=event, timeout=2.0)
        response.raise_for_status()
        return "http"
    except Exception as exc:  # pragma: no cover - external collector dependent
        logger.warning("OpenLineage HTTP export failed: %s", type(exc).__name__)
        return None


def emit_run_event(
    *,
    run_id: str,
    job_name: str,
    event_type: str,
    trace_id: str,
    input_datasets: Iterable[dict[str, Any]],
    output_name: str,
    output_hash: str | None,
    result_status: str,
    policy_hash: str | None = None,
    raw_data_exported: bool = False,
) -> dict[str, Any]:
    """Emit a redacted OpenLineage RunEvent for a trusted execution.

    Only stable identifiers, commitments, policy/result hashes and security
    flags are accepted into the event.  Callers should pass data product
    metadata rather than vault paths or provider payloads.
    """

    event = {
        "eventType": event_type,
        "eventTime": _utc_now(),
        "producer": PRODUCER,
        "schemaURL": SCHEMA_URL,
        "run": {
            "runId": _run_uuid(run_id),
            "facets": {
                "hiddenchain_security": _facet(
                    {
                        "runId": run_id,
                        "traceId": trace_id,
                        "resultStatus": result_status,
                        "policyHash": policy_hash,
                        "rawDataExported": bool(raw_data_exported),
                    }
                )
            },
        },
        "job": {
            "namespace": settings.openlineage_namespace,
            "name": job_name,
        },
        "inputs": list(input_datasets),
        "outputs": [
            _dataset(
                namespace=settings.openlineage_namespace,
                name=output_name,
                direction="output",
                metadata={
                    "resultHash": output_hash,
                    "resultStatus": result_status,
                    "rawDataExported": bool(raw_data_exported),
                },
            )
        ],
    }
    local_path = _write_event(event)
    http_export = _post_event(event)
    return {
        "emitted": bool(local_path or http_export),
        "event_type": event_type,
        "run_id": run_id,
        "event_id": event["run"]["runId"],
        "local_path": local_path,
        "http_exported": bool(http_export),
        "raw_data_exported": bool(raw_data_exported),
    }


def read_run_events(run_id: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
    path = Path(settings.openlineage_path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        facet = event.get("run", {}).get("facets", {}).get("hiddenchain_security", {})
        if run_id and facet.get("runId") != run_id:
            continue
        events.append(event)
        if len(events) >= max(limit, 1):
            break
    return list(reversed(events))


def lineage_status() -> dict[str, Any]:
    return {
        "enabled": settings.openlineage_enabled,
        "namespace": settings.openlineage_namespace,
        "schema_url": SCHEMA_URL,
        "local_path": settings.openlineage_path,
        "http_export_configured": bool(settings.openlineage_http_url),
        "raw_data_policy": "only data product references, commitments and hashes; raw payloads excluded",
    }
