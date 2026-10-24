"""Narrow, audited approval for an authorized owner computing its own asset."""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..models import DataUsageRequest, Organization, User, new_id, utc_now
from ..security import sha256_json
from ..trust_models import DataAsset, DataAssetVersion, DataSource
from .common import add_audit_log
from .data_usage_requests import UsageRequestError, _active_identity

OWNER_QUERY_PERMISSIONS = frozenset({"VIEW_DATA", "APPROVE_AUTHORIZATION", "CREATE_COMPUTE_TASK"})


def _owned_asset(db: Session, user: User, asset_id: str):
    asset = db.get(DataAsset, asset_id)
    org = db.get(Organization, user.org_id)
    if user.role_code in {"ADMIN", "REGULATOR"} or user.status != "ACTIVE" or not OWNER_QUERY_PERMISSIONS.issubset(user.permissions_json or []):
        raise UsageRequestError(403, "OWNER_QUERY_PERMISSION_REQUIRED", "当前账号没有批准本方数据计算的权限")
    if asset is None or asset.owner_org_id != user.org_id:
        raise UsageRequestError(403, "OWNER_QUERY_SUBJECT_MISMATCH", "只能确认本主体的数据计算")
    version = db.get(DataAssetVersion, asset.current_version_id) if asset.current_version_id else None
    source = db.get(DataSource, asset.source_id)
    now = utc_now()
    if (org is None or org.status != "ACTIVE" or asset.status != "ACTIVE" or source is None or source.status != "ACTIVE"
            or source.owner_org_id != user.org_id or version is None or version.asset_id != asset.asset_id or version.status != "ACTIVE"
            or version.effective_from and version.effective_from > now or version.effective_until and version.effective_until <= now):
        raise UsageRequestError(409, "OWNER_QUERY_RESOURCE_UNAVAILABLE", "本方资源、数据版本或主体当前不可用")
    identity = _active_identity(db, user.org_id)
    return asset, version, org, identity


def validate_self_owned_query(db: Session, user: User, authorization: DataUsageRequest, asset: DataAsset) -> None:
    current, version, _org, _identity = _owned_asset(db, user, asset.asset_id)
    if (authorization.applicant_org_id != user.org_id or authorization.provider_org_id != user.org_id
            or authorization.applicant_user_id != user.user_id
            or current.owner_org_id != user.org_id or authorization.asset_version_id != version.version_id
            or (authorization.terms_json or {}).get("authorization_source") != "SELF_OWNED_QUERY"):
        raise UsageRequestError(403, "OWNER_QUERY_BINDING_INVALID", "本方计算授权与当前主体或数据版本不一致")


def confirm_owned_query(db: Session, user: User, asset_id: str, energy_domain: str, resource: str, function: str,
                        start_date: date, end_date: date, region: str | None, comparison_fields: dict[str, str]):
    asset, version, org, identity = _owned_asset(db, user, asset_id)
    if org.energy_domain != energy_domain or (asset.metadata_json or {}).get("domain") != energy_domain or (asset.metadata_json or {}).get("resource_id") != resource:
        raise UsageRequestError(403, "OWNER_QUERY_RESOURCE_MISMATCH", "本方资源与确认的能源范围或指标不一致")
    starts = [start_date.isoformat(), *([comparison_fields["comparison_start_date"]] if comparison_fields else [])]
    ends = [end_date.isoformat(), *([comparison_fields["comparison_end_date"]] if comparison_fields else [])]
    confirmed_period = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), **comparison_fields}
    scope = {"start_date": min(starts), "end_date": max(ends), "region": region, "max_uses": 1, "output_mode": "AGGREGATE_ONLY", "raw_data_export": False}
    now = utc_now()
    approval = DataUsageRequest(
        request_id=new_id(), asset_id=asset.asset_id, asset_version_id=version.version_id,
        applicant_user_id=user.user_id, applicant_org_id=user.org_id, provider_org_id=user.org_id,
        applicant_did=identity.did_id, provider_did=identity.did_id, purpose="SELF_OWNED_QUERY", usage_mode="MPC_AGGREGATE",
        requested_scope_json=scope, requested_fields_json=[resource, function],
        terms_json={"authorization_source": "SELF_OWNED_QUERY", "confirmed_period": confirmed_period, "raw_data_export": False, "output_mode": "AGGREGATE_ONLY"},
        duration_days=1, expires_at=now + timedelta(minutes=15), status="APPROVED", state_version=1,
        decision_reason="有权主体确认本方数据的单次受控计算", decision_hash=sha256_json({"user_id": user.user_id, "asset_version_id": version.version_id, "scope": scope, "confirmed_period": confirmed_period}),
        decision_capability_label="LOCAL_REAL", submitted_at=now, decided_at=now, trace_id="trace-" + new_id(),
    )
    db.add(approval)
    db.flush()
    add_audit_log(db, action="SELF_OWNED_QUERY_CONFIRMED", target_type="DATA_USAGE_REQUEST", target_id=approval.request_id, result="SUCCESS", user=user,
                  details={"asset_id": asset.asset_id, "asset_version_id": version.version_id, "confirmed_period": confirmed_period, "max_uses": 1, "raw_data_accessed": False})
    return approval, asset
