from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    DataContract,
    DataSpaceAgreement,
    DataUsageRequest,
    DidIdentity,
    Organization,
    User,
    utc_now,
    new_id,
)
from ..schemas import DataUsageRequestCreate
from ..security import sha256_json
from .common import add_audit_log, trace_id
from .notifications import publish_access_request_decision, publish_access_request_submitted
from .trust_domain import TrustDomainError, verify_active_identity
from ..trust_models import DataAsset, DataAssetPassport, DataAssetVersion


class DataUsageRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class UsageRequestError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


_REVIEWABLE = {
    DataUsageRequestStatus.SUBMITTED,
    DataUsageRequestStatus.UNDER_REVIEW,
}
_REVOKABLE = {
    DataUsageRequestStatus.SUBMITTED,
    DataUsageRequestStatus.UNDER_REVIEW,
    DataUsageRequestStatus.APPROVED,
}
_BUSINESS_APPLICANTS = {
    "GENERATOR",
    "RETAILER",
    "COAL_ENTERPRISE",
    "HEAT_ENTERPRISE",
    "GAS_ENTERPRISE",
    "OIL_ENTERPRISE",
    "EXCHANGE",
    "REGULATOR",
}
_READ_ALL = {"REGULATOR"}
_PROVIDER_REVIEWERS = {
    "GENERATOR",
    "RETAILER",
    "COAL_ENTERPRISE",
    "HEAT_ENTERPRISE",
    "GAS_ENTERPRISE",
    "OIL_ENTERPRISE",
    "EXCHANGE",
}

ACCESS_DURATION_POLICY_VERSION = "TRUSTED_SPACE_USAGE_DURATION_V1"
_SERVER_DEFAULT_DURATION_POLICY = {
    "policy_version": ACCESS_DURATION_POLICY_VERSION,
    "source": "SERVER_DEFAULT_POLICY",
    "source_ref": "data_usage_policy",
    "min_days": 1,
    "max_days": 365,
    "default_days": 30,
    "is_default": True,
}

_MAX_AUTHORIZATION_USES = 1000
_REGULATORY_ACCESS_WHITELIST = {
    "REGULATORY_CROSS_ENERGY_REVIEW": {
        "legal_bases": frozenset({"ENERGY_REGULATION"}),
        "max_duration_days": 30,
    },
    "REGULATORY_EMERGENCY_RESPONSE": {
        "legal_bases": frozenset({"EMERGENCY_RESPONSE"}),
        "max_duration_days": 7,
    },
}
_REGULATORY_USAGE_MODES = frozenset({"MPC_AGGREGATE", "MASKED_QUERY"})
_REGULATORY_OUTPUT_MODES = frozenset({"AGGREGATE_ONLY", "MASKED_QUERY"})


def _raise(status_code: int, code: str, detail: str) -> None:
    raise UsageRequestError(status_code, code, detail)


def _validate_regulatory_request(
    payload: DataUsageRequestCreate,
    user: User,
    *,
    terms: dict[str, Any],
    requested_scope: dict[str, Any],
    duration_days: int,
) -> str | None:
    """Apply the narrow allowlist for regulator-initiated data-use requests."""

    if user.role_code != "REGULATOR":
        return None
    if "CREATE_CROSS_ENERGY_QUERY" not in set(user.permissions_json or []):
        _raise(403, "REGULATORY_QUERY_PERMISSION_REQUIRED", "监管账号未获得跨能源申请权限")
    policy = _REGULATORY_ACCESS_WHITELIST.get(payload.purpose)
    if policy is None:
        _raise(
            422,
            "REGULATORY_PURPOSE_NOT_WHITELISTED",
            "监管申请用途不在白名单内，只允许登记的能源监管或应急处置事项",
        )
    legal_basis = str(terms.get("regulatory_basis") or "").strip()
    authority_ref = str(terms.get("authority_ref") or "").strip()
    if legal_basis not in policy["legal_bases"] or not authority_ref:
        _raise(
            422,
            "REGULATORY_BASIS_REQUIRED",
            "监管申请必须提供白名单法律依据和可审计的事项编号",
        )
    if duration_days > int(policy["max_duration_days"]):
        _raise(
            422,
            "REGULATORY_DURATION_OUT_OF_POLICY",
            f"该监管用途最长允许 {policy['max_duration_days']} 天",
        )
    if payload.usage_mode not in _REGULATORY_USAGE_MODES:
        _raise(422, "REGULATORY_USAGE_MODE_NOT_ALLOWED", "监管申请只允许受控聚合或脱敏查询")
    output_mode = str(terms.get("output_mode") or requested_scope.get("output_mode") or "")
    if output_mode not in _REGULATORY_OUTPUT_MODES:
        _raise(422, "REGULATORY_OUTPUT_MODE_NOT_ALLOWED", "监管申请只允许汇总或脱敏结果")
    if len(payload.requested_fields) > 32:
        _raise(422, "REGULATORY_SCOPE_TOO_BROAD", "监管申请字段数量不能超过 32 个")
    return payload.purpose


def _active_identity(db: Session, org_id: str) -> DidIdentity:
    identity = db.scalar(
        select(DidIdentity)
        .where(
            DidIdentity.owner_id == org_id,
            DidIdentity.org_id == org_id,
            DidIdentity.owner_type == "ORG",
        )
        .order_by(DidIdentity.created_at.desc())
    )
    if identity is None:
        _raise(403, "ORG_DID_MISSING", "主体缺少有效 DID")
    try:
        return verify_active_identity(db, identity.did_id)
    except TrustDomainError as exc:
        _raise(403, exc.code, exc.detail)
    raise AssertionError("unreachable")


def _asset_and_version(
    db: Session,
    payload: DataUsageRequestCreate,
) -> tuple[DataAsset, DataAssetVersion]:
    asset = db.get(DataAsset, payload.asset_id)
    if asset is None:
        _raise(404, "ASSET_NOT_FOUND", "数据资产不存在")
    if asset.status != "ACTIVE":
        _raise(409, "ASSET_NOT_ACTIVE", "数据资产当前不可申请")

    version: DataAssetVersion | None = None
    if payload.asset_version_id:
        version = db.get(DataAssetVersion, payload.asset_version_id)
        if version is None or version.asset_id != asset.asset_id:
            _raise(404, "ASSET_VERSION_NOT_FOUND", "数据资产版本不存在或不属于该资产")
    elif asset.current_version_id:
        version = db.get(DataAssetVersion, asset.current_version_id)
    if version is None:
        version = db.scalar(
            select(DataAssetVersion)
            .where(DataAssetVersion.asset_id == asset.asset_id)
            .order_by(DataAssetVersion.version_no.desc())
        )
    if version is None:
        _raise(409, "ASSET_VERSION_MISSING", "数据资产没有可申请的版本")
    if version.status != "ACTIVE":
        _raise(409, "ASSET_VERSION_NOT_ACTIVE", "数据资产版本当前不可申请")
    return asset, version


def duration_policy_for_version(
    db: Session,
    version: DataAssetVersion,
) -> dict[str, Any]:
    """Return the honest duration policy for an asset version.

    Existing passports do not carry per-asset validity constraints.  In that
    case this deliberately returns a versioned server default rather than
    presenting the default as a contract or provider rule.  A future passport
    may opt in with a complete ``duration_policy`` object.
    """

    passport = db.scalar(
        select(DataAssetPassport)
        .where(DataAssetPassport.asset_version_id == version.version_id)
        .order_by(DataAssetPassport.passport_version.desc())
    )
    permitted_use = passport.permitted_use_json if passport else {}
    configured = permitted_use.get("duration_policy") if isinstance(permitted_use, dict) else None
    if not isinstance(configured, dict):
        return dict(_SERVER_DEFAULT_DURATION_POLICY)

    try:
        minimum = int(configured["min_days"])
        maximum = int(configured["max_days"])
        default = int(configured["default_days"])
    except (KeyError, TypeError, ValueError):
        return dict(_SERVER_DEFAULT_DURATION_POLICY)
    if minimum < 1 or maximum < minimum or maximum > 3650 or not minimum <= default <= maximum:
        return dict(_SERVER_DEFAULT_DURATION_POLICY)
    return {
        "policy_version": ACCESS_DURATION_POLICY_VERSION,
        "source": "ASSET_PASSPORT_PERMITTED_USE",
        "source_ref": version.version_id,
        "min_days": minimum,
        "max_days": maximum,
        "default_days": default,
        "is_default": False,
    }


def _org(db: Session, org_id: str, *, label: str) -> Organization:
    organization = db.get(Organization, org_id)
    if organization is None:
        _raise(404, f"{label.upper()}_ORG_NOT_FOUND", f"{label}组织不存在")
    if organization.status != "ACTIVE":
        _raise(403, f"{label.upper()}_ORG_INACTIVE", f"{label}组织不可用")
    return organization


def _fingerprint(
    payload: DataUsageRequestCreate,
    applicant_org_id: str,
    *,
    duration_days: int,
) -> str:
    return sha256_json(
        {
            "applicant_org_id": applicant_org_id,
            "asset_id": payload.asset_id,
            "asset_version_id": payload.asset_version_id,
            "purpose": payload.purpose,
            "usage_mode": payload.usage_mode,
            "requested_scope": payload.requested_scope,
            "requested_fields": payload.requested_fields,
            "duration_days": duration_days,
            "terms": payload.terms,
        }
    )


def _request_orgs(db: Session, request: DataUsageRequest) -> tuple[Organization, Organization]:
    applicant = _org(db, request.applicant_org_id, label="申请方")
    provider = _org(db, request.provider_org_id, label="提供方")
    return applicant, provider


def _mark_expired(db: Session, request: DataUsageRequest) -> bool:
    if request.status != DataUsageRequestStatus.APPROVED.value:
        return False
    if request.expires_at > utc_now():
        return False
    request.status = DataUsageRequestStatus.EXPIRED.value
    request.state_version += 1
    contract = db.get(DataContract, request.contract_id) if request.contract_id else None
    agreement = db.get(DataSpaceAgreement, request.agreement_id) if request.agreement_id else None
    if contract is not None:
        contract.status = "EXPIRED"
    if agreement is not None:
        agreement.state = "EXPIRED"
    add_audit_log(
        db,
        action="DATA_USAGE_REQUEST_EXPIRED",
        target_type="DATA_USAGE_REQUEST",
        target_id=request.request_id,
        result="SUCCESS",
        actor_name="SYSTEM",
        details={
            "state_version": request.state_version,
            "contract_id": request.contract_id,
            "agreement_id": request.agreement_id,
            "capability_label": "LOCAL_REAL",
            "external_anchor": "BLOCKED",
        },
    )
    return True


def can_view(request: DataUsageRequest, user: User) -> bool:
    return user.role_code in _READ_ALL or user.org_id in {
        request.applicant_org_id,
        request.provider_org_id,
    }


def can_review(request: DataUsageRequest, user: User) -> bool:
    return (
        user.role_code in _PROVIDER_REVIEWERS
        and user.org_id == request.provider_org_id
        and "APPROVE_AUTHORIZATION" in set(user.permissions_json or [])
    )


def can_revoke(request: DataUsageRequest, user: User) -> bool:
    return user.org_id in {
        request.applicant_org_id,
        request.provider_org_id,
    }


def _actions(request: DataUsageRequest, user: User) -> list[str]:
    actions: list[str] = []
    status = DataUsageRequestStatus(request.status)
    if can_review(request, user):
        if status == DataUsageRequestStatus.SUBMITTED:
            actions.extend(["review", "approve", "reject"])
        elif status == DataUsageRequestStatus.UNDER_REVIEW:
            actions.extend(["approve", "reject"])
        elif status == DataUsageRequestStatus.APPROVED:
            actions.append("revoke")
    if can_revoke(request, user) and status in _REVOKABLE and "revoke" not in actions:
        actions.append("revoke")
    return actions


def to_payload(db: Session, request: DataUsageRequest, user: User) -> dict[str, Any]:
    applicant, provider = _request_orgs(db, request)
    asset = db.get(DataAsset, request.asset_id)
    version = db.get(DataAssetVersion, request.asset_version_id)
    duration_policy = duration_policy_for_version(db, version) if version else dict(_SERVER_DEFAULT_DURATION_POLICY)
    cross_energy = applicant.energy_domain != provider.energy_domain
    return {
        "request_id": request.request_id,
        "asset": {
            "asset_id": request.asset_id,
            "asset_code": None,
            "asset_name": (asset.asset_name if asset else None) or "未命名数据资源，请由提供企业补充中文名称",
            "asset_type": asset.asset_type if asset else None,
            "classification": asset.classification if asset else None,
            "sensitivity_level": asset.sensitivity_level if asset else None,
            "version_id": request.asset_version_id,
            "version_no": version.version_no if version else None,
            "data_hash": version.data_hash if version else None,
        },
        "applicant": {
            "user_id": request.applicant_user_id,
            "org_id": request.applicant_org_id,
            "org_name": applicant.org_name,
            "did": request.applicant_did,
        },
        "provider": {
            "org_id": request.provider_org_id,
            "org_name": provider.org_name,
            "did": request.provider_did,
        },
        "cross_energy": cross_energy,
        "access_control": {
            "provider_decision_required": True,
            "raw_data_export": False,
            "default_execution": "CONTROLLED_COMPUTE_OR_AGGREGATE",
            "revocable": True,
        },
        "purpose": request.purpose,
        "usage_mode": request.usage_mode,
        "requested_scope": request.requested_scope_json,
        "requested_fields": request.requested_fields_json,
        "terms": request.terms_json,
        "duration_days": request.duration_days,
        "duration_policy": duration_policy,
        "expires_at": request.expires_at.isoformat(),
        "status": request.status,
        "decision_reason": request.decision_reason,
        "revocation_reason": request.revocation_reason,
        "reviewer_user_id": request.reviewer_user_id,
        "reviewer_did": request.reviewer_did,
        "decision_hash": request.decision_hash,
        "decision_capability_label": request.decision_capability_label,
        "decision_signature_id": request.decision_signature_id,
        "contract_id": request.contract_id,
        "agreement_id": request.agreement_id,
        "state_version": request.state_version,
        "submitted_at": request.submitted_at.isoformat(),
        "reviewed_at": request.reviewed_at.isoformat() if request.reviewed_at else None,
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
        "revoked_at": request.revoked_at.isoformat() if request.revoked_at else None,
        "capability": {
            "decision": request.decision_capability_label or "LOCAL_REAL",
            "signature": "NOT_PROVIDED",
            "external_anchor": "BLOCKED",
        },
        "actions": _actions(request, user),
    }


def _require_version(request: DataUsageRequest, if_match: str | None) -> None:
    if not if_match:
        _raise(428, "IF_MATCH_REQUIRED", "必须提供申请状态版本 If-Match")
    value = if_match.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    if value == "*" or not value.isdigit():
        _raise(400, "INVALID_IF_MATCH", "If-Match 必须是申请状态版本号")
    expected = int(value)
    if expected != request.state_version:
        _raise(
            409,
            "REQUEST_VERSION_CONFLICT",
            f"申请状态已变更，当前版本为 {request.state_version}",
        )


def _idempotent_target(target: str, status_value: str) -> bool:
    return status_value == target


def create_request(
    db: Session,
    payload: DataUsageRequestCreate,
    user: User,
    *,
    idempotency_key: str | None = None,
) -> tuple[DataUsageRequest, bool]:
    if user.role_code not in _BUSINESS_APPLICANTS:
        _raise(403, "APPLICANT_ROLE_REQUIRED", "当前角色不能发起数据使用申请")
    if idempotency_key and len(idempotency_key) > 128:
        _raise(400, "IDEMPOTENCY_KEY_TOO_LONG", "幂等键长度不能超过128")
    asset, version = _asset_and_version(db, payload)
    duration_policy = duration_policy_for_version(db, version)
    duration_days = payload.duration_days or int(duration_policy["default_days"])
    if not int(duration_policy["min_days"]) <= duration_days <= int(duration_policy["max_days"]):
        _raise(
            422,
            "DURATION_OUT_OF_POLICY",
            f"申请期限必须在 {duration_policy['min_days']} 至 {duration_policy['max_days']} 日之间，当前为 {duration_days} 日",
        )
    requested_scope = payload.requested_scope if isinstance(payload.requested_scope, dict) else {}
    terms = payload.terms if isinstance(payload.terms, dict) else {}
    if bool(requested_scope.get("raw_data_export")) or bool(terms.get("raw_data_export")):
        _raise(
            422,
            "RAW_DATA_EXPORT_NOT_AVAILABLE",
            "当前可信空间默认不转移原始数据，只允许经提供方授权的受控计算或汇总结果",
        )
    try:
        max_uses = int(requested_scope.get("max_uses", 1))
    except (TypeError, ValueError):
        _raise(422, "INVALID_MAX_USES", "使用次数必须是正整数")
    if not 1 <= max_uses <= _MAX_AUTHORIZATION_USES:
        _raise(422, "MAX_USES_OUT_OF_POLICY", f"使用次数必须在 1 至 {_MAX_AUTHORIZATION_USES} 次之间")
    regulatory_policy_code = _validate_regulatory_request(
        payload,
        user,
        terms=terms,
        requested_scope=requested_scope,
        duration_days=duration_days,
    )
    fingerprint = _fingerprint(payload, user.org_id, duration_days=duration_days)
    if idempotency_key:
        existing = db.scalar(
            select(DataUsageRequest).where(
                DataUsageRequest.applicant_org_id == user.org_id,
                DataUsageRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                _raise(409, "IDEMPOTENCY_REBINDING", "幂等键已绑定其他申请内容")
            return existing, True

    applicant = _org(db, user.org_id, label="申请方")
    provider = _org(db, asset.owner_org_id, label="提供方")
    applicant_did = _active_identity(db, applicant.org_id)
    provider_did = _active_identity(db, provider.org_id)
    request_id = new_id()
    now = utc_now()
    request = DataUsageRequest(
        request_id=request_id,
        asset_id=asset.asset_id,
        asset_version_id=version.version_id,
        applicant_user_id=user.user_id,
        applicant_org_id=applicant.org_id,
        provider_org_id=provider.org_id,
        applicant_did=applicant_did.did_id,
        provider_did=provider_did.did_id,
        purpose=payload.purpose,
        usage_mode=payload.usage_mode,
        requested_scope_json=payload.requested_scope,
        requested_fields_json=payload.requested_fields,
        terms_json={
            **terms,
            **({"regulatory_policy_code": regulatory_policy_code} if regulatory_policy_code else {}),
        },
        duration_days=duration_days,
        expires_at=now + timedelta(days=duration_days),
        status=DataUsageRequestStatus.SUBMITTED.value,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        submitted_at=now,
        trace_id=trace_id(),
    )
    db.add(request)
    add_audit_log(
        db,
        action="DATA_USAGE_REQUEST_SUBMITTED",
        target_type="DATA_USAGE_REQUEST",
        target_id=request_id,
        result="SUCCESS",
        user=user,
        details={
            "asset_id": asset.asset_id,
            "asset_version_id": version.version_id,
            "provider_org_id": provider.org_id,
            "usage_mode": payload.usage_mode,
            "cross_energy": applicant.energy_domain != provider.energy_domain,
            "provider_decision_required": True,
            "regulatory_policy_code": regulatory_policy_code,
            "capability_label": "LOCAL_REAL",
        },
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(request)
    publish_access_request_submitted(db, request)
    return request, False


def list_requests(
    db: Session,
    user: User,
    *,
    page: int,
    page_size: int,
    status_filter: str | None,
    provider_inbox: bool = False,
    applicant_outbox: bool = False,
) -> tuple[list[DataUsageRequest], int]:
    if status_filter:
        try:
            DataUsageRequestStatus(status_filter)
        except ValueError:
            _raise(400, "INVALID_REQUEST_STATUS", "申请状态无效")
    if provider_inbox and applicant_outbox:
        _raise(400, "REQUEST_SCOPE_INVALID", "不能同时查询待审申请和本人申请")
    query = select(DataUsageRequest)
    if provider_inbox:
        if (
            user.role_code not in _PROVIDER_REVIEWERS
            or "APPROVE_AUTHORIZATION" not in set(user.permissions_json or [])
        ):
            _raise(403, "PROVIDER_INBOX_DENIED", "当前角色不能访问提供方待审箱")
        query = query.where(DataUsageRequest.provider_org_id == user.org_id)
    elif applicant_outbox:
        query = query.where(DataUsageRequest.applicant_org_id == user.org_id)
    if user.role_code not in _READ_ALL:
        query = query.where(
            or_(
                DataUsageRequest.applicant_org_id == user.org_id,
                DataUsageRequest.provider_org_id == user.org_id,
            )
        )
    if status_filter:
        query = query.where(DataUsageRequest.status == status_filter)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = db.scalars(
        query.order_by(DataUsageRequest.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    expired_items: list[DataUsageRequest] = []
    for item in records:
        if _mark_expired(db, item):
            expired_items.append(item)
    if expired_items:
        db.commit()
        for item in expired_items:
            db.refresh(item)
            publish_access_request_decision(db, item, action="expire")
    return records, int(total)


def get_request(db: Session, request_id: str, user: User) -> DataUsageRequest:
    request = db.get(DataUsageRequest, request_id)
    if request is None:
        _raise(404, "REQUEST_NOT_FOUND", "数据使用申请不存在")
    if not can_view(request, user):
        _raise(403, "REQUEST_SCOPE_DENIED", "当前角色不能查看该申请")
    expired = _mark_expired(db, request)
    if expired:
        db.commit()
        db.refresh(request)
        publish_access_request_decision(db, request, action="expire")
    return request


def transition_request(
    db: Session,
    request: DataUsageRequest,
    user: User,
    *,
    action: str,
    reason: str = "",
    if_match: str | None = None,
) -> tuple[DataUsageRequest, bool]:
    current = DataUsageRequestStatus(request.status)
    target = {
        "review": DataUsageRequestStatus.UNDER_REVIEW,
        "approve": DataUsageRequestStatus.APPROVED,
        "reject": DataUsageRequestStatus.REJECTED,
        "revoke": DataUsageRequestStatus.REVOKED,
    }.get(action)
    if target is None:
        _raise(400, "UNKNOWN_REQUEST_ACTION", "不支持的申请动作")

    if action in {"review", "approve", "reject"} and not can_review(request, user):
        _raise(403, "PROVIDER_REVIEW_REQUIRED", "仅资产提供方可以审查该申请")
    if action == "revoke" and not can_revoke(request, user):
        _raise(403, "REQUEST_REVOKE_DENIED", "仅申请方或提供方可以撤回申请")

    if _idempotent_target(target.value, request.status):
        return request, True

    allowed_sources = {
        "review": {DataUsageRequestStatus.SUBMITTED},
        "approve": _REVIEWABLE,
        "reject": _REVIEWABLE,
        "revoke": _REVOKABLE,
    }[action]
    if current not in allowed_sources:
        _raise(
            409,
            "INVALID_REQUEST_TRANSITION",
            f"申请不能从 {request.status} 转换为 {target.value}",
        )
    _require_version(request, if_match)
    if action in {"approve", "reject"} and not reason.strip():
        _raise(422, "DECISION_REASON_REQUIRED", "审批或拒绝必须填写理由")

    now = utc_now()
    reviewer_did: DidIdentity | None = None
    if action in {"review", "approve", "reject"} and user.org_id == request.provider_org_id:
        reviewer_did = _active_identity(db, user.org_id)
        request.reviewer_user_id = user.user_id
        request.reviewer_did = reviewer_did.did_id
        request.reviewed_at = request.reviewed_at or now

    contract: DataContract | None = None
    agreement: DataSpaceAgreement | None = None
    if action == "approve":
        asset = db.get(DataAsset, request.asset_id)
        version = db.get(DataAssetVersion, request.asset_version_id)
        if asset is None or version is None:
            _raise(409, "REQUEST_ASSET_MISSING", "申请所引用的资产版本已不可用")
        policy = {
            "profile": "HCDS-DATA-USAGE-REQUEST-1.0",
            "source": "DATA_USAGE_REQUEST",
            "request_id": request.request_id,
            "permission": {
                "action": "use",
                "assignee": request.applicant_did,
                "purpose": request.purpose,
            },
            "constraint": {
                "asset_id": request.asset_id,
                "asset_version_id": request.asset_version_id,
                "data_scope": request.requested_scope_json,
                "requested_fields": request.requested_fields_json,
                "usage_mode": request.usage_mode,
                "output_mode": "AGGREGATE_ONLY",
                "raw_data_export": False,
                "provider_decision_required": True,
                "valid_from": now.isoformat(),
                "expires_at": request.expires_at.isoformat(),
            },
            "obligation": ["LOG_USAGE", "DELETE_ON_EXPIRY", "NO_SECONDARY_DISTRIBUTION"],
        }
        contract = DataContract(
            task_id=None,
            provider_org_id=request.provider_org_id,
            consumer_type=request.applicant_org_id,
            purpose=request.purpose,
            data_refs_json=[version.data_ref],
            policy_json=policy,
            policy_hash=sha256_json(policy),
            status="ACTIVE",
            valid_from=now,
            expires_at=request.expires_at,
        )
        db.add(contract)
        db.flush()
        agreement = DataSpaceAgreement(
            contract_id=contract.contract_id,
            task_id=None,
            provider_org_id=request.provider_org_id,
            consumer_org_id=request.applicant_org_id,
            provider_did=request.provider_did,
            consumer_did=request.applicant_did,
            protocol_version="HCDS-1.0",
            state="ACTIVE",
            requested_purpose=request.purpose,
            algorithm_code=str(request.requested_scope_json.get("algorithm_code", "CONTROLLED_DATA_USAGE_V1"))[:64],
            data_product_ids_json=[
                f"ASSET:{request.asset_id}:VERSION:{version.version_no}"
            ],
            offered_policy_hash=contract.policy_hash,
            negotiated_policy_hash=contract.policy_hash,
            valid_from=now,
            expires_at=request.expires_at,
            max_uses=int(request.requested_scope_json.get("max_uses", 1)),
            use_count=0,
            decision_json={
                "decision": "PERMIT",
                "request_id": request.request_id,
                "provider_decision_required": True,
                "capability_label": "LOCAL_REAL",
                "signature_status": "NOT_PROVIDED",
                "external_anchor": "BLOCKED",
            },
            last_receipt_json={},
            trace_id=request.trace_id,
        )
        db.add(agreement)
        db.flush()
        request.contract_id = contract.contract_id
        request.agreement_id = agreement.agreement_id

    request.status = target.value
    request.state_version += 1
    if action in {"approve", "reject"}:
        request.decision_reason = reason.strip()
        request.decided_at = now
        request.decision_capability_label = "LOCAL_REAL"
        request.decision_hash = sha256_json(
            {
                "request_id": request.request_id,
                "action": action.upper(),
                "reason": request.decision_reason,
                "state_version": request.state_version,
            }
        )
    if action == "revoke":
        request.revocation_reason = reason.strip() or None
        request.revoked_at = now
        request.revoked_by_user_id = user.user_id
        request.revoked_by_did = _active_identity(db, user.org_id).did_id
        if request.contract_id:
            contract = db.get(DataContract, request.contract_id)
            if contract is not None:
                contract.status = "REVOKED"
        if request.agreement_id:
            agreement = db.get(DataSpaceAgreement, request.agreement_id)
            if agreement is not None:
                agreement.state = "REVOKED"

    add_audit_log(
        db,
        action=f"DATA_USAGE_REQUEST_{action.upper()}",
        target_type="DATA_USAGE_REQUEST",
        target_id=request.request_id,
        result="SUCCESS",
        user=user,
        details={
            "from_status": current.value,
            "to_status": target.value,
            "state_version": request.state_version,
            "contract_id": request.contract_id,
            "agreement_id": request.agreement_id,
            "decision_capability_label": request.decision_capability_label or "LOCAL_REAL",
            "signature_status": "NOT_PROVIDED",
            "external_anchor": "BLOCKED",
        },
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(request)
    if action in {"approve", "reject", "revoke"}:
        publish_access_request_decision(
            db,
            request,
            action=action,
            actor_user_id=user.user_id,
        )
    return request, False
