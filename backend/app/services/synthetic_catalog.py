"""Verify metadata-only v2 seed catalogs without importing or generating raw data."""
from __future__ import annotations

import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.orm import Session

from ..config import settings
from ..security import canonical_json, sha256_json
from .common import add_audit_log
from .local_data_boundary import subject_node_config


SEED_VERSION = "hiddenchain-demo-seed-v2"
PERIOD_START = "2021-01-01"
PERIOD_END = "2026-09-30"
PERIOD_DAYS = 2099
REGIONS = ["东部片区", "西部片区", "南部片区", "北部片区"]
HEX_HASH = re.compile(r"^[0-9a-f]{64}$")
HOURLY_RESOURCES = frozenset({("electricity", "supply"), ("electricity", "load"), ("heat", "supply"), ("heat", "load"), ("gas", "supply")})
STARTUP_SYNC_BUDGET_SECONDS = 45.0


class SyntheticCatalogError(ValueError):
    pass


def verify_catalog(
    payload: dict[str, Any],
    *,
    public_key: str,
    connector_id: str,
    owner_org_id: str,
    domain: str,
    units: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("signature_algorithm") != "Ed25519" or payload.get("public_key") != public_key:
        raise SyntheticCatalogError("SYNTHETIC_CATALOG_SIGNATURE_INVALID")
    signed = {key: value for key, value in payload.items() if key not in {"signature", "public_key", "signature_algorithm", "signature_valid"}}
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True)).verify(
            base64.b64decode(payload["signature"], validate=True), canonical_json(signed).encode(),
        )
    except Exception as exc:
        raise SyntheticCatalogError("SYNTHETIC_CATALOG_SIGNATURE_INVALID") from exc
    if (
        signed.get("connector_id") != connector_id
        or signed.get("organization_id") != owner_org_id
        or signed.get("energy_domain") != domain
        or signed.get("seed_catalog_version") != SEED_VERSION
    ):
        raise SyntheticCatalogError("SYNTHETIC_CATALOG_IDENTITY_MISMATCH")
    resources = signed.get("resources")
    if not isinstance(resources, list) or len(resources) > len(units):
        raise SyntheticCatalogError("SYNTHETIC_CATALOG_RESOURCES_INVALID")
    verified: dict[str, dict[str, Any]] = {}
    seen = set()
    for item in resources:
        if not isinstance(item, dict) or item.get("resource_id") not in units or item["resource_id"] in seen:
            raise SyntheticCatalogError("SYNTHETIC_CATALOG_RESOURCES_INVALID")
        resource = item["resource_id"]
        seen.add(resource)
        seed = item.get("synthetic_seed")
        if item.get("latest_version") != 2 or item.get("current_schema_version") != SEED_VERSION or seed is None:
            continue  # CSV/unknown/legacy current versions are never promoted.
        if not isinstance(seed, dict) or seed.get("version") != 2 or seed.get("schema_version") != SEED_VERSION:
            raise SyntheticCatalogError("SYNTHETIC_CATALOG_VERSION_MISMATCH")
        description = seed.get("manifest")
        if not isinstance(description, dict):
            raise SyntheticCatalogError("SYNTHETIC_CATALOG_MANIFEST_INVALID")
        label = description.get("organization_label")
        if not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise SyntheticCatalogError("SYNTHETIC_CATALOG_MANIFEST_INVALID")
        unit = units[resource]
        hourly = (domain, resource) in HOURLY_RESOURCES
        expected_count = PERIOD_DAYS * len(REGIONS) * (25 if hourly else 1)
        expected = {
            "generator_version": SEED_VERSION,
            "connector_id": connector_id,
            "organization_label": label,
            "energy_domain": domain,
            "resource_id": resource,
            "unit": unit,
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "regions": REGIONS,
            "daily_rows_per_day": len(REGIONS),
            "hourly_available": hourly,
            "hourly_semantics": "daily_mean" if unit == "MW" else "daily_total",
            "value_decimals": 6,
            "record_count": expected_count,
        }
        expected_schema_hash = sha256_json({"schema_version": SEED_VERSION, "fields": ["record_date", "hour", "region", "organization", "value", "unit"], "unit": unit, "value_decimals": 6})
        if (
            description != expected
            or any(type(description.get(key)) is not type(value) for key, value in expected.items())
            or seed.get("manifest_hash") != sha256_json(expected)
            or item.get("unit") != unit
            or type(seed.get("record_count")) is not int
            or seed["record_count"] != expected_count
            or item.get("record_count") != expected_count
            or seed.get("local_ref") != f"connector://{connector_id}/{resource}/versions/2"
            or seed.get("schema_hash") != expected_schema_hash
            or not isinstance(seed.get("content_hash"), str)
            or not HEX_HASH.fullmatch(seed["content_hash"])
        ):
            raise SyntheticCatalogError("SYNTHETIC_CATALOG_MANIFEST_INVALID")
        verified[resource] = seed
    return verified


def _fetch_catalog(request: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]] | None, str | None]:
    owner, domain, node, units = (request[key] for key in ("owner", "domain", "node", "units"))
    deadline = request.get("deadline", time.monotonic() + STARTUP_SYNC_BUDGET_SECONDS)
    delay, error = 0.5, "SYNTHETIC_CONNECTOR_IDENTITY_UNAVAILABLE"
    while time.monotonic() < deadline:
        try:
            # Reuse the workbench trust anchor; retry availability, never an
            # identity/signature mismatch. All workers share one startup budget.
            from ..routers.prototype import _dashboard_connector_public_key

            public_key, _source, _latest = _dashboard_connector_public_key(
                endpoint=str(node["endpoint"]), node=node, provider_org_id=owner, energy_domain=domain,
            )
            response = httpx.get(f"{str(node['endpoint']).rstrip('/')}/catalog", timeout=min(2.0, max(0.1, deadline - time.monotonic())))
            if 400 <= response.status_code < 500 and response.status_code not in {408, 425, 429}:
                raise SyntheticCatalogError("SYNTHETIC_CATALOG_UNAVAILABLE")
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise SyntheticCatalogError("SYNTHETIC_CATALOG_RESPONSE_INVALID") from exc
            return owner, verify_catalog(payload, public_key=public_key, connector_id=node["node_code"], owner_org_id=owner, domain=domain, units=units), None
        except SyntheticCatalogError as exc:
            return owner, None, str(exc)
        except ValueError as exc:
            if str(exc) != "主体连接器身份发现暂不可用":
                return owner, None, "SYNTHETIC_CONNECTOR_IDENTITY_INVALID"
            error = "SYNTHETIC_CONNECTOR_IDENTITY_UNAVAILABLE"
        except httpx.HTTPError:
            error = "SYNTHETIC_CATALOG_UNAVAILABLE"
        except Exception:
            return owner, None, "SYNTHETIC_CONNECTOR_IDENTITY_UNAVAILABLE"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(delay, remaining))
        delay = min(3.0, delay * 2)
    return owner, None, error


def load_verified_catalogs(db: Session, owners: dict[str, tuple[str, dict[str, str]]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Seven subjects share 45s; a final bounded health read can overrun."""
    if not settings.demo_catalog_seed or settings.app_env not in {"demo", "development"}:
        return {}
    requests = []
    deadline = time.monotonic() + STARTUP_SYNC_BUDGET_SECONDS
    for owner, (domain, units) in sorted(owners.items()):
        node = subject_node_config(db, owner)
        if node and node.get("endpoint"):
            requests.append({"owner": owner, "domain": domain, "units": units, "node": node, "deadline": deadline})
        else:
            add_audit_log(db, action="DEMO_SYNTHETIC_CATALOG_SYNC", target_type="CONNECTOR", target_id=owner, result="FAILED", details={"code": "SYNTHETIC_CONNECTOR_NOT_CONFIGURED", "raw_data_accessed": False})
    catalogs = {}
    # SQLAlchemy sessions stay on this thread. Workers only fetch signed metadata.
    with ThreadPoolExecutor(max_workers=7) as pool:
        for owner, catalog, error in pool.map(_fetch_catalog, requests):
            if error:
                add_audit_log(db, action="DEMO_SYNTHETIC_CATALOG_SYNC", target_type="CONNECTOR", target_id=owner, result="FAILED", details={"code": error, "generator_version": SEED_VERSION, "raw_data_accessed": False})
            else:
                catalogs[owner] = catalog
    return catalogs
