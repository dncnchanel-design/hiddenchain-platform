from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AgentEvent,
    AuditReport,
    AuditLog,
    BlockchainEvidence,
    ContractNegotiationEvent,
    DataContract,
    DataSpaceAgreement,
    DataUsageRequest,
    DidIdentity,
    ExecutionReceipt,
    Organization,
    PrivacyComputeJob,
    SettlementResult,
    SettlementTask,
    Signature,
    TaskParticipant,
    User,
    utc_now,
)
from ..security import sha256_json
from ..services.adapters import DataSpaceConnectorAdapter
from ..services.credentials import JsonLdCredentialAdapter
from ..services.common import add_audit_log
from ..services.data_usage_requests import DataUsageRequestStatus, duration_policy_for_version
from ..services.local_data_boundary import can_view_subject_metadata, can_view_subject_value
from ..services.notifications import (
    publish_computation_action,
    publish_contract_event,
    publish_ttc_transition,
)
from ..services.trust_domain import (
    InvalidTtcTransition,
    TTCState,
    TtcStateMachine,
    TrustDomainError,
    verify_active_identity,
)
from ..trust_models import (
    AssetQuality,
    BlockchainAnchor,
    DataAsset,
    DataAssetPassport,
    DataAssetVersion,
    DataSource,
    EvidenceBatch,
    EvidenceBatchItem,
    EvidenceOutbox,
    ExecutionSnapshot,
    TtcAttempt,
    TtcStateTransition,
)


ENTERPRISE_ROLES = frozenset(
    {
        "GENERATOR",
        "RETAILER",
        "COAL_ENTERPRISE",
        "HEAT_ENTERPRISE",
        "GAS_ENTERPRISE",
        "OIL_ENTERPRISE",
    }
)
BUSINESS_ROLES = ENTERPRISE_ROLES | frozenset({"EXCHANGE", "REGULATOR"})
ALL_ROLES = BUSINESS_ROLES | frozenset({"ADMIN"})
PROVIDER_ROLES = ENTERPRISE_ROLES | frozenset({"EXCHANGE"})
APPLICANT_ROLES = BUSINESS_ROLES
OVERSIGHT_ROLES = frozenset({"REGULATOR"})

MANUAL_TTC_TARGETS = frozenset(
    {
        TTCState.HUMAN_REVIEW,
        TTCState.REWORK,
        TTCState.INTERRUPTED,
        TTCState.CANCELLED,
    }
)

TTC_PHASE_PROGRESS_SOURCE = "TTC_STATE_PHASE_ESTIMATE_V1"


def _ttc_phase_progress(task: SettlementTask) -> dict[str, Any]:
    """Expose a phase estimate, never pretend TTC transitions are live progress."""

    if task.ttc_state == TTCState.ARCHIVED.value or task.status in {"SUCCEEDED", "COMPLETED"}:
        value = 100
    elif task.ttc_state == TTCState.COMPUTE_EXEC.value:
        value = 65
    elif task.ttc_state not in {TTCState.INIT.value, ""}:
        value = 25
    else:
        value = 0
    return {
        "value": value,
        "source": TTC_PHASE_PROGRESS_SOURCE,
        "label": "阶段估算（非实时执行进度）",
    }

TRUST_SPACE_HELP_VERSION = "20260821.004"
TRUST_SPACE_HELP: dict[str, dict[str, Any]] = {
    "workbench": {
        "title": "工作台",
        "summary": "工作台聚合当前能源域可见资产和当前主体有权查看的申请、任务、结果与审计计数。",
        "entries": [
            {
                "id": "scope",
                "title": "数据范围",
                "body": "资产卡片只代表当前能源域的目录元数据可见，不代表原始数据可读；监管方跨能源查询也必须经过提供方授权。",
                "related_paths": ["/api/trust-space/context", "/api/trust-space/workbench"],
                "allowed_actions": ["view", "refresh"],
            },
            {
                "id": "actions",
                "title": "快捷动作",
                "body": "快捷动作由后端返回稳定 code、路径和权限；没有目标实体时会明确禁用。",
                "related_paths": ["/api/trust-space/workbench"],
                "allowed_actions": ["view", "open_quick_action"],
            },
        ],
    },
    "identity": {
        "title": "身份中心",
        "summary": "身份、组织、去中心化身份标识、证书摘要和连接器就绪状态来自后端登记。",
        "entries": [
            {
                "id": "boundary",
                "title": "能力边界",
                "body": "没有真实证书文件、连接器控制面或可信执行环境时，页面必须显示“未配置”“适配器能力”或“已阻断”。",
                "related_paths": ["/api/trust-space/identity", "/api/trust-space/context"],
                "allowed_actions": ["view", "copy_identity_reference"],
            }
        ],
    },
    "catalog": {
        "title": "数据目录",
        "summary": "搜索、筛选、分页和资产详情均以真实数据资产读模型及当前能源域范围为准。",
        "entries": [
            {
                "id": "application",
                "title": "使用申请",
                "body": "企业只能发现本能源域目录；监管方可发起跨能源查询。申请前确认资产版本、敏感级别、用途和使用方式，提交后由资产提供方审批。",
                "related_paths": ["/api/trust-space/catalog", "/api/data/access-requests"],
                "allowed_actions": ["view", "filter", "open_asset", "request_usage"],
            }
        ],
    },
    "authorizations": {
        "title": "授权记录",
        "summary": "提供方查看自己资产的入站申请，申请方查看本人发起的申请。",
        "entries": [
            {
                "id": "lifecycle",
                "title": "授权状态",
                "body": "审批、拒绝、撤回和撤销由后端状态机与 If-Match 版本共同保护。",
                "related_paths": ["/api/data/access-requests", "/api/data/access-requests/{request_id}/approve"],
                "allowed_actions": ["view", "review", "approve", "reject", "withdraw", "revoke"],
            }
        ],
    },
    "asset": {
        "title": "数据资产护照",
        "summary": "资产版本、质量、使用规则、授权记录和证据摘要来自后端资产护照。",
        "entries": [
            {
                "id": "passport",
                "title": "真实性",
                "body": "缺少链上交易哈希或区块高度时不会补造；外部存证状态按后端 capability_state 展示。",
                "related_paths": ["/api/trust-space/assets/{asset_id}"],
                "allowed_actions": ["view", "open_usage_request", "open_authorizations"],
            }
        ],
    },
    "apply": {
        "title": "使用申请",
        "summary": "四步申请只收集真实资产范围、用途、方式、期限和条款。",
        "entries": [
            {
                "id": "submit",
                "title": "提交与幂等",
                "body": "提交使用 /data/access-requests 时使用幂等键；成功后以 request_id、状态和版本为准。",
                "related_paths": ["/api/trust-space/assets/{asset_id}", "/api/data/access-requests"],
                "allowed_actions": ["view", "submit_request"],
            }
        ],
    },
    "contracts": {
        "title": "合同协商",
        "summary": "合同双方、条款、事件时间线和状态均来自数据合同与协议记录。",
        "entries": [
            {
                "id": "negotiation",
                "title": "协商动作",
                "body": "回复、反报价、接受和拒绝使用 If-Match 与幂等键；附件只允许已登记引用元数据。",
                "related_paths": ["/api/trust-space/contracts", "/api/trust-space/contracts/{contract_id}/events"],
                "allowed_actions": ["view", "comment", "counter", "accept", "reject"],
            }
        ],
    },
    "ttc": {
        "title": "TTC 任务",
        "summary": "TTC 详情、状态转换、规则冻结、尝试和日志来自真实任务状态机。",
        "entries": [
            {
                "id": "state-machine",
                "title": "状态推进",
                "body": "仅角色与当前状态允许的 transition 会返回；状态推进必须提供 If-Match 和理由。",
                "related_paths": ["/api/trust-space/ttc", "/api/trust-space/ttc/{task_id}", "/api/trust-space/ttc/{task_id}/transitions"],
                "allowed_actions": ["view", "poll_events", "transition"],
            }
        ],
    },
    "mpc": {
        "title": "多方安全计算",
        "summary": "计算任务、参与方、进度、回执和日志来自隐私计算任务记录。",
        "entries": [
            {
                "id": "external-boundary",
                "title": "外部能力边界",
                "body": "没有真实跨域参与方或可信执行环境时显示“适配器能力”或“已阻断”；不会生成静态参与方或链上回执。",
                "related_paths": ["/api/trust-space/computations", "/api/trust-space/computations/{job_id}/events"],
                "allowed_actions": ["view", "poll_logs"],
            }
        ],
    },
    "results": {
        "title": "计算结果与存证",
        "summary": "结果摘要、哈希、签名和证据状态来自结算结果与证据表。",
        "entries": [
            {
                "id": "evidence",
                "title": "结果确认",
                "body": "只有后端返回 confirm_result 时才能确认；缺少链锚定时显示待锚定，不显示伪造 TxHash。",
                "related_paths": ["/api/trust-space/results", "/api/trust-space/results/{result_id}/confirm", "/api/trust-space/evidence/{evidence_id}/verify"],
                "allowed_actions": ["view", "verify_evidence", "confirm_result"],
            }
        ],
    },
    "audit": {
        "title": "审计中心",
        "summary": "审计列表、任务链、报告、证据和 JSON/CSV 导出均按监管范围返回。",
        "entries": [
            {
                "id": "export",
                "title": "审计证据",
                "body": "完整报告和导出接口只返回当前角色可见的审计记录，并为导出动作写入审计日志。",
                "related_paths": ["/api/trust-space/audit", "/api/trust-space/audit/tasks/{task_id}", "/api/trust-space/audit/export"],
                "allowed_actions": ["view", "export_json", "export_csv"],
            }
        ],
    },
}

TRUST_SPACE_MENUS: tuple[dict[str, Any], ...] = (
    {"code": "overview", "path": "/trusted-space/workbench", "title": "运行总览", "roles": sorted(ALL_ROLES)},
    {"code": "query", "path": "/trusted-space/query", "title": "智能数据查询", "roles": sorted(BUSINESS_ROLES)},
    {"code": "catalog", "path": "/trusted-space/catalog", "title": "数据目录", "roles": sorted(BUSINESS_ROLES)},
    {"code": "connector", "path": "/trusted-space/connector", "title": "数据连接", "roles": sorted(PROVIDER_ROLES)},
    {"code": "authorization", "path": "/trusted-space/authorizations", "title": "数据授权", "roles": sorted(BUSINESS_ROLES)},
    {"code": "compute", "path": "/trusted-space/mpc", "title": "隐私计算", "roles": sorted(BUSINESS_ROLES)},
    {"code": "audit", "path": "/trusted-space/audit", "title": "审计追溯", "roles": sorted(OVERSIGHT_ROLES)},
    {"code": "participants", "path": "/trusted-space/identity", "title": "参与主体", "roles": sorted(ALL_ROLES)},
)

ROLE_CAPABILITIES: dict[str, dict[str, Any]] = {
    "GENERATOR": {
        "can_view_own_assets": True,
        "can_view_all_assets": False,
        "can_discover_cross_domain_metadata": False,
        "cross_domain_usage_requires_provider_approval": True,
        "can_request_usage": True,
        "can_review_inbound_requests": True,
        "can_revoke_own_authorizations": True,
        "can_create_settlement": False,
        "can_confirm_own_result": True,
        "can_view_audit": False,
        "can_manage_system": False,
    },
    "RETAILER": {
        "can_view_own_assets": True,
        "can_view_all_assets": False,
        "can_discover_cross_domain_metadata": False,
        "cross_domain_usage_requires_provider_approval": True,
        "can_request_usage": True,
        "can_review_inbound_requests": True,
        "can_revoke_own_authorizations": True,
        "can_create_settlement": False,
        "can_confirm_own_result": True,
        "can_view_audit": False,
        "can_manage_system": False,
    },
    "EXCHANGE": {
        "can_view_own_assets": True,
        "can_view_all_assets": False,
        "can_discover_cross_domain_metadata": False,
        "cross_domain_usage_requires_provider_approval": True,
        "can_request_usage": True,
        "can_review_inbound_requests": False,
        "can_revoke_own_authorizations": True,
        "can_create_settlement": True,
        "can_confirm_own_result": False,
        "can_view_audit": False,
        "can_manage_system": False,
    },
    "REGULATOR": {
        "can_view_own_assets": False,
        "can_view_all_assets": True,
        "can_discover_cross_domain_metadata": True,
        "cross_domain_usage_requires_provider_approval": True,
        "can_request_usage": True,
        "can_review_inbound_requests": False,
        "can_revoke_own_authorizations": False,
        "can_create_settlement": False,
        "can_confirm_own_result": False,
        "can_view_audit": True,
        "can_manage_system": False,
    },
    "ADMIN": {
        "can_view_own_assets": False,
        "can_view_all_assets": False,
        "can_discover_cross_domain_metadata": False,
        "cross_domain_usage_requires_provider_approval": False,
        "can_request_usage": False,
        "can_review_inbound_requests": False,
        "can_revoke_own_authorizations": False,
        "can_create_settlement": False,
        "can_confirm_own_result": False,
        "can_view_audit": False,
        "can_manage_system": True,
    },
}

for _enterprise_role in ("COAL_ENTERPRISE", "HEAT_ENTERPRISE", "GAS_ENTERPRISE", "OIL_ENTERPRISE"):
    ROLE_CAPABILITIES[_enterprise_role] = dict(ROLE_CAPABILITIES["GENERATOR"])

def _organization_map(db: Session) -> dict[str, Organization]:
    return {item.org_id: item for item in db.scalars(select(Organization)).all()}


def _actor_did(db: Session, user: User) -> DidIdentity | None:
    return db.scalar(
        select(DidIdentity)
        .where(
            DidIdentity.owner_type == "ORG",
            DidIdentity.owner_id == user.org_id,
            DidIdentity.org_id == user.org_id,
        )
        .order_by(DidIdentity.created_at.desc())
    )


def _source_map(db: Session) -> dict[str, DataSource]:
    return {item.source_id: item for item in db.scalars(select(DataSource)).all()}


def _visible_asset_query(user: User):
    query = select(DataAsset).where(DataAsset.status == "ACTIVE")
    if user.role_code == "ADMIN":
        query = query.where(DataAsset.asset_id == "__platform_admin_has_no_business_asset_access__")
    return query


def _asset_energy_domain(asset: DataAsset, sources: dict[str, DataSource]) -> str:
    source = sources.get(asset.source_id)
    explicit = str((asset.metadata_json or {}).get("domain") or "")
    if explicit:
        return explicit
    owner_domains = {
        "org-generator-t01": "electricity",
        "org-retailer-t01": "electricity",
        "org-exchange-t01": "electricity",
        "org-coal-t01": "coal",
        "org-heat-t01": "heat",
        "org-gas-t01": "gas",
        "org-oil-t01": "oil",
    }
    if asset.owner_org_id in owner_domains:
        return owner_domains[asset.owner_org_id]
    return str(source.security_domain if source else "")


def _asset_visible_in_energy_scope(
    asset: DataAsset,
    user: User,
    organization: Organization | None,
    sources: dict[str, DataSource],
) -> bool:
    if user.role_code == "ADMIN":
        return False
    # A domain is a classification label, not a tenancy boundary. REGULATOR
    # gets metadata for every subject; every other business user gets only its
    # own subject metadata unless a future scoped evidence grant says otherwise.
    return can_view_subject_metadata(user, asset.owner_org_id)


def _asset_visible_in_energy_aggregate(
    asset: DataAsset,
    user: User,
    organization: Organization | None,
    sources: dict[str, DataSource],
) -> bool:
    """Allow role-scoped aggregate counts without widening asset-detail access."""

    if _asset_visible_in_energy_scope(asset, user, organization, sources):
        return True
    return bool(
        user.role_code == "EXCHANGE"
        and organization
        and organization.energy_domain
        and _asset_energy_domain(asset, sources) == organization.energy_domain
    )


def _asset_access_control(
    asset: DataAsset,
    user: User,
    organization: Organization | None,
    sources: dict[str, DataSource],
) -> dict[str, Any]:
    cross_energy = bool(
        organization
        and organization.energy_domain
        and _asset_energy_domain(asset, sources) != organization.energy_domain
    )
    return {
        "cross_energy": cross_energy,
        "metadata_only": cross_energy,
        "metadata_discovery": True,
        "provider_decision_required": asset.owner_org_id != user.org_id,
        "raw_data_export": False,
        "default_execution": "CONTROLLED_COMPUTE_OR_AGGREGATE",
        "execution": "CONTROLLED_COMPUTE_OR_AGGREGATE",
    }


def _task_scope_query(db: Session, user: User):
    query = select(SettlementTask)
    if user.role_code in BUSINESS_ROLES:
        query = query.where(
            or_(
                SettlementTask.creator_org_id == user.org_id,
                SettlementTask.task_id.in_(
                    select(TaskParticipant.task_id).where(TaskParticipant.org_id == user.org_id)
                ),
            )
        )
    return query


def _request_scope_query(user: User):
    query = select(DataUsageRequest)
    query = query.where(
        or_(
            DataUsageRequest.applicant_org_id == user.org_id,
            DataUsageRequest.provider_org_id == user.org_id,
        )
    )
    return query


def _capability(state: str, source: str, **extra: Any) -> dict[str, Any]:
    return {"capability_state": state, "source_of_truth": source, **extra}


def _has_permission(user: User, permission: str) -> bool:
    return permission in set(user.permissions_json or [])


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _request_summary(request: DataUsageRequest, organizations: dict[str, Organization]) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "status": request.status,
        "purpose": request.purpose,
        "usage_mode": request.usage_mode,
        "applicant_org_id": request.applicant_org_id,
        "applicant_org_name": organizations.get(request.applicant_org_id).org_name
        if organizations.get(request.applicant_org_id)
        else None,
        "provider_org_id": request.provider_org_id,
        "provider_org_name": organizations.get(request.provider_org_id).org_name
        if organizations.get(request.provider_org_id)
        else None,
        "expires_at": _iso(request.expires_at),
        "contract_id": request.contract_id,
        "agreement_id": request.agreement_id,
        "state_version": request.state_version,
    }


def role_context(db: Session, user: User) -> dict[str, Any]:
    organization = db.get(Organization, user.org_id)
    did = _actor_did(db, user)
    role = ROLE_CAPABILITIES.get(user.role_code, {})
    visible_menus = [item for item in TRUST_SPACE_MENUS if user.role_code in item["roles"]]
    credential_status = did.credential_status if did else "NOT_CONFIGURED"
    connector_sources = db.scalars(
        select(DataSource).where(DataSource.owner_org_id == user.org_id)
    ).all()
    connector_state = (
        "LOCAL_REAL"
        if any(item.capability_label == "LOCAL_REAL" for item in connector_sources)
        else "ADAPTER"
        if connector_sources
        else "NOT_CONFIGURED"
    )
    can_discover_cross_domain = user.role_code == "REGULATOR"
    return {
        "actor": {
            "user_id": user.user_id,
            "username": user.username,
            "display_name": user.display_name,
            "role_code": user.role_code,
            "role_label": {
                "GENERATOR": "发电企业",
                "RETAILER": "售电企业",
                "COAL_ENTERPRISE": "煤炭企业",
                "HEAT_ENTERPRISE": "热能企业",
                "GAS_ENTERPRISE": "天然气企业",
                "OIL_ENTERPRISE": "石油企业",
                "EXCHANGE": "交易中心",
                "REGULATOR": "监管方",
                "ADMIN": "平台运维",
            }.get(user.role_code, user.role_code),
            "permissions": list(user.permissions_json or []),
            "is_org_owner": bool(user.is_org_owner),
        },
        "current_subject": {
            "org_id": user.org_id,
            "org_type": organization.org_type if organization else None,
            "org_name": organization.org_name if organization else None,
            "energy_domain": organization.energy_domain if organization else None,
            "status": organization.status if organization else "NOT_CONFIGURED",
        },
        "identity_ref": {
            "did": did.did_id if did else None,
            "credential_status": credential_status,
            **_capability(
                "LOCAL_REAL" if credential_status == "VALID" else "BLOCKED",
                "did_identities",
            ),
        },
        "role_capabilities": role,
        "visible_menus": visible_menus,
        "environment": {
            "name": settings.app_env.upper(),
            "fixture_seed": bool(settings.test_fixture_seed),
            **_capability("LOCAL_REAL", "runtime configuration"),
        },
        "capabilities": {
            "data_catalog": _capability("LOCAL_REAL", "data_assets/data_asset_versions"),
            "data_space_connector": _capability(
                connector_state,
                "enterprise connector registry",
                readiness="CONFIGURED" if connector_state == "LOCAL_REAL" else "NOT_CONFIGURED",
                raw_data_centrally_stored=False,
            ),
            "cross_domain_data_access": _capability(
                "LOCAL_REAL" if can_discover_cross_domain else "BLOCKED",
                "regulator-only cross-energy metadata and provider-gated requests",
                allowed_for_role=can_discover_cross_domain,
                provider_decision_required=can_discover_cross_domain,
                raw_data_export=False,
                metadata_only=True,
                reason=None
                if can_discover_cross_domain
                else "企业和交易中心只能访问本能源域目录",
            ),
            "tee": _capability("BLOCKED", "runtime configuration", readiness="NOT_CONFIGURED"),
            "audit_hash_chain": _capability("LOCAL_REAL", "append-only hash chain", append_only=True),
            "blockchain_anchor": _capability("BLOCKED", "external blockchain not configured", consensus_verified=False),
        },
    }


def contextual_help(db: Session, user: User, view: str) -> dict[str, Any]:
    item = TRUST_SPACE_HELP.get(view.strip().lower())
    if item is None:
        raise ValueError("HELP_VIEW_NOT_SUPPORTED")
    role = ROLE_CAPABILITIES.get(user.role_code, {})
    entries = [
        {
            **entry,
            "capability_state": "LOCAL_REAL",
            "source_of_truth": "versioned_trusted_space_help",
        }
        for entry in item["entries"]
    ]
    allowed_actions = sorted(
        {
            action
            for entry in entries
            for action in entry.get("allowed_actions", [])
        }
    )
    return {
        "view": view.strip().lower(),
        "version": TRUST_SPACE_HELP_VERSION,
        "title": item["title"],
        "summary": item["summary"],
        "entries": entries,
        "role_code": user.role_code,
        "role_capabilities": role,
        "allowed_actions": allowed_actions,
        **_capability("LOCAL_REAL", "versioned_trusted_space_help"),
    }


def _ttc_allowed_actions(user: User, task: SettlementTask) -> list[str]:
    actions = ["view"]
    if user.role_code not in {"EXCHANGE", "REGULATOR"}:
        return actions
    try:
        source = TTCState(task.ttc_state)
    except ValueError:
        return actions
    targets = sorted(
        (
            target
            for target in TtcStateMachine.allowed_transitions.get(source, frozenset())
            if target in MANUAL_TTC_TARGETS
            and TtcStateMachine.can_transition(source, target)
        ),
        key=lambda item: item.value,
    )
    actions.extend(f"transition:{target.value}" for target in targets)
    return actions


def _quick_action(
    *,
    code: str,
    label: str,
    path: str,
    allowed: bool,
    disabled_reason: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "path": path,
        "allowed": allowed,
        "disabled_reason": disabled_reason if not allowed else None,
        "entity_id": entity_id,
        "capability_state": "LOCAL_REAL",
        "source_of_truth": "trusted_space_workbench",
    }


def _quick_action_items(
    user: User,
    *,
    asset_count: int,
    inbound_count: int,
    audit_count: int,
    result_ids: list[str],
    audit_task_ids: list[str],
) -> list[dict[str, Any]]:
    has_assets = asset_count > 0
    if user.role_code in ENTERPRISE_ROLES:
        return [
            _quick_action(
                code="VIEW_OWN_ASSETS",
                label="查看本方资产",
                path="/trusted-space/catalog",
                allowed=has_assets,
                disabled_reason="当前主体暂无可见资产" if not has_assets else None,
            ),
            _quick_action(
                code="REVIEW_INBOUND_AUTHORIZATIONS",
                label="处理入站授权",
                path="/trusted-space/authorizations?view=inbox",
                allowed=inbound_count > 0,
                disabled_reason="当前没有入站授权申请" if inbound_count == 0 else None,
            ),
            _quick_action(
                code="CONFIRM_OWN_RESULT",
                label="确认本方结果",
                path=(f"/trusted-space/results/{result_ids[0]}" if result_ids else "/trusted-space/results"),
                allowed=bool(result_ids),
                disabled_reason="当前没有待确认的本方结果" if not result_ids else None,
                entity_id=result_ids[0] if result_ids else None,
            ),
        ]
    if user.role_code == "EXCHANGE":
        return [
            _quick_action(
                code="REQUEST_USAGE",
                label="发起使用申请",
                path="/trusted-space/catalog",
                allowed=has_assets,
                disabled_reason="当前没有可申请的数据资产" if not has_assets else None,
            ),
            _quick_action(
                code="CREATE_SETTLEMENT",
                label="发起结算任务",
                path="/settlements/new",
                allowed=True,
            ),
            _quick_action(
                code="VIEW_PENDING_AUDIT",
                label="查看待审计任务",
                path=(
                    f"/trusted-space/audit/tasks/{audit_task_ids[0]}"
                    if audit_task_ids
                    else "/trusted-space/audit"
                ),
                allowed=audit_count > 0,
                disabled_reason="当前没有可见审计报告" if audit_count == 0 else None,
                entity_id=audit_task_ids[0] if audit_task_ids else None,
            ),
        ]
    if user.role_code == "REGULATOR":
        return [
            _quick_action(
                code="VIEW_ALL_ASSETS",
                label="查看全域资产",
                path="/trusted-space/catalog",
                allowed=has_assets,
                disabled_reason="当前没有可见数据资产" if not has_assets else None,
            ),
            _quick_action(
                code="VIEW_AUTHORIZATIONS",
                label="查看授权记录",
                path="/trusted-space/authorizations?view=outbound",
                allowed=True,
            ),
            _quick_action(
                code="REVIEW_AUDIT_EVIDENCE",
                label="复核审计证据",
                path="/trusted-space/audit",
                allowed=audit_count > 0,
                disabled_reason="当前没有可见审计报告" if audit_count == 0 else None,
            ),
        ]
    if user.role_code == "ADMIN":
        return [
            _quick_action(
                code="VIEW_SYSTEM_CAPABILITIES",
                label="查看系统能力",
                path="/agents",
                allowed=True,
            ),
            _quick_action(
                code="VIEW_ALL_ASSETS",
                label="查看全域资产",
                path="/trusted-space/catalog",
                allowed=has_assets,
                disabled_reason="当前没有可见数据资产" if not has_assets else None,
            ),
            _quick_action(
                code="VIEW_RUNTIME_STATUS",
                label="查看运行状态",
                path="/metrics",
                allowed=True,
            ),
        ]
    return []


def workbench(db: Session, user: User) -> dict[str, Any]:
    if user.role_code == "ADMIN":
        return {
            "kpis": {
                "visible_assets": 0,
                "visible_tasks": 0,
                "usage_requests": 0,
                "active_usage_requests": 0,
                "inbound_usage_requests": 0,
                "outbound_usage_requests": 0,
                "compute_jobs": 0,
                "audit_reports": 0,
            },
            "recent_assets": [],
            "recent_tasks": [],
            "recent_usage_requests": [],
            "recent_compute_jobs": [],
            "recent_audit_reports": [],
            "quick_actions": ["VIEW_RUNTIME_STATUS"],
            "quick_action_items": [
                _quick_action(
                    code="VIEW_RUNTIME_STATUS",
                    label="查看平台运行状态",
                    path="/metrics",
                    allowed=True,
                )
            ],
            "empty_state": False,
            **_capability("LOCAL_REAL", "sanitized platform operations status"),
        }
    organizations = _organization_map(db)
    source_map = _source_map(db)
    current_organization = organizations.get(user.org_id)
    all_asset_rows = db.scalars(
        _visible_asset_query(user).order_by(DataAsset.created_at.desc())
    ).all()
    visible_asset_rows = [
        item
        for item in all_asset_rows
        if _asset_visible_in_energy_scope(item, user, current_organization, source_map)
        and (user.role_code not in ENTERPRISE_ROLES or item.owner_org_id == user.org_id)
    ]
    aggregate_asset_rows = [
        item
        for item in all_asset_rows
        if _asset_visible_in_energy_aggregate(item, user, current_organization, source_map)
        and (user.role_code not in ENTERPRISE_ROLES or item.owner_org_id == user.org_id)
    ]
    assets = visible_asset_rows[:8]
    tasks = db.scalars(_task_scope_query(db, user).order_by(SettlementTask.updated_at.desc()).limit(8)).all()
    task_ids = [item.task_id for item in tasks]
    asset_count = len(aggregate_asset_rows)
    task_count = int(
        db.scalar(select(func.count()).select_from(_task_scope_query(db, user).subquery())) or 0
    )
    request_scope = _request_scope_query(user)
    request_count = int(db.scalar(select(func.count()).select_from(request_scope.subquery())) or 0)
    active_request_count = int(
        db.scalar(
            select(func.count())
            .select_from(
                request_scope.where(
                    DataUsageRequest.status.in_(
                        [
                            DataUsageRequestStatus.SUBMITTED.value,
                            DataUsageRequestStatus.UNDER_REVIEW.value,
                            DataUsageRequestStatus.APPROVED.value,
                        ]
                    )
                ).subquery()
            )
        )
        or 0
    )
    inbound_count = int(
        db.scalar(
            select(func.count())
            .select_from(
                request_scope.where(DataUsageRequest.provider_org_id == user.org_id).subquery()
            )
        )
        or 0
    )
    outbound_count = int(
        db.scalar(
            select(func.count())
            .select_from(
                request_scope.where(DataUsageRequest.applicant_org_id == user.org_id).subquery()
            )
        )
        or 0
    )
    request_query = request_scope.order_by(DataUsageRequest.created_at.desc()).limit(8)
    requests = db.scalars(request_query).all()
    task_scope = _task_scope_query(db, user)
    all_task_ids = list(
        db.scalars(task_scope.with_only_columns(SettlementTask.task_id)).all()
    )
    compute_query = select(PrivacyComputeJob)
    if user.role_code in ENTERPRISE_ROLES:
        compute_query = compute_query.where(PrivacyComputeJob.task_id.in_(all_task_ids or ["__none__"]))
    compute_jobs = db.scalars(compute_query.order_by(PrivacyComputeJob.created_at.desc()).limit(8)).all()
    compute_count_query = select(func.count(PrivacyComputeJob.job_id))
    if user.role_code in ENTERPRISE_ROLES:
        compute_count_query = compute_count_query.where(
            PrivacyComputeJob.task_id.in_(all_task_ids or ["__none__"])
        )
    compute_count = int(db.scalar(compute_count_query) or 0)
    audit_query = select(AuditReport)
    if user.role_code in ENTERPRISE_ROLES:
        audit_query = audit_query.where(AuditReport.task_id.in_(all_task_ids or ["__none__"]))
    audit_reports = db.scalars(audit_query.order_by(AuditReport.created_at.desc()).limit(8)).all()
    audit_count_query = select(func.count(AuditReport.report_id))
    if user.role_code in ENTERPRISE_ROLES:
        audit_count_query = audit_count_query.where(AuditReport.task_id.in_(all_task_ids or ["__none__"]))
    audit_count = int(db.scalar(audit_count_query) or 0)
    result_rows = db.scalars(
        select(SettlementResult).order_by(SettlementResult.created_at.desc()).limit(32)
    ).all()
    result_ids = [
        item.result_id
        for item in result_rows
        if item.confirm_status == "UNCONFIRMED"
        and result_visible(db, item, user)
        and item.org_id == user.org_id
    ]
    audit_task_ids = [item.task_id for item in audit_reports if item.task_id]
    recent_assets = [
        {
            "asset_id": item.asset_id,
            "asset_code": item.asset_code,
            "asset_name": item.asset_name,
            "asset_type": item.asset_type,
            "owner_org_id": item.owner_org_id,
            "owner_org_name": organizations.get(item.owner_org_id).org_name
            if organizations.get(item.owner_org_id)
            else None,
            "source_capability": source_map.get(item.source_id).capability_label
            if source_map.get(item.source_id)
            else "NOT_CONFIGURED",
            "access_control": _asset_access_control(item, user, current_organization, source_map),
            **_capability("LOCAL_REAL", "data_assets"),
        }
        for item in assets
    ]
    recent_tasks = [
        {
            "task_id": item.task_id,
            "task_name": item.task_name,
            "status": item.status,
            "ttc_state": item.ttc_state,
            "current_attempt": item.current_attempt,
            "updated_at": _iso(item.updated_at),
            "phase_progress_estimate": _ttc_phase_progress(item),
            **_capability("LOCAL_REAL", "settlement_tasks/ttc_attempts"),
        }
        for item in tasks
    ]
    quick_action_items = _quick_action_items(
        user,
        asset_count=asset_count,
        inbound_count=inbound_count,
        audit_count=audit_count,
        result_ids=result_ids,
        audit_task_ids=audit_task_ids,
    )
    return {
        "kpis": {
            "visible_assets": asset_count,
            "visible_tasks": task_count,
            "usage_requests": request_count,
            "active_usage_requests": active_request_count,
            "inbound_usage_requests": inbound_count,
            "outbound_usage_requests": outbound_count,
            "compute_jobs": compute_count,
            "audit_reports": audit_count,
        },
        "recent_assets": recent_assets,
        "recent_tasks": recent_tasks,
        "recent_usage_requests": [
            {
                **_request_summary(item, organizations),
                **_capability("LOCAL_REAL", "data_usage_requests"),
            }
            for item in requests
        ],
        "recent_compute_jobs": [
            {
                "job_id": item.job_id,
                "task_id": item.task_id,
                "algorithm_code": item.algorithm_code,
                "status": item.status,
                "progress": item.progress,
                "output_hash": item.output_hash,
                **_capability("LOCAL_REAL", "privacy_compute_jobs"),
            }
            for item in compute_jobs
        ],
        "recent_audit_reports": [
            {
                "report_id": item.report_id,
                "task_id": item.task_id,
                "title": item.report_title,
                "status": item.status,
                "risk_level": item.risk_level,
                "report_hash": item.report_hash,
                **_capability("LOCAL_REAL", "audit_reports"),
            }
            for item in audit_reports
        ],
        # Keep the string list for the current client contract. New clients
        # should consume the structured items below and never infer a route
        # from localized labels.
        "quick_actions": [item["label"] for item in quick_action_items],
        "quick_action_items": quick_action_items,
        "empty_state": not any(
            [asset_count, task_count, request_count, compute_count, audit_count]
        ),
        **_capability("LOCAL_REAL", "authoritative database read model"),
    }


def identity(db: Session, user: User) -> dict[str, Any]:
    organization = db.get(Organization, user.org_id)
    did = _actor_did(db, user)
    sources = db.scalars(
        select(DataSource).where(DataSource.owner_org_id == user.org_id).order_by(DataSource.created_at)
    ).all()
    credential = JsonLdCredentialAdapter.fingerprint(did.credential_json if did else None)
    connector_state = "ADAPTER" if sources else "NOT_CONFIGURED"
    return {
        "subject": {
            "org_id": user.org_id,
            "org_type": organization.org_type if organization else None,
            "org_name": organization.org_name if organization else None,
            "credit_code": organization.credit_code if organization else None,
            "status": organization.status if organization else "NOT_CONFIGURED",
        },
        "actor": {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "role_code": user.role_code,
        },
        "did": {
            "did_id": did.did_id if did else None,
            "credential_status": did.credential_status if did else "NOT_CONFIGURED",
            "public_key_fingerprint": did.public_key_fingerprint if did else None,
            "chain_address": did.chain_address if did else None,
            "credential_type": (did.credential_json or {}).get("type") if did else None,
            "issuer": (did.credential_json or {}).get("issuer") if did else None,
            "issued_at": _iso(did.created_at) if did else None,
            "expires_at": (did.credential_json or {}).get("expirationDate") if did else None,
            "verification": credential,
            **_capability(
                "LOCAL_REAL" if did and did.credential_status == "VALID" else "BLOCKED",
                "did_identities",
            ),
        },
        "connector": {
            "code": DataSpaceConnectorAdapter.code,
            "protocol_version": DataSpaceConnectorAdapter.protocol_version,
            "source_count": len(sources),
            "source_capabilities": sorted({item.capability_label for item in sources}),
            "readiness": "NOT_CONFIGURED",
            "external_edc_runtime": "NOT_CONFIGURED",
            **_capability(connector_state, "data_sources"),
        },
        "capability_matrix": {
            "identity": _capability("LOCAL_REAL", "did_identities"),
            "asset_registry": _capability("LOCAL_REAL", "data_assets/data_asset_versions"),
            "connector_control_plane": _capability("ADAPTER", "DataSpaceConnectorAdapter", readiness="NOT_CONFIGURED"),
            "tee": _capability("BLOCKED", "runtime configuration", readiness="NOT_CONFIGURED"),
            "hash_chain": _capability("LOCAL_REAL", "append-only audit hash chain", append_only=True),
            "blockchain": _capability("BLOCKED", "external blockchain not configured", consensus_verified=False),
        },
        **_capability("LOCAL_REAL", "organizations/users/did_identities/data_sources"),
    }


_SENSITIVE_DID_DOCUMENT_FIELDS = {
    "access_token",
    "password",
    "private_key",
    "privatekey",
    "secret",
    "secret_key",
    "secretkey",
    "token",
}


def _public_did_document(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded public DID document without credential secrets.

    Credentials are stored by the enterprise-owned identity record. The
    directory may expose its public JSON-LD statements, but private material
    must never cross the API boundary even if a connector accidentally writes
    it into the JSON column.
    """

    if depth > 8:
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in _SENSITIVE_DID_DOCUMENT_FIELDS or any(
                marker in normalized for marker in ("private", "secret", "password")
            ):
                continue
            result[str(key)] = _public_did_document(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_public_did_document(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _identity_summary(
    item: DidIdentity,
    organization: Organization | None,
    *,
    member_count: int,
) -> dict[str, Any]:
    credential = item.credential_json or {}
    credential_type = credential.get("type")
    if isinstance(credential_type, str):
        credential_type = [credential_type]
    if not isinstance(credential_type, list):
        credential_type = []
    return {
        "org_id": item.org_id or item.owner_id,
        "org_type": organization.org_type if organization else None,
        "org_name": organization.org_name if organization else None,
        "energy_domain": organization.energy_domain if organization else None,
        "status": organization.status if organization else "NOT_CONFIGURED",
        "did_id": item.did_id,
        "credential_status": item.credential_status,
        "public_key_fingerprint": item.public_key_fingerprint,
        "chain_address": item.chain_address,
        "credential_type": [str(value) for value in credential_type],
        "issuer": credential.get("issuer"),
        "issued_at": _iso(item.created_at),
        "expires_at": credential.get("expirationDate") or credential.get("expiration_date"),
        "member_count": member_count,
        **_capability("LOCAL_REAL", "organizations/did_identities"),
    }


def identity_directory(db: Session, user: User) -> dict[str, Any]:
    """Read the public organization DID directory from the authoritative DB."""

    organizations = _organization_map(db)
    member_counts = {
        org_id: count
        for org_id, count in db.execute(
            select(User.org_id, func.count(User.user_id)).group_by(User.org_id)
        ).all()
    }
    identities = db.scalars(
        select(DidIdentity)
        .where(DidIdentity.owner_type == "ORG", DidIdentity.org_id.is_not(None))
        .order_by(DidIdentity.created_at, DidIdentity.did_id)
    ).all()
    items = []
    for item in identities:
        organization = organizations.get(item.org_id or item.owner_id)
        # Platform operations is intentionally not a business participant. It
        # maintains the host only and must not appear in the enterprise DID
        # directory or topology.
        if organization is None or organization.org_type == "ADMIN":
            continue
        items.append(
            _identity_summary(
                item,
                organization,
                member_count=member_counts.get(item.org_id or item.owner_id, 0),
            )
        )
    return {
        "items": items,
        "total": len(items),
        "verified_count": sum(item["credential_status"] == "VALID" for item in items),
        "energy_domains": sorted({item["energy_domain"] for item in items if item["energy_domain"]}),
        "empty_state": not items,
        **_capability("LOCAL_REAL", "organizations/did_identities"),
    }


def did_document(db: Session, did_id: str, user: User) -> dict[str, Any] | None:
    """Return one public DID document, never its private credential material."""

    item = db.scalar(
        select(DidIdentity).where(
            DidIdentity.did_id == did_id,
            DidIdentity.owner_type == "ORG",
        )
    )
    if item is None:
        return None
    organization = db.get(Organization, item.org_id or item.owner_id)
    if organization is None or organization.org_type == "ADMIN":
        return None
    document = _public_did_document(item.credential_json or {})
    if not isinstance(document, dict):
        document = {}
    return {
        "did_id": item.did_id,
        "subject": {
            "org_id": item.org_id or item.owner_id,
            "org_name": organization.org_name if organization else None,
            "org_type": organization.org_type if organization else None,
            "energy_domain": organization.energy_domain if organization else None,
        },
        "credential_status": item.credential_status,
        "public_key_fingerprint": item.public_key_fingerprint,
        "document": document,
        "verification": JsonLdCredentialAdapter.fingerprint(document),
        **_capability("LOCAL_REAL", "did_identities"),
    }


def _asset_item(
    db: Session,
    asset: DataAsset,
    organizations: dict[str, Organization],
    sources: dict[str, DataSource],
    user: User,
) -> dict[str, Any]:
    version = db.scalar(
        select(DataAssetVersion)
        .where(DataAssetVersion.asset_id == asset.asset_id)
        .order_by(DataAssetVersion.version_no.desc())
    )
    source = sources.get(asset.source_id)
    can_request = user.role_code in APPLICANT_ROLES and asset.owner_org_id != user.org_id
    can_review = (
        user.role_code in PROVIDER_ROLES
        and asset.owner_org_id == user.org_id
        and _has_permission(user, "APPROVE_AUTHORIZATION")
    )
    return {
        "asset_id": asset.asset_id,
        "asset_code": "",
        "asset_name": asset.asset_name or "未命名数据资源，请由提供企业补充中文名称",
        "asset_type": asset.asset_type,
        "classification": asset.classification,
        "sensitivity_level": asset.sensitivity_level,
        "status": asset.status,
        "domain": (asset.metadata_json or {}).get("domain") or (source.security_domain if source else None),
        "metadata": asset.metadata_json,
        "provider": {
            "org_id": asset.owner_org_id,
            "org_name": organizations.get(asset.owner_org_id).org_name
            if organizations.get(asset.owner_org_id)
            else None,
        },
        "latest_version": {
            "version_id": version.version_id,
            "version_no": version.version_no,
            "schema_version": version.schema_version,
            "data_hash": version.data_hash,
            "record_count": version.record_count,
            "status": version.status,
        }
        if version
        else None,
        "actions": {
            "can_request_usage": can_request,
            "can_review_inbound": can_review,
            "can_view_passport": True,
        },
        "access_control": _asset_access_control(
            asset,
            user,
            organizations.get(user.org_id),
            sources,
        ),
        "source": {
            "source_id": source.source_id if source else None,
            "connector_type": source.connector_type if source else None,
            "capability_label": source.capability_label if source else "NOT_CONFIGURED",
            "status": source.status if source else "NOT_CONFIGURED",
        },
        **_capability("LOCAL_REAL", "data_assets/data_asset_versions"),
    }


def catalog(
    db: Session,
    user: User,
    *,
    query_text: str | None,
    asset_type: str | None,
    domain: str | None,
    sensitivity_level: str | None,
    provider_org_id: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    organizations = _organization_map(db)
    sources = _source_map(db)
    assets = db.scalars(_visible_asset_query(user).order_by(DataAsset.created_at.desc())).all()
    current_organization = organizations.get(user.org_id)
    normalized_query = query_text.strip().lower() if query_text else None
    filtered: list[DataAsset] = []
    for asset in assets:
        if not _asset_visible_in_energy_scope(asset, user, current_organization, sources):
            continue
        source = sources.get(asset.source_id)
        metadata = asset.metadata_json or {}
        asset_domain = str(metadata.get("domain") or (source.security_domain if source else ""))
        provider_name = organizations.get(asset.owner_org_id).org_name if organizations.get(asset.owner_org_id) else ""
        haystack = " ".join(
            [asset.asset_id, asset.asset_code, asset.asset_name, asset.asset_type, provider_name]
        ).lower()
        if normalized_query and normalized_query not in haystack:
            continue
        if asset_type and asset.asset_type != asset_type:
            continue
        if domain and domain.lower() not in asset_domain.lower():
            continue
        if sensitivity_level and asset.sensitivity_level != sensitivity_level:
            continue
        if provider_org_id and asset.owner_org_id != provider_org_id:
            continue
        filtered.append(asset)
    total = len(filtered)
    start = (page - 1) * page_size
    items = [_asset_item(db, asset, organizations, sources, user) for asset in filtered[start : start + page_size]]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "filters": {
            "query": query_text,
            "asset_type": asset_type,
            "domain": domain,
            "sensitivity_level": sensitivity_level,
            "provider_org_id": provider_org_id,
        },
        "empty_state": total == 0,
        **_capability("LOCAL_REAL", "data_assets/data_asset_versions"),
    }


def asset_detail(db: Session, asset_id: str, user: User) -> dict[str, Any] | None:
    asset = db.get(DataAsset, asset_id)
    if asset is None:
        return None
    organizations = _organization_map(db)
    sources = _source_map(db)
    if not _asset_visible_in_energy_scope(asset, user, organizations.get(user.org_id), sources):
        return None
    source = sources.get(asset.source_id)
    versions = db.scalars(
        select(DataAssetVersion)
        .where(DataAssetVersion.asset_id == asset.asset_id)
        .order_by(DataAssetVersion.version_no.desc())
    ).all()
    version_items: list[dict[str, Any]] = []
    for version in versions:
        passport = db.scalar(
            select(DataAssetPassport)
            .where(DataAssetPassport.asset_version_id == version.version_id)
            .order_by(DataAssetPassport.passport_version.desc())
        )
        quality = db.scalar(
            select(AssetQuality)
            .where(AssetQuality.asset_version_id == version.version_id)
            .order_by(AssetQuality.evaluated_at.desc())
        )
        version_items.append(
            {
                "version_id": version.version_id,
                "version_no": version.version_no,
                "schema_version": version.schema_version,
                "data_hash": version.data_hash,
                "commitment": version.commitment,
                "record_count": version.record_count,
                "immutable_hash": version.immutable_hash,
                "status": version.status,
                "passport": {
                    "passport_id": passport.passport_id,
                    "passport_version": passport.passport_version,
                    "owner_did": passport.owner_did,
                    "provenance": passport.provenance_json,
                    "classification": passport.classification_json,
                    "permitted_use": passport.permitted_use_json,
                    "policy_refs": passport.policy_refs_json,
                    "evidence_refs": passport.evidence_refs_json,
                    "passport_hash": passport.passport_hash,
                    "status": passport.status,
                }
                if passport
                else None,
                "quality": {
                    "quality_id": quality.quality_id,
                    "profile_version": quality.profile_version,
                    "metrics": quality.metrics_json,
                    "decision": quality.decision,
                    "quality_hash": quality.quality_hash,
                    "evidence_refs": quality.evidence_refs_json,
                    "evaluated_at": _iso(quality.evaluated_at),
                }
                if quality
                else None,
            }
        )
    request_records = db.scalars(
        _request_scope_query(user)
        .where(DataUsageRequest.asset_id == asset.asset_id)
        .order_by(DataUsageRequest.created_at.desc())
    ).all()
    contract_ids = [item.contract_id for item in request_records if item.contract_id]
    agreement_count = (
        db.scalar(
            select(func.count(DataSpaceAgreement.agreement_id)).where(
                DataSpaceAgreement.contract_id.in_(contract_ids or ["__none__"]),
                DataSpaceAgreement.state.in_(["ACTIVE", "NEGOTIATED", "CONSUMED"]),
            )
        )
        or 0
    )
    latest = version_items[0] if version_items else None
    passport = latest.get("passport") if latest else None
    duration_policy = duration_policy_for_version(db, versions[0]) if versions else None
    can_request = user.role_code in APPLICANT_ROLES and asset.owner_org_id != user.org_id
    can_review = (
        user.role_code in PROVIDER_ROLES
        and asset.owner_org_id == user.org_id
        and _has_permission(user, "APPROVE_AUTHORIZATION")
    )
    return {
        "asset": {
            "asset_id": asset.asset_id,
            "asset_code": asset.asset_code,
            "asset_name": asset.asset_name,
            "asset_type": asset.asset_type,
            "classification": asset.classification,
            "sensitivity_level": asset.sensitivity_level,
            "status": asset.status,
            "domain": (asset.metadata_json or {}).get("domain") or (source.security_domain if source else None),
            "metadata": asset.metadata_json,
            "provider": {
                "org_id": asset.owner_org_id,
                "org_name": organizations.get(asset.owner_org_id).org_name
                if organizations.get(asset.owner_org_id)
                else None,
            },
        },
        "versions": version_items,
        "current_version_id": asset.current_version_id,
        "usage_rules": passport.get("permitted_use") if passport else None,
        "duration_policy": duration_policy,
        "policy_refs": passport.get("policy_refs", []) if passport else [],
        "evidence_summary": {
            "passport_evidence_refs": passport.get("evidence_refs", []) if passport else [],
            "active_agreement_count": int(agreement_count),
            "contract_count": len(contract_ids),
            **_capability("LOCAL_REAL", "data_asset_passports/data_contracts/data_space_agreements"),
        },
        "usage_requests": [
            {
                **_request_summary(item, organizations),
                **_capability("LOCAL_REAL", "data_usage_requests"),
            }
            for item in request_records
        ],
        "actions": {
            "can_request_usage": can_request,
            "can_review_inbound": can_review,
            "can_revoke_provider_authorization": can_review,
            "can_view_audit": user.role_code == "REGULATOR" and _has_permission(user, "VIEW_AUDIT"),
        },
        "access_control": _asset_access_control(
            asset,
            user,
            organizations.get(user.org_id),
            sources,
        ),
        "source": {
            "source_id": source.source_id if source else None,
            "source_code": source.source_code if source else None,
            "security_domain": source.security_domain if source else None,
            "connector_type": source.connector_type if source else None,
            "capability_label": source.capability_label if source else "NOT_CONFIGURED",
            "status": source.status if source else "NOT_CONFIGURED",
        },
        **_capability("LOCAL_REAL", "data_assets/data_asset_versions/data_asset_passports"),
    }


# ---------------------------------------------------------------------------
# Contract / TTC / computation / evidence / audit read models
# ---------------------------------------------------------------------------


def _allowed_actions(
    user: User,
    *,
    actions: Iterable[str] = (),
    source: str,
    state: str | None = None,
) -> dict[str, Any]:
    """Return a capability envelope for every new Trusted Space DTO."""

    return {
        "allowed_actions": sorted(set(actions)),
        **_capability("LOCAL_REAL", source, lifecycle_state=state),
    }


def _organization_payload(db: Session, org_id: str | None) -> dict[str, Any] | None:
    if not org_id:
        return None
    organization = db.get(Organization, org_id)
    if organization is None:
        return {"org_id": org_id, "org_name": None}
    return {
        "org_id": organization.org_id,
        "org_name": organization.org_name,
        "org_type": organization.org_type,
        "status": organization.status,
    }


def _contract_visible(contract: DataContract, user: User) -> bool:
    return contract.provider_org_id == user.org_id or contract.consumer_type == user.org_id


def _contract_agreement(db: Session, contract_id: str) -> DataSpaceAgreement | None:
    return db.scalar(
        select(DataSpaceAgreement)
        .where(DataSpaceAgreement.contract_id == contract_id)
        .order_by(DataSpaceAgreement.created_at.desc())
    )


def _event_version(db: Session, contract_id: str) -> int:
    return int(
        db.scalar(
            select(func.max(ContractNegotiationEvent.state_version)).where(
                ContractNegotiationEvent.contract_id == contract_id
            )
        )
        or 0
    )


def _event_payload(db: Session, event: ContractNegotiationEvent) -> dict[str, Any]:
    actor = _organization_payload(db, event.actor_org_id)
    return {
        "event_id": event.event_id,
        "contract_id": event.contract_id,
        "agreement_id": event.agreement_id,
        "actor": actor,
        "actor_user_id": event.actor_user_id,
        "actor_did": event.actor_did,
        "event_type": event.event_type,
        "message": event.message,
        "terms": event.terms_json,
        "attachment_metadata": event.attachment_metadata_json,
        "from_state": event.from_state,
        "to_state": event.to_state,
        "state_version": event.state_version,
        "event_hash": event.event_hash,
        "created_at": _iso(event.created_at),
        **_allowed_actions(
            User(
                user_id="",
                org_id=event.actor_org_id,
                username="",
                password_hash="",
                display_name="",
                role_code="ADMIN",
            ),
            source="contract_negotiation_events",
            state=event.to_state,
        ),
    }


def _contract_actions(user: User, contract: DataContract, agreement: DataSpaceAgreement | None) -> list[str]:
    if agreement is None or not _contract_visible(contract, user):
        return []
    if user.role_code in OVERSIGHT_ROLES:
        return []
    if user.role_code == "EXCHANGE" or user.org_id in {
        contract.provider_org_id,
        contract.consumer_type,
    }:
        if agreement.state in {"REJECTED", "REVOKED", "EXPIRED"}:
            return []
        if agreement.state == "ACTIVE":
            return ["comment"]
        return ["comment", "counter", "accept", "reject"]
    return []


def _asset_refs_for_contract(db: Session, contract: DataContract) -> list[dict[str, Any]]:
    request = db.scalar(
        select(DataUsageRequest)
        .where(DataUsageRequest.contract_id == contract.contract_id)
        .order_by(DataUsageRequest.created_at.desc())
    )
    refs = list(contract.data_refs_json or [])
    if request is not None:
        refs = [
            {
                "asset_id": request.asset_id,
                "asset_version_id": request.asset_version_id,
                "source": "data_usage_requests",
            }
        ]
    assets: list[dict[str, Any]] = []
    for ref in refs:
        if isinstance(ref, str):
            asset_id, version_id = ref, None
        elif isinstance(ref, dict):
            asset_id = str(ref.get("asset_id") or ref.get("id") or "")
            version_id = ref.get("asset_version_id") or ref.get("version_id")
        else:
            continue
        if not asset_id:
            continue
        asset = db.get(DataAsset, asset_id)
        if asset is None:
            assets.append({"asset_id": asset_id, "asset_version_id": version_id})
            continue
        assets.append(
            {
                "asset_id": asset.asset_id,
                "asset_code": asset.asset_code,
                "asset_name": asset.asset_name,
                "asset_version_id": version_id or asset.current_version_id,
                "provider_org_id": asset.owner_org_id,
            }
        )
    return assets


def contract_list(
    db: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    state: str | None = None,
) -> dict[str, Any]:
    query = select(DataContract).order_by(DataContract.created_at.desc())
    contracts = [item for item in db.scalars(query).all() if _contract_visible(item, user)]
    if state:
        contracts = [
            item
            for item in contracts
            if (
                (_contract_agreement(db, item.contract_id).state
                 if _contract_agreement(db, item.contract_id) is not None
                 else item.status)
                == state
            )
        ]
    total = len(contracts)
    start = (page - 1) * page_size
    items: list[dict[str, Any]] = []
    for contract in contracts[start : start + page_size]:
        agreement = _contract_agreement(db, contract.contract_id)
        items.append(
            {
                "contract_id": contract.contract_id,
                "provider": _organization_payload(db, contract.provider_org_id),
                "consumer": _organization_payload(db, contract.consumer_type),
                "purpose": contract.purpose,
                "status": contract.status,
                "agreement_state": agreement.state if agreement else None,
                "valid_from": _iso(contract.valid_from),
                "expires_at": _iso(contract.expires_at),
                "latest_event_version": _event_version(db, contract.contract_id),
                **_allowed_actions(
                    user,
                    actions=_contract_actions(user, contract, agreement),
                    source="data_contracts/data_space_agreements",
                    state=agreement.state if agreement else contract.status,
                ),
            }
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "empty_state": total == 0,
        **_capability("LOCAL_REAL", "data_contracts/data_space_agreements"),
        "allowed_actions": [],
    }


def contract_detail(db: Session, contract_id: str, user: User) -> dict[str, Any] | None:
    contract = db.get(DataContract, contract_id)
    if contract is None or not _contract_visible(contract, user):
        return None
    agreement = _contract_agreement(db, contract.contract_id)
    events = db.scalars(
        select(ContractNegotiationEvent)
        .where(ContractNegotiationEvent.contract_id == contract.contract_id)
        .order_by(ContractNegotiationEvent.state_version.asc())
    ).all()
    actions = _contract_actions(user, contract, agreement)
    payload = {
        "contract": {
            "contract_id": contract.contract_id,
            "task_id": contract.task_id,
            "provider": _organization_payload(db, contract.provider_org_id),
            "consumer": _organization_payload(db, contract.consumer_type),
            "purpose": contract.purpose,
            "terms": contract.policy_json,
            "policy_hash": contract.policy_hash,
            "data_refs": _asset_refs_for_contract(db, contract),
            "status": contract.status,
            "valid_from": _iso(contract.valid_from),
            "expires_at": _iso(contract.expires_at),
        },
        "agreement": {
            "agreement_id": agreement.agreement_id,
            "provider_did": agreement.provider_did,
            "consumer_did": agreement.consumer_did,
            "protocol_version": agreement.protocol_version,
            "state": agreement.state,
            "requested_purpose": agreement.requested_purpose,
            "algorithm_code": agreement.algorithm_code,
            "data_product_ids": agreement.data_product_ids_json,
            "offered_policy_hash": agreement.offered_policy_hash,
            "negotiated_policy_hash": agreement.negotiated_policy_hash,
            "valid_from": _iso(agreement.valid_from),
            "expires_at": _iso(agreement.expires_at),
            "max_uses": agreement.max_uses,
            "use_count": agreement.use_count,
            "decision": agreement.decision_json,
            "last_receipt": agreement.last_receipt_json,
        }
        if agreement
        else None,
        "events": [_event_payload(db, item) for item in events],
        "timeline": [
            {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "from_state": item.from_state,
                "to_state": item.to_state,
                "state_version": item.state_version,
                "created_at": _iso(item.created_at),
            }
            for item in events
        ],
        **_allowed_actions(
            user,
            actions=actions,
            source="data_contracts/data_space_agreements/contract_negotiation_events",
            state=agreement.state if agreement else contract.status,
        ),
    }
    return payload


def _normalize_if_match(value: str | None, current: int) -> int:
    if not value:
        raise ValueError("IF_MATCH_REQUIRED")
    normalized = value.strip()
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    normalized = normalized.strip('"')
    try:
        expected = int(normalized)
    except ValueError as exc:
        raise ValueError("IF_MATCH_INVALID") from exc
    if expected != current:
        raise ValueError("NEGOTIATION_VERSION_CONFLICT")
    return expected


def _validate_attachment_metadata(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(attachments) > 16:
        raise ValueError("ATTACHMENT_METADATA_LIMIT")
    allowed = {"file_ref", "evidence_id", "upload_id", "name", "media_type", "sha256"}
    result: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict) or not set(item).issubset(allowed):
            raise ValueError("ATTACHMENT_METADATA_ONLY")
        if not any(item.get(key) for key in ("file_ref", "evidence_id", "upload_id")):
            raise ValueError("ATTACHMENT_REFERENCE_REQUIRED")
        result.append({str(key): value for key, value in item.items()})
    return result


def append_contract_event(
    db: Session,
    contract_id: str,
    user: User,
    *,
    event_type: str,
    message: str = "",
    terms: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    if_match: str | None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    contract = db.get(DataContract, contract_id)
    if contract is None:
        raise LookupError("CONTRACT_NOT_FOUND")
    agreement = _contract_agreement(db, contract_id)
    if agreement is None:
        raise ValueError("NEGOTIATION_AGREEMENT_REQUIRED")
    actions = _contract_actions(user, contract, agreement)
    normalized_type = event_type.strip().upper()
    action_name = "comment" if normalized_type in {"COMMENT", "ATTACHMENT"} else "counter"
    if normalized_type == "ACCEPT":
        action_name = "accept"
    elif normalized_type == "REJECT":
        action_name = "reject"
    if agreement.state == "ACTIVE" and normalized_type in {
        "ACCEPT",
        "REJECT",
        "COUNTER",
        "COUNTEROFFER",
    }:
        raise ValueError("NEGOTIATION_STATE_CLOSED")
    if action_name not in actions:
        raise PermissionError("CONTRACT_NEGOTIATION_FORBIDDEN")
    if agreement.state in {"REJECTED", "REVOKED", "EXPIRED"}:
        raise ValueError("NEGOTIATION_STATE_CLOSED")
    current_version = _event_version(db, contract_id)
    if idempotency_key:
        replay = db.scalar(
            select(ContractNegotiationEvent).where(
                ContractNegotiationEvent.contract_id == contract_id,
                ContractNegotiationEvent.idempotency_key == idempotency_key,
            )
        )
        if replay is not None:
            return {**_event_payload(db, replay), "idempotent_replay": True}
    _normalize_if_match(if_match, current_version)
    if not message.strip() and normalized_type in {"COMMENT", "COUNTEROFFER", "COUNTER", "REJECT"}:
        raise ValueError("NEGOTIATION_MESSAGE_REQUIRED")
    metadata = _validate_attachment_metadata(attachments or [])
    target_state = agreement.state
    if normalized_type in {"COUNTER", "COUNTEROFFER"}:
        target_state = "NEGOTIATED"
    elif normalized_type == "ACCEPT":
        target_state = "ACTIVE"
    elif normalized_type == "REJECT":
        target_state = "REJECTED"
    key = idempotency_key or sha256_json(
        {
            "contract_id": contract_id,
            "actor_org_id": user.org_id,
            "event_type": normalized_type,
            "current_version": current_version,
            "message": message,
            "terms": terms or {},
            "attachments": metadata,
        }
    )[:160]
    identity = _actor_did(db, user)
    event_payload = {
        "contract_id": contract_id,
        "agreement_id": agreement.agreement_id,
        "actor_org_id": user.org_id,
        "actor_did": identity.did_id if identity else None,
        "event_type": normalized_type,
        "message": message,
        "terms": terms or {},
        "attachments": metadata,
        "from_state": agreement.state,
        "to_state": target_state,
        "state_version": current_version + 1,
    }
    event = ContractNegotiationEvent(
        contract_id=contract_id,
        agreement_id=agreement.agreement_id,
        actor_user_id=user.user_id,
        actor_org_id=user.org_id,
        actor_did=identity.did_id if identity else None,
        event_type=normalized_type,
        message=message.strip(),
        terms_json=terms or {},
        attachment_metadata_json=metadata,
        from_state=agreement.state,
        to_state=target_state,
        state_version=current_version + 1,
        idempotency_key=key,
        event_hash=sha256_json(event_payload),
        capability_label="LOCAL_REAL",
    )
    db.add(event)
    agreement.state = target_state
    if terms:
        agreement.decision_json = {**(agreement.decision_json or {}), "latest_terms": terms}
        contract.policy_json = {**(contract.policy_json or {}), **terms}
        contract.policy_hash = sha256_json(contract.policy_json)
    add_audit_log(
        db,
        action=f"CONTRACT_NEGOTIATION_{normalized_type}",
        target_type="DATA_CONTRACT",
        target_id=contract_id,
        result="SUCCESS",
        user=user,
        details={
            "event_id": event.event_id,
            "event_type": normalized_type,
            "state_version": current_version + 1,
            "attachment_metadata_only": True,
        },
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    publish_contract_event(
        db,
        event,
        provider_org_id=contract.provider_org_id,
        consumer_org_id=contract.consumer_type,
    )
    return {**_event_payload(db, event), "idempotent_replay": False}


def _task_visible(db: Session, task: SettlementTask, user: User) -> bool:
    if task.creator_org_id == user.org_id:
        return True
    return db.scalar(
        select(TaskParticipant.participant_id).where(
            TaskParticipant.task_id == task.task_id,
            TaskParticipant.org_id == user.org_id,
        )
    ) is not None


def _transition_item(item: TtcStateTransition) -> dict[str, Any]:
    return {
        "transition_id": item.transition_id,
        "attempt_id": item.attempt_id,
        "task_id": item.task_id,
        "sequence_no": item.sequence_no,
        "from_state": item.from_state,
        "to_state": item.to_state,
        "actor_did": item.actor_did,
        "agent_did": item.agent_did,
        "trigger_code": item.trigger_code,
        "reason": item.reason,
        "trace_id": item.trace_id,
        "transition_hash": item.transition_hash,
        "occurred_at": _iso(item.occurred_at),
    }


def _attempt_item(item: TtcAttempt) -> dict[str, Any]:
    return {
        "attempt_id": item.attempt_id,
        "task_id": item.task_id,
        "capsule_id": item.capsule_id,
        "attempt_no": item.attempt_no,
        "current_state": item.current_state,
        "status": item.status,
        "trace_id": item.trace_id,
        "failure_code": item.failure_code,
        "failure_detail": item.failure_detail,
        "started_at": _iso(item.started_at),
        "ended_at": _iso(item.ended_at),
    }


def ttc_detail(db: Session, task_id: str, user: User) -> dict[str, Any] | None:
    task = db.get(SettlementTask, task_id)
    if task is None or not _task_visible(db, task, user):
        return None
    attempts = db.scalars(
        select(TtcAttempt).where(TtcAttempt.task_id == task_id).order_by(TtcAttempt.attempt_no.asc())
    ).all()
    transitions = db.scalars(
        select(TtcStateTransition)
        .where(TtcStateTransition.task_id == task_id)
        .order_by(TtcStateTransition.occurred_at.asc())
    ).all()
    snapshots = db.scalars(
        select(ExecutionSnapshot)
        .where(ExecutionSnapshot.task_id == task_id)
        .order_by(ExecutionSnapshot.snapshot_version.asc())
    ).all()
    participants = db.scalars(
        select(TaskParticipant).where(TaskParticipant.task_id == task_id)
    ).all()
    return {
        "task": {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "capsule_id": task.capsule_id,
            "status": task.status,
            "ttc_state": task.ttc_state,
            "current_attempt": task.current_attempt,
            "state_version": task.state_version,
            "current_stage": task.current_stage,
            "phase_progress_estimate": _ttc_phase_progress(task),
            "execution_snapshot_id": task.execution_snapshot_id,
            "execution_snapshot_hash": task.execution_snapshot_hash,
            "last_transition_at": _iso(task.last_transition_at),
        },
        "participants": [
            {
                "participant_id": item.participant_id,
                "org_id": item.org_id,
                "organization": _organization_payload(db, item.org_id),
                "role_in_task": item.role_in_task,
                "data_status": item.data_status,
                "confirm_status": item.confirm_status,
            }
            for item in participants
        ],
        "attempts": [_attempt_item(item) for item in attempts],
        "transitions": [_transition_item(item) for item in transitions],
        "snapshots": [
            {
                "snapshot_id": item.snapshot_id,
                "attempt_id": item.attempt_id,
                "snapshot_version": item.snapshot_version,
                "rule_id": item.rule_id,
                "rule_version": item.rule_version,
                "rule_hash": item.rule_hash,
                "policy_refs": item.policy_refs_json,
                "contract_refs": item.contract_refs_json,
                "data_refs": item.data_refs_json,
                "algorithm_code": item.algorithm_code,
                "algorithm_version": item.algorithm_version,
                "algorithm_hash": item.algorithm_hash,
                "snapshot_hash": item.snapshot_hash,
                "frozen_by_did": item.frozen_by_did,
                "trace_id": item.trace_id,
                "frozen_at": _iso(item.frozen_at),
            }
            for item in snapshots
        ],
        **_allowed_actions(
            user,
            actions=_ttc_allowed_actions(user, task),
            source="settlement_tasks/ttc_attempts/ttc_state_transitions/execution_snapshots",
            state=task.ttc_state,
        ),
    }


def ttc_list(
    db: Session,
    user: User,
    *,
    page: int,
    page_size: int,
    status_filter: str | None = None,
) -> dict[str, Any]:
    query = _task_scope_query(db, user)
    if status_filter:
        query = query.where(
            or_(
                SettlementTask.status == status_filter,
                SettlementTask.ttc_state == status_filter,
            )
        )
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    tasks = db.scalars(
        query.order_by(SettlementTask.updated_at.desc(), SettlementTask.task_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "capsule_id": task.capsule_id,
            "status": task.status,
            "ttc_state": task.ttc_state,
            "current_stage": task.current_stage,
            "current_attempt": task.current_attempt,
            "state_version": task.state_version,
            "phase_progress_estimate": _ttc_phase_progress(task),
            "updated_at": _iso(task.updated_at),
            "allowed_actions": _ttc_allowed_actions(user, task),
            **_capability(
                "LOCAL_REAL",
                "settlement_tasks/ttc_attempts/ttc_state_transitions",
                lifecycle_state=task.ttc_state,
            ),
        }
        for task in tasks
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "status": status_filter,
        "empty_state": total == 0,
        "allowed_actions": ["view"],
        **_capability("LOCAL_REAL", "settlement_tasks/ttc_attempts/ttc_state_transitions"),
    }


def ttc_events(
    db: Session,
    task_id: str,
    user: User,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any] | None:
    detail = ttc_detail(db, task_id, user)
    if detail is None:
        return None
    transitions = detail["transitions"]
    audit_rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.target_id == task_id)
        .order_by(AuditLog.occurred_at.asc())
    ).all()
    events: list[dict[str, Any]] = [
        {
            "event_id": item["transition_id"],
            "kind": "TTC_TRANSITION",
            "occurred_at": item["occurred_at"],
            "state": item["to_state"],
            "details": item,
        }
        for item in transitions
    ]
    events.extend(
        {
            "event_id": item.log_id,
            "kind": "AUDIT_LOG",
            "occurred_at": _iso(item.occurred_at),
            "state": item.result,
            "details": {
                "action_code": item.action_code,
                "target_type": item.target_type,
                "result": item.result,
                "details": item.details_json,
            },
        }
        for item in audit_rows
    )
    events.sort(key=lambda item: (item["occurred_at"] or "", item["event_id"]))
    try:
        offset = max(0, int(cursor or 0))
    except ValueError as exc:
        raise ValueError("CURSOR_INVALID") from exc
    page = events[offset : offset + limit]
    next_cursor = str(offset + len(page)) if offset + len(page) < len(events) else None
    return {
        "task_id": task_id,
        "items": page,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "limit": limit,
        **_allowed_actions(
            user,
            actions=_ttc_allowed_actions(user, db.get(SettlementTask, task_id))
            if db.get(SettlementTask, task_id) is not None
            else ["view"],
            source="ttc_state_transitions/audit_logs",
            state=detail["task"]["ttc_state"],
        ),
    }


def transition_ttc(
    db: Session,
    task_id: str,
    user: User,
    *,
    to_state: str,
    trigger: str,
    reason: str,
    if_match: str | None,
    attempt_id: str | None = None,
    agent_did: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise LookupError("TTC_TASK_NOT_FOUND")
    if not _task_visible(db, task, user):
        raise PermissionError("TTC_TASK_SCOPE_DENIED")
    if user.role_code not in {"EXCHANGE", "REGULATOR"}:
        raise PermissionError("TTC_OPERATION_FORBIDDEN")
    normalized = to_state.strip().upper()
    if normalized not in {"HUMAN_REVIEW", "REWORK", "INTERRUPTED", "CANCELLED"}:
        raise PermissionError("TTC_SYSTEM_TRANSITION_REQUIRED")
    try:
        expected = _normalize_if_match(if_match, int(task.state_version or 1))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    identity = _actor_did(db, user)
    try:
        transition = TtcStateMachine.transition(
            db,
            task,
            TTCState(normalized),
            identity.did_id,
            trigger,
            reason,
            agent_did=agent_did,
            trace_id=trace_id,
            attempt_id=attempt_id,
        )
        db.commit()
    except TrustDomainError:
        db.rollback()
        raise
    participant_org_ids = db.scalars(
        select(TaskParticipant.org_id).where(TaskParticipant.task_id == task.task_id)
    ).all()
    publish_ttc_transition(
        db,
        task,
        transition_id=transition.transition_id,
        to_state=task.ttc_state,
        actor_user_id=user.user_id,
        participant_org_ids=participant_org_ids,
    )
    return {
        "task_id": task_id,
        "ttc_state": task.ttc_state,
        "state_version": task.state_version,
        "transition": _transition_item(transition),
        "idempotent_replay": False,
        **_allowed_actions(
            user,
            actions=_ttc_allowed_actions(user, task),
            source="ttc_state_machine/ttc_state_transitions",
            state=task.ttc_state,
        ),
    }


def _compute_visible(db: Session, job: PrivacyComputeJob, user: User) -> bool:
    task = db.get(SettlementTask, job.task_id)
    if task is not None:
        return _task_visible(db, task, user)

    # Trusted-space queries use a generated task id for the connector
    # invocation, but deliberately do not create a SettlementTask.  Scope
    # those jobs by the two organizations recorded in the signed execution
    # attestation instead of making every detached job visible.
    attestation = job.execution_attestation_json or {}
    if not attestation.get("request_item_id"):
        return False
    return user.org_id in {
        str(attestation.get("applicant_org_id") or ""),
        str(attestation.get("provider_org_id") or ""),
    }


LOCAL_COMPUTE_ADAPTER = "LOCAL_CONTROLLED_SETTLEMENT_V1"


def _compute_control_actions(
    db: Session,
    job: PrivacyComputeJob,
    user: User,
    task: SettlementTask | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return only actions backed by a real, currently available executor.

    The current local adapter runs synchronously and does not expose a
    cancellation handle or a requeue worker.  Consequently retry is always
    reported as blocked, while cancellation is available only for a queued
    local job whose TTC state can be cancelled.  This keeps the UI/API honest
    instead of turning a button click into a status-only fake execution.
    """

    task = task or db.get(SettlementTask, job.task_id)
    actions = ["view", "poll_logs"]
    reasons: dict[str, str] = {
        "retry": "当前运行面没有真实重试队列/执行器，不会伪造新的计算尝试。",
    }
    if job.status not in {"QUEUED", "PENDING"}:
        reasons["cancel"] = "计算已开始或已结束，当前执行器没有可中止句柄。"
    elif job.adapter_code != LOCAL_COMPUTE_ADAPTER:
        reasons["cancel"] = "当前适配器没有可中止的本地执行器。"
    elif task is None:
        reasons["cancel"] = "关联 TTC 任务不存在，无法安全取消。"
    else:
        try:
            can_cancel = TtcStateMachine.can_transition(task.ttc_state, TTCState.CANCELLED)
        except (KeyError, ValueError):
            can_cancel = False
        actor_did = _actor_did(db, user)
        if not can_cancel:
            reasons["cancel"] = f"TTC 当前状态 {task.ttc_state} 不允许取消。"
        elif actor_did is None or actor_did.credential_status != "VALID":
            reasons["cancel"] = "当前主体没有可用于受控取消的有效 DID 凭证。"
        else:
            actions.append("cancel")
            reasons.pop("cancel", None)
    return actions, reasons


def control_computation(
    db: Session,
    job_id: str,
    user: User,
    *,
    action: str,
    reason: str,
    if_match: str | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Apply a truthful computation control command.

    ``cancel`` only terminates a queued local job and records the TTC
    cancellation in the same transaction.  ``retry`` is deliberately a
    structured 409 until a real requeue executor is configured.
    """

    job = db.get(PrivacyComputeJob, job_id)
    if job is None:
        raise LookupError("COMPUTE_JOB_NOT_FOUND")
    if not _compute_visible(db, job, user):
        raise PermissionError("COMPUTE_JOB_SCOPE_DENIED")
    normalized_action = action.strip().upper()
    if normalized_action not in {"CANCEL", "RETRY"}:
        raise ValueError("COMPUTE_ACTION_INVALID")
    normalized_key = (idempotency_key or "").strip()
    if not normalized_key:
        raise TrustDomainError(
            "COMPUTE_ACTION_IDEMPOTENCY_REQUIRED",
            "计算控制动作必须提供 Idempotency-Key。",
        )
    if len(normalized_key) > 160:
        raise TrustDomainError(
            "COMPUTE_ACTION_IDEMPOTENCY_INVALID",
            "Idempotency-Key 长度不能超过 160 个字符。",
        )
    normalized_reason = reason.strip() or (
        "用户请求取消计算" if normalized_action == "CANCEL" else "用户请求重试计算"
    )
    fingerprint = sha256_json(
        {
            "job_id": job.job_id,
            "action": normalized_action,
            "reason": normalized_reason,
            "if_match": if_match,
        }
    )
    if job.action_idempotency_key == normalized_key:
        if job.action_fingerprint != fingerprint:
            raise TrustDomainError(
                "COMPUTE_ACTION_IDEMPOTENCY_CONFLICT",
                "相同 Idempotency-Key 对应的计算控制参数不一致。",
            )
        if job.action_response_json:
            return {**job.action_response_json, "idempotent_replay": True}

    if not if_match:
        raise TrustDomainError(
            "COMPUTE_ACTION_IF_MATCH_REQUIRED",
            "计算控制动作必须提供当前 job 版本的 If-Match。",
        )
    expected = if_match.strip().removeprefix("W/").strip('"')
    try:
        expected_version = int(expected)
    except ValueError as exc:
        raise TrustDomainError(
            "COMPUTE_ACTION_VERSION_INVALID",
            "If-Match 必须是当前计算任务的整数版本号。",
        ) from exc
    current_version = int(job.state_version or 1)
    if expected_version != current_version:
        raise TrustDomainError(
            "COMPUTE_ACTION_VERSION_CONFLICT",
            "计算任务已发生变化，请刷新后重试。",
        )

    task = db.get(SettlementTask, job.task_id)
    actions, reasons = _compute_control_actions(db, job, user, task)
    action_name = normalized_action.lower()
    if action_name not in actions:
        code = f"COMPUTE_{normalized_action}_BLOCKED"
        raise TrustDomainError(code, reasons.get(action_name, "当前环境不允许该计算控制动作。"))

    old_status = job.status
    transition = None
    actor_did = _actor_did(db, user)
    try:
        if normalized_action == "CANCEL":
            if task is None or actor_did is None:
                raise TrustDomainError(
                    "COMPUTE_CANCEL_BLOCKED",
                    reasons.get("cancel", "缺少可用于受控取消的主体身份。"),
                )
            transition = TtcStateMachine.transition(
                db,
                task,
                TTCState.CANCELLED,
                actor_did.did_id,
                "COMPUTE_CANCELLED",
                normalized_reason,
                trace_id=uuid.uuid4().hex,
                attempt_id=job.attempt_id,
            )
            job.status = "CANCELLED"
            job.cancelled_at = utc_now()
            job.logs_json = [
                *(job.logs_json or []),
                f"Compute cancellation recorded: {normalized_reason}",
            ]
            job.state_version = current_version + 1
            add_audit_log(
                db,
                action="CANCEL_PRIVACY_COMPUTE",
                target_type="PRIVACY_COMPUTE_JOB",
                target_id=job.job_id,
                result="SUCCESS",
                user=user,
                details={
                    "task_id": job.task_id,
                    "from_status": old_status,
                    "to_status": job.status,
                    "reason": normalized_reason,
                    "transition_id": transition.transition_id if transition else None,
                    "capability_state": "LOCAL_REAL",
                },
            )
        payload = computation_detail(db, job.job_id, user) or {}
        payload.update(
            {
                "action": normalized_action.lower(),
                "action_reason": normalized_reason,
                "idempotent_replay": False,
            }
        )
        job.action_code = normalized_action
        job.action_idempotency_key = normalized_key
        job.action_fingerprint = fingerprint
        job.action_response_json = payload
        db.commit()
    except TrustDomainError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    if normalized_action == "CANCEL" and task is not None:
        participant_org_ids = db.scalars(
            select(TaskParticipant.org_id).where(TaskParticipant.task_id == task.task_id)
        ).all()
        publish_computation_action(
            db,
            job,
            action=normalized_action,
            actor_user_id=user.user_id,
            org_ids=[task.creator_org_id, *participant_org_ids],
        )
    return payload


def computation_detail(db: Session, job_id: str, user: User) -> dict[str, Any] | None:
    job = db.get(PrivacyComputeJob, job_id)
    if job is None or not _compute_visible(db, job, user):
        return None
    task = db.get(SettlementTask, job.task_id)
    participants = db.scalars(
        select(TaskParticipant).where(TaskParticipant.task_id == job.task_id)
    ).all()
    attempt = db.get(TtcAttempt, job.attempt_id) if job.attempt_id else None
    snapshot = db.get(ExecutionSnapshot, job.execution_snapshot_id) if job.execution_snapshot_id else None
    evidence = db.scalars(
        select(BlockchainEvidence)
        .where(BlockchainEvidence.task_id == job.task_id)
        .order_by(BlockchainEvidence.created_at.asc())
    ).all()
    attestation = job.execution_attestation_json or {}
    is_trusted_query = task is None and bool(attestation.get("request_item_id"))
    participant_payloads = [
        {
            "org_id": item.org_id,
            "organization": _organization_payload(db, item.org_id),
            "role_in_task": item.role_in_task,
            "data_status": item.data_status,
        }
        for item in participants
    ]
    if is_trusted_query:
        seen_org_ids = {item["org_id"] for item in participant_payloads}
        for org_id, role_in_task, data_status in (
            (attestation.get("applicant_org_id"), "QUERY_APPLICANT", "AUTHORIZED"),
            (attestation.get("provider_org_id"), "DATA_PROVIDER", "CONNECTOR_READY"),
        ):
            normalized_org_id = str(org_id or "")
            if normalized_org_id and normalized_org_id not in seen_org_ids:
                participant_payloads.append(
                    {
                        "org_id": normalized_org_id,
                        "organization": _organization_payload(db, normalized_org_id),
                        "role_in_task": role_in_task,
                        "data_status": data_status,
                    }
                )
                seen_org_ids.add(normalized_org_id)

    # Participants are real task registrations for settlement jobs.  A
    # completed trusted query has a verified subject connector attestation,
    # so its capability is the registered local adapter even without a TTC
    # task row.  No external MPC/TEE capability is inferred here.
    external_state = "ADAPTER" if is_trusted_query else ("BLOCKED" if len(participants) < 2 else "ADAPTER")
    query_receipts = db.scalars(
        select(ExecutionReceipt)
        .where(ExecutionReceipt.task_id == job.task_id)
        .order_by(ExecutionReceipt.executed_at.asc())
    ).all() if is_trusted_query else []
    receipt_payloads = [
        {
            "evidence_id": item.evidence_id,
            "stage": item.stage,
            "biz_type": item.biz_type,
            "biz_id": item.biz_id,
            "evidence_hash": item.evidence_hash,
            "chain_code": item.chain_code,
            "status": item.status,
            "tx_hash": item.tx_hash,
            "block_height": item.block_height,
        }
        for item in evidence
    ]
    receipt_payloads.extend(
        {
            "evidence_id": item.receipt_id,
            "stage": "IN_COMPUTE",
            "biz_type": "TRUSTED_QUERY",
            "biz_id": item.request_item_id,
            "evidence_hash": item.result_hash,
            "chain_code": None,
            "status": item.status,
            "tx_hash": None,
            "block_height": None,
        }
        for item in query_receipts
    )
    control_actions, action_reasons = _compute_control_actions(db, job, user, task)
    return {
        "job": {
            "job_id": job.job_id,
            "task_id": job.task_id,
            "task_name": task.task_name
            if task
            else f"智能查询 · {(job.result_json or {}).get('resource_name') or job.algorithm_code}",
            "task_kind": "TRUSTED_QUERY" if is_trusted_query else "SETTLEMENT",
            "algorithm_code": job.algorithm_code,
            "adapter_code": job.adapter_code,
            "status": job.status,
            "progress": job.progress,
            "duration_ms": job.duration_ms,
            "input_hashes": job.input_hashes_json,
            "output_hash": job.output_hash,
            "result": job.result_json
            if (job.execution_attestation_json or {}).get("applicant_org_id") == user.org_id
            else {"output_hash": job.output_hash},
            "privacy_guarantees": job.privacy_guarantees_json,
            "logs": job.logs_json,
            "attempt_id": job.attempt_id,
            "execution_snapshot_id": job.execution_snapshot_id,
            "state_version": int(job.state_version or 1),
        },
        "participants": participant_payloads,
        "attempt": _attempt_item(attempt) if attempt else None,
        "snapshot": {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_hash": snapshot.snapshot_hash,
            "rule_hash": snapshot.rule_hash,
            "algorithm_hash": snapshot.algorithm_hash,
        }
        if snapshot
        else None,
        "receipts": receipt_payloads,
        "external_execution": {
            "capability_state": external_state,
            "source_of_truth": "privacy_compute_jobs/execution_attestation"
            if is_trusted_query
            else "privacy_compute_jobs/task_participants",
            "adapter_code": job.adapter_code,
            "tee_attestation": "NOT_CONFIGURED",
            "cross_domain_participants": [
                str(org_id)
                for org_id in (
                    attestation.get("applicant_org_id"),
                    attestation.get("provider_org_id"),
                )
                if org_id
            ]
            if is_trusted_query
            else [],
        },
        **_allowed_actions(
            user,
            actions=control_actions,
            source="privacy_compute_jobs/ttc_attempts/task_participants",
            state=job.status,
        ),
        "action_reasons": action_reasons,
    }


def computation_events(
    db: Session,
    job_id: str,
    user: User,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> dict[str, Any] | None:
    detail = computation_detail(db, job_id, user)
    if detail is None:
        return None
    logs = detail["job"].get("logs") or []
    try:
        offset = max(0, int(cursor or 0))
    except ValueError as exc:
        raise ValueError("CURSOR_INVALID") from exc
    items = [
        {"sequence_no": offset + index + 1, "kind": "COMPUTE_LOG", "detail": value}
        for index, value in enumerate(logs[offset : offset + limit])
    ]
    next_cursor = str(offset + len(items)) if offset + len(items) < len(logs) else None
    return {
        "job_id": job_id,
        "items": items,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
        "limit": limit,
        **_allowed_actions(
            user,
            actions=["view"],
            source="privacy_compute_jobs.logs_json",
            state=detail["job"]["status"],
        ),
    }


def result_visible(db: Session, result: SettlementResult, user: User) -> bool:
    task = db.get(SettlementTask, result.task_id)
    if task is None:
        return False
    if user.role_code == "REGULATOR" and "VIEW_AUDIT" in set(user.permissions_json or []):
        return True
    if not _task_visible(db, task, user):
        return False
    return result.org_id in {None, user.org_id} or user.org_id == result.org_id


def result_detail(db: Session, result_id: str, user: User) -> dict[str, Any] | None:
    result = db.get(SettlementResult, result_id)
    if result is None or not result_visible(db, result, user):
        return None
    task = db.get(SettlementTask, result.task_id)
    signatures = db.scalars(
        select(Signature)
        .where(
            Signature.target_type.in_(("RESULT_CONFIRM", "RESULT_REJECT")),
            Signature.target_id == result.result_id,
        )
        .order_by(Signature.created_at.asc())
    ).all()
    evidence = db.scalars(
        select(BlockchainEvidence)
        .where(
            BlockchainEvidence.task_id == result.task_id,
            BlockchainEvidence.biz_id == result.result_id,
        )
        .order_by(BlockchainEvidence.created_at.asc())
    ).all()
    batches = db.scalars(
        select(EvidenceBatch)
        .where(EvidenceBatch.task_id == result.task_id)
        .order_by(EvidenceBatch.sealed_at.asc())
    ).all()
    batch_payloads: list[dict[str, Any]] = []
    for batch in batches:
        items = db.scalars(
            select(EvidenceBatchItem)
            .where(EvidenceBatchItem.batch_id == batch.batch_id)
            .order_by(EvidenceBatchItem.sequence_no.asc())
        ).all()
        outboxes = db.scalars(
            select(EvidenceOutbox).where(EvidenceOutbox.batch_id == batch.batch_id)
        ).all()
        anchors = db.scalars(
            select(BlockchainAnchor).where(BlockchainAnchor.batch_id == batch.batch_id)
        ).all()
        batch_payloads.append(
            {
                "batch_id": batch.batch_id,
                "batch_type": batch.batch_type,
                "merkle_root": batch.merkle_root,
                "leaf_count": batch.leaf_count,
                "status": batch.status,
                "items": [
                    {
                        "item_id": item.item_id,
                        "evidence_type": item.evidence_type,
                        "biz_type": item.biz_type,
                        "biz_id": item.biz_id,
                        "evidence_hash": item.evidence_hash,
                        "metadata": item.metadata_json,
                    }
                    for item in items
                ],
                "outbox": [
                    {
                        "outbox_id": item.outbox_id,
                        "event_type": item.event_type,
                        "status": item.status,
                        "payload_hash": item.payload_hash,
                        "published_at": _iso(item.published_at),
                    }
                    for item in outboxes
                ],
                "anchors": [
                    {
                        "anchor_id": item.anchor_id,
                        "adapter_code": item.adapter_code,
                        "capability_label": item.capability_label,
                        "network_code": item.network_code,
                        "anchor_payload_hash": item.anchor_payload_hash,
                        "transaction_hash": item.transaction_hash,
                        "block_height": item.block_height,
                        "status": item.status,
                        "anchored_at": _iso(item.anchored_at),
                    }
                    for item in anchors
                ],
            }
        )
    can_confirm = (
        result.org_id == user.org_id
        and user.role_code in {"GENERATOR", "RETAILER"}
        and result.confirm_status in {"UNCONFIRMED", "PENDING"}
    )
    return {
        "result": {
            "result_id": result.result_id,
            "task_id": result.task_id,
            "attempt_id": result.attempt_id,
            "org_id": result.org_id,
            "result_scope": result.result_scope,
            "result": result.result_json if can_view_subject_value(user, result.org_id or "", authorized=result.org_id == user.org_id) else {"result_hash": result.result_hash},
            "result_hash": result.result_hash,
            "confirm_status": result.confirm_status,
            "created_at": _iso(result.created_at),
        },
        "task": {
            "task_id": task.task_id if task else None,
            "ttc_state": task.ttc_state if task else None,
            "state_version": task.state_version if task else None,
        },
        "signatures": [
            {
                "signature_id": item.signature_id,
                "signer_org_id": item.signer_org_id,
                "signer_did": item.signer_did,
                "target_type": item.target_type,
                "target_hash": item.target_hash,
                "verify_status": item.verify_status,
                "created_at": _iso(item.created_at),
            }
            for item in signatures
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "stage": item.stage,
                "biz_type": item.biz_type,
                "biz_id": item.biz_id,
                "evidence_hash": item.evidence_hash,
                "tx_hash": item.tx_hash,
                "block_height": item.block_height,
                "chain_code": item.chain_code,
                "status": item.status,
            }
            for item in evidence
        ],
        "formal_evidence": batch_payloads,
        **_allowed_actions(
            user,
            actions=["view", "verify_evidence"] + (["confirm_result"] if can_confirm else []),
            source="settlement_results/signatures/blockchain_evidence/evidence_outbox",
            state=result.confirm_status,
        ),
    }


def result_list(db: Session, user: User, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    rows = db.scalars(select(SettlementResult).order_by(SettlementResult.created_at.desc())).all()
    rows = [item for item in rows if result_visible(db, item, user)]
    total = len(rows)
    start = (page - 1) * page_size
    items = []
    for result in rows[start : start + page_size]:
        items.append(
            {
                "result_id": result.result_id,
                "task_id": result.task_id,
                "attempt_id": result.attempt_id,
                "org_id": result.org_id,
                "result_scope": result.result_scope,
                "result_hash": result.result_hash,
                "confirm_status": result.confirm_status,
                **_allowed_actions(
                    user,
                    actions=["view"],
                    source="settlement_results",
                    state=result.confirm_status,
                ),
            }
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "empty_state": total == 0,
        "allowed_actions": [],
        **_capability("LOCAL_REAL", "settlement_results"),
    }


def audit_list(db: Session, user: User, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    if user.role_code != "REGULATOR" or "VIEW_AUDIT" not in set(user.permissions_json or []):
        raise PermissionError("AUDIT_SCOPE_DENIED")
    visible_task_ids = (
        set(db.scalars(select(SettlementTask.task_id)).all())
        if user.role_code == "REGULATOR"
        else set(db.scalars(_task_scope_query(db, user).with_only_columns(SettlementTask.task_id)).all())
    )
    logs = db.scalars(select(AuditLog).order_by(AuditLog.occurred_at.desc())).all()
    reports = db.scalars(select(AuditReport).order_by(AuditReport.created_at.desc())).all()
    logs = [
        item
        for item in logs
        if item.actor_org_id == user.org_id
        or item.target_id in visible_task_ids
        or item.target_type in {"DATA_USAGE_REQUEST", "TRUSTED_SPACE_QUERY_CONFIRMATION"}
        and item.actor_org_id == user.org_id
    ]
    reports = [item for item in reports if item.task_id in visible_task_ids]
    total = len(logs) + len(reports)
    entries = [
        {
            "record_type": "AUDIT_LOG",
            "record_id": item.log_id,
            "occurred_at": _iso(item.occurred_at),
            "action_code": item.action_code,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "result": item.result,
            "actor_org_id": item.actor_org_id,
            "details": item.details_json,
        }
        for item in logs
    ] + [
        {
            "record_type": "AUDIT_REPORT",
            "record_id": item.report_id,
            "occurred_at": _iso(item.created_at),
            "action_code": "AUDIT_REPORT",
            "target_type": "AUDIT_REPORT",
            "target_id": item.report_id,
            "result": item.status,
            "actor_org_id": None,
            "details": {
                "task_id": item.task_id,
                "attempt_id": item.attempt_id,
                "title": item.report_title,
                "risk_level": item.risk_level,
                "report_hash": item.report_hash,
                "evidence_refs": item.evidence_refs_json,
            },
        }
        for item in reports
    ]
    entries.sort(key=lambda item: item["occurred_at"] or "", reverse=True)
    start = (page - 1) * page_size
    return {
        "items": entries[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "reports": [item for item in entries if item["record_type"] == "AUDIT_REPORT"][:page_size],
        **_allowed_actions(
            user,
            actions=["view", "export_json", "export_csv"],
            source="audit_logs/audit_reports",
            state="READ_ONLY",
        ),
    }


def audit_task(db: Session, task_id: str, user: User) -> dict[str, Any] | None:
    if user.role_code != "REGULATOR" or "VIEW_AUDIT" not in set(user.permissions_json or []):
        raise PermissionError("AUDIT_SCOPE_DENIED")
    task = db.get(SettlementTask, task_id)
    if task is None:
        return None
    if user.role_code != "REGULATOR" and not _task_visible(db, task, user):
        return None
    audit = audit_list(db, user, page=1, page_size=500)
    logs = [item for item in audit["items"] if item.get("target_id") == task_id]
    report_rows = db.scalars(
        select(AuditReport).where(AuditReport.task_id == task_id).order_by(AuditReport.created_at.asc())
    ).all()
    evidence = db.scalars(
        select(BlockchainEvidence).where(BlockchainEvidence.task_id == task_id).order_by(BlockchainEvidence.created_at.asc())
    ).all()
    transitions = db.scalars(
        select(TtcStateTransition).where(TtcStateTransition.task_id == task_id).order_by(TtcStateTransition.occurred_at.asc())
    ).all()
    return {
        "task": {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "ttc_state": task.ttc_state,
            "status": task.status,
            "state_version": task.state_version,
        },
        "audit_chain": logs,
        "transitions": [_transition_item(item) for item in transitions],
        "reports": [
            {
                "report_id": item.report_id,
                "attempt_id": item.attempt_id,
                "title": item.report_title,
                "status": item.status,
                "risk_level": item.risk_level,
                "report_hash": item.report_hash,
                "evidence_refs": item.evidence_refs_json,
            }
            for item in report_rows
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "stage": item.stage,
                "biz_type": item.biz_type,
                "biz_id": item.biz_id,
                "evidence_hash": item.evidence_hash,
                "tx_hash": item.tx_hash,
                "block_height": item.block_height,
                "chain_code": item.chain_code,
                "status": item.status,
            }
            for item in evidence
        ],
        **_allowed_actions(
            user,
            actions=["view", "export_json", "export_csv"],
            source="audit_logs/audit_reports/ttc_state_transitions/blockchain_evidence",
            state=task.ttc_state,
        ),
    }
