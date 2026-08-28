from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AccessRule, LocalSubjectNode, User


ENERGY_SUBJECT_ROLES = frozenset(
    {
        "GENERATOR",
        "RETAILER",
        "COAL_ENTERPRISE",
        "HEAT_ENTERPRISE",
        "GAS_ENTERPRISE",
        "OIL_ENTERPRISE",
        "EXCHANGE",
    }
)
RULE_AUTO = "AUTO_CALL"
RULE_APPROVAL = "ENTERPRISE_APPROVAL"
RULE_FORBIDDEN = "FORBIDDEN"
CLOSED_USAGE_DOMAIN_PAIR = frozenset({"electricity", "oil"})


def has_permission(user: User, permission: str) -> bool:
    return permission in set(user.permissions_json or [])


def can_view_subject_metadata(user: User, owner_org_id: str) -> bool:
    """Catalog metadata is public to a regulator and the owning subject."""

    return user.role_code == "REGULATOR" or user.org_id == owner_org_id


def same_energy_domain_metadata_visible(
    user: User,
    owner_org_id: str,
    *,
    viewer_energy_domain: str | None,
    owner_energy_domain: str | None,
) -> bool:
    """Allow business users to discover metadata within their own energy domain."""

    if can_view_subject_metadata(user, owner_org_id):
        return True
    return bool(
        user.role_code in ENERGY_SUBJECT_ROLES
        and viewer_energy_domain
        and owner_energy_domain
        and viewer_energy_domain == owner_energy_domain
    )


def usage_domain_pair_is_closed(
    applicant_energy_domain: str | None,
    provider_energy_domain: str | None,
) -> bool:
    """Keep the electricity/oil application channel closed for business users."""

    if not applicant_energy_domain or not provider_energy_domain:
        return False
    return frozenset({applicant_energy_domain, provider_energy_domain}) == CLOSED_USAGE_DOMAIN_PAIR


def can_view_subject_value(user: User, provider_org_id: str, *, authorized: bool = False) -> bool:
    """A subject value requires own-tenant scope or an explicit authorization."""

    if user.role_code == "ADMIN":
        return False
    return user.org_id == provider_org_id or (user.role_code == "REGULATOR" and authorized)


def can_manage_subject_rule(user: User, owner_org_id: str) -> bool:
    return (
        user.org_id == owner_org_id
        and user.role_code in ENERGY_SUBJECT_ROLES
        and has_permission(user, "MANAGE_RULES")
    )


def parse_subject_map(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): str(endpoint) for key, endpoint in value.items() if endpoint}


def subject_node_config(db: Session, provider_org_id: str) -> dict[str, Any] | None:
    node = db.scalar(
        select(LocalSubjectNode)
        .where(LocalSubjectNode.org_id == provider_org_id, LocalSubjectNode.status == "ACTIVE")
        .order_by(LocalSubjectNode.created_at.desc())
    )
    endpoint_map = parse_subject_map(
        getattr(settings, "subject_node_endpoints_json", settings.connector_endpoints_json)
    )
    key_map = parse_subject_map(
        getattr(settings, "subject_node_public_keys_json", settings.connector_public_keys_json)
    )
    if node is None and provider_org_id not in endpoint_map:
        return None
    return {
        "org_id": provider_org_id,
        "node_id": node.node_id if node else None,
        "node_code": node.node_code if node else f"subject-node-{provider_org_id}",
        "endpoint": (node.endpoint_ref if node and node.endpoint_ref else endpoint_map.get(provider_org_id)),
        "public_key": (node.public_key if node and node.public_key else key_map.get(provider_org_id)),
        "environment": node.environment if node else "DEMO_ADAPTER",
    }


def _scope_matches(rule: AccessRule, requested_scope: dict[str, Any]) -> bool:
    limits = rule.limits_json if isinstance(rule.limits_json, dict) else {}
    requested = requested_scope if isinstance(requested_scope, dict) else {}
    if requested.get("raw_data_export"):
        return False
    for key in ("granularity", "region", "output_mode"):
        allowed = limits.get(key)
        if allowed is not None and requested.get(key) not in (None, allowed):
            return False
    min_records = limits.get("minimum_record_count")
    if min_records is not None and requested.get("minimum_record_count", min_records) < min_records:
        return False
    max_days = limits.get("max_duration_days")
    if max_days is not None and requested.get("duration_days", max_days) > max_days:
        return False
    return True


def matching_rule(
    db: Session,
    *,
    owner_org_id: str,
    resource_id: str,
    function_code: str,
    requested_scope: dict[str, Any] | None = None,
) -> AccessRule | None:
    rules = db.scalars(
        select(AccessRule)
        .where(
            AccessRule.owner_org_id == owner_org_id,
            AccessRule.resource_id == resource_id,
            AccessRule.function_code == function_code,
            AccessRule.status == "ACTIVE",
            AccessRule.revoked_at.is_(None),
        )
        .order_by(AccessRule.version_no.desc())
    ).all()
    requested = requested_scope or {}
    for rule in rules:
        if _scope_matches(rule, requested):
            return rule
    return None


def rule_decision(rule: AccessRule | None) -> str:
    if rule is None:
        return RULE_APPROVAL
    return rule.mode if rule.mode in {RULE_AUTO, RULE_APPROVAL, RULE_FORBIDDEN} else RULE_APPROVAL


def metadata_only_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Remove value-like fields before a cross-subject catalog response."""

    hidden = {"value", "values", "result", "records", "raw_payload", "local_payload"}
    return {key: value for key, value in entry.items() if key not in hidden}
