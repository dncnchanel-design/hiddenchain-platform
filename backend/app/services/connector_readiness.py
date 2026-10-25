"""Public browser health targets from configured, registered subject metadata."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from ..config import parse_subject_map, settings
from ..models import Organization
from .local_data_boundary import subject_node_config


def browser_connector_readiness(
    db: Session,
    organization_id: str,
    energy_domain: str,
) -> dict[str, Any] | None:
    """Describe one scoped public GET; callers retain all authorization gates.

    This never contacts a node, exposes signing material, or accepts a target
    from a browser. The descriptor is a wake hint, not evidence of readiness.
    """
    organization = db.get(Organization, organization_id)
    if (
        organization is None
        or organization.status != "ACTIVE"
        or not energy_domain
        or organization.energy_domain != energy_domain
    ):
        return None
    node = subject_node_config(db, organization_id)
    if not node or not node.get("node_id") or not node.get("node_code") or node.get("org_id") != organization_id:
        return None
    endpoint = parse_subject_map(settings.subject_node_browser_endpoints_json).get(organization_id, "")
    if not endpoint or "\\" in endpoint or any(ord(character) <= 32 or ord(character) == 127 for character in endpoint):
        return None
    try:
        parsed = urlsplit(endpoint)
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or not (
                parsed.scheme == "https"
                or settings.app_env in {"development", "test", "demo"}
                and parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            return None
    except ValueError:
        return None
    return {
        "health_url": urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/health", "", "")),
        "organization_id": organization_id,
        "energy_domain": energy_domain,
        "connector_id": node["node_code"],
        "raw_data_accessed": False,
    }
