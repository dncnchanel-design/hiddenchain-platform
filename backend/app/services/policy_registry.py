from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DataContract
from ..security import sha256_json
from ..trust_models import UsagePolicy, UsagePolicyVersion


def project_contract_policy(
    db: Session,
    contract: DataContract,
) -> UsagePolicyVersion:
    """Persist an immutable, versioned view of a negotiated usage policy."""

    policy_code = f"USAGE:{contract.provider_org_id}:{contract.purpose}"
    policy = db.scalar(
        select(UsagePolicy).where(UsagePolicy.policy_code == policy_code)
    )
    if policy is None:
        policy = UsagePolicy(
            policy_code=policy_code,
            policy_name=f"{contract.purpose} usage policy",
            owner_org_id=contract.provider_org_id,
            policy_type="ODRL_COMPAT_USAGE",
            current_version_no=0,
            status="ACTIVE",
        )
        db.add(policy)
        db.flush()
    existing = db.scalar(
        select(UsagePolicyVersion).where(
            UsagePolicyVersion.policy_id == policy.policy_id,
            UsagePolicyVersion.policy_hash == contract.policy_hash,
        )
    )
    if existing is not None:
        return existing
    version_no = int(
        db.scalar(
            select(func.max(UsagePolicyVersion.version_no)).where(
                UsagePolicyVersion.policy_id == policy.policy_id
            )
        )
        or 0
    ) + 1
    valid_from = contract.valid_from or contract.created_at
    expires_at = contract.expires_at
    if expires_at is None:
        configured_expiry = (contract.policy_json or {}).get("constraint", {}).get(
            "expires_at"
        )
        if configured_expiry:
            expires_at = datetime.fromisoformat(
                str(configured_expiry).replace("Z", "+00:00")
            ).replace(tzinfo=None)
    immutable_payload = {
        "policy_id": policy.policy_id,
        "version_no": version_no,
        "policy_hash": contract.policy_hash,
        "policy": contract.policy_json,
        "valid_from": valid_from.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    version = UsagePolicyVersion(
        policy_id=policy.policy_id,
        version_no=version_no,
        policy_json=contract.policy_json,
        policy_hash=contract.policy_hash,
        immutable_hash=sha256_json(immutable_payload),
        valid_from=valid_from,
        expires_at=expires_at,
        status="ACTIVE",
    )
    db.add(version)
    db.flush()
    policy.current_version_no = version_no
    return version
