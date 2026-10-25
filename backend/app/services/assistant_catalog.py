"""Pure, scoped metadata reads for the assistant's controlled action catalog.

Planning never grants access. Every candidate and execution reuses the same
resource boundary; no helper here expires requests or delivers notifications.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    AuditReport, BlockchainEvidence, DataContract, DataUsageRequest, Organization,
    PrivacyComputeJob, SettlementTask, TrustedQueryTask, User, UserNotification, utc_now,
)
from ..trust_models import DataAsset, DataAssetVersion, DataSource, TtcAttempt, TtcStateTransition
from . import trust_space
from .adapters import LocalEvidenceLedgerAdapter
from .audit_scope import (
    audit_task_ids_query, audit_task_scope_query,
    audit_trusted_query_task_ids_query, audit_trusted_query_task_scope_query,
    has_audit_permission, scoped_audit_task,
)
from .data_usage_requests import UsageRequestError, _usage_budget, can_review, can_revoke, can_view
from .self_owned_query import _owned_asset


PAGE_SIZE = 20
BUSINESS_ROLES = trust_space.BUSINESS_ROLES
DETAIL_TYPES = {
    "CHECK_ASSET_INTEGRITY": ("data_asset",),
    "QUERY_AUTHORIZATION_STATUS": ("data_usage_request",),
    "CHECK_TTC_STATUS": ("settlement_task", "privacy_compute_job"),
    "VERIFY_EVIDENCE_SUMMARY": ("settlement_task", "blockchain_evidence"),
    "EXPLAIN_AUDIT": ("settlement_task", "audit_report"),
    "SUBMIT_USAGE_REQUEST": ("data_asset",),
    "APPROVE_USAGE_REQUEST": ("data_usage_request",),
    "REJECT_USAGE_REQUEST": ("data_usage_request",),
    "REVOKE_USAGE_AUTHORIZATION": ("data_usage_request",),
    "ADVANCE_TTC_STATE": ("settlement_task",),
}
LIST_ACTIONS = frozenset({
    "LIST_DATA_ASSETS", "LIST_VISIBLE_DATA_ASSETS", "LIST_AUTHORIZED_DATA_ASSETS", "LIST_AUTHORIZATIONS",
    "LIST_TASKS", "LIST_AUDIT_REPORTS", "LIST_NOTIFICATIONS", "SYSTEM_OVERVIEW",
})
WRITE_ACTIONS = frozenset({
    "SUBMIT_USAGE_REQUEST", "APPROVE_USAGE_REQUEST", "REJECT_USAGE_REQUEST",
    "REVOKE_USAGE_AUTHORIZATION", "ADVANCE_TTC_STATE",
})
STATUS_GROUPS = {
    "PENDING": frozenset({"PENDING", "SUBMITTED", "UNDER_REVIEW", "QUEUED", "READY", "DRAFT", "INIT", "IDENTITY_VERIFIED", "DATA_AUTHORIZED", "RULE_FROZEN", "HUMAN_REVIEW", "REWORK", "ANCHOR_RETRY"}),
    "FAILED": frozenset({"FAILED", "BLOCKED", "REJECTED", "INTERRUPTED"}),
    "RUNNING": frozenset({"RUNNING", "COMPUTING", "EXECUTING", "COMPUTE_EXEC", "RESULT_CONFIRM", "AUDIT_GATE", "EVIDENCE_STAGE", "EVIDENCE_ANCHOR"}),
    "SUCCEEDED": frozenset({"SUCCEEDED", "COMPLETED", "SUCCESS", "PASSED", "ARCHIVED", "CONFIRMED"}),
    "UNREAD": frozenset({"UNREAD"}),
    "READ": frozenset({"READ"}),
}
STATUS_GROUPS["NOT_FINISHED"] = STATUS_GROUPS["PENDING"] | STATUS_GROUPS["RUNNING"]


def _blocked(code: str, message: str) -> dict[str, Any]:
    return {"status": "BLOCKED", "error_code": code, "message": message, "raw_data_accessed": False}


def _role_error(user: User, action: str) -> tuple[str, str] | None:
    if action not in DETAIL_TYPES and action not in LIST_ACTIONS:
        return "UNKNOWN_ASSISTANT_ACTION", "这条指令不在受控动作范围内，请选择一个可用查询。"
    if action == "SYSTEM_OVERVIEW":
        if user.role_code == "ADMIN":
            return None
        return "ASSISTANT_ROLE_DENIED", "平台运维状态仅向运维账号开放。"
    if user.role_code not in BUSINESS_ROLES:
        return "ASSISTANT_ROLE_DENIED", "运维账号只能查询平台技术状态，不能读取企业业务内容。"
    if action in {"VERIFY_EVIDENCE_SUMMARY", "EXPLAIN_AUDIT", "ADVANCE_TTC_STATE"} and user.role_code not in {"EXCHANGE", "REGULATOR"}:
        return "ASSISTANT_ROLE_DENIED", "当前角色没有执行该助手指令的权限。"
    if action == "LIST_AUDIT_REPORTS" and user.role_code != "REGULATOR":
        return "ASSISTANT_ROLE_DENIED", "审计报告列表仅向获得审计授权的监管账号开放。"
    if action in {"VERIFY_EVIDENCE_SUMMARY", "EXPLAIN_AUDIT", "LIST_AUDIT_REPORTS"} and not has_audit_permission(user):
        return "AUDIT_SCOPE_DENIED", "当前账号尚未获得审计查看权限。"
    return None


def _settlement(db: Session, user: User, target_id: str) -> SettlementTask | None:
    return db.scalar(trust_space._task_scope_query(db, user).where(SettlementTask.task_id == target_id))


def _audit_visible(db: Session, user: User, target_id: str) -> bool:
    return scoped_audit_task(db, user, target_id) is not None or db.scalar(
        audit_trusted_query_task_scope_query(user).where(
            TrustedQueryTask.task_id == target_id
        )
    ) is not None


def _job_visible(db: Session, user: User, job: PrivacyComputeJob) -> bool:
    task = db.get(SettlementTask, job.task_id)
    return _settlement(db, user, job.task_id) is not None if task else trust_space._compute_visible(db, job, user)


def _asset_rows(db: Session, user: User, *, own: bool = False) -> list[DataAsset]:
    # ponytail: reuse catalog's metadata scan; push domain filters into SQL if it grows.
    organizations, sources = trust_space._organization_map(db), trust_space._source_map(db)
    query = trust_space._visible_asset_query(user)
    if own:
        query = query.where(DataAsset.owner_org_id == user.org_id)
    return [asset for asset in db.scalars(query.order_by(DataAsset.asset_name.asc(), DataAsset.asset_id.asc())).all()
            if trust_space._asset_visible_in_energy_scope(asset, user, organizations.get(user.org_id), sources)]


def _request_status(request: DataUsageRequest) -> str:
    # Effective expiry is deterministic metadata, without changing any row.
    if request.status == "APPROVED" and request.expires_at <= utc_now():
        return "EXPIRED"
    return request.status


def validate_target(
    db: Session, user: User, action_code: str,
    target_type: str | None, target_id: str | None,
) -> tuple[str, str] | None:
    """Check the actual resource before reads or durable write-review envelopes."""
    role_error = _role_error(user, action_code)
    if role_error:
        return role_error
    if action_code in LIST_ACTIONS:
        if action_code == "LIST_DATA_ASSETS" and target_id and target_id != user.org_id:
            return "ASSISTANT_CATALOG_SCOPE_DENIED", "本方数据目录只能查询当前账号所属主体。"
        return None
    if not target_id:
        return "ASSISTANT_TARGET_REQUIRED", "请先从当前账号可见的对象中选择要查询或申请复核的一项。"
    if target_type not in DETAIL_TYPES[action_code]:
        return "ASSISTANT_TARGET_TYPE_MISMATCH", "所选对象不适用于这条指令，请重新选择对应业务对象。"
    if target_type == "data_asset":
        detail = trust_space.asset_detail(db, target_id, user)
        if detail is None:
            return "ASSET_SCOPE_DENIED", "资产不存在或不在当前账号可见的能源范围内。"
        if action_code == "CHECK_ASSET_INTEGRITY" and user.role_code in trust_space.ENTERPRISE_ROLES and detail["asset"]["provider"]["org_id"] != user.org_id:
            return "ASSET_SCOPE_DENIED", "当前企业账号只能检查本方资产的完整性。"
        if action_code == "SUBMIT_USAGE_REQUEST":
            if not detail["actions"]["can_request_usage"]:
                return "REQUEST_SCOPE_DENIED", "这项资产不支持由当前账号发起使用申请。"
            if user.role_code == "REGULATOR" and "CREATE_CROSS_ENERGY_QUERY" not in set(user.permissions_json or []):
                return "REGULATORY_QUERY_PERMISSION_REQUIRED", "监管账号尚未获得跨能源申请权限。"
        return None
    if target_type == "data_usage_request":
        request = db.get(DataUsageRequest, target_id)
        if request is None or not can_view(request, user):
            return "REQUEST_SCOPE_DENIED", "申请不存在或不属于当前主体的申请方、提供方范围。"
        if action_code in {"APPROVE_USAGE_REQUEST", "REJECT_USAGE_REQUEST"}:
            if not can_review(request, user):
                return "PROVIDER_REVIEW_REQUIRED", "仅获得审批权限的资产提供方可提交审批复核请求。"
            if _request_status(request) not in {"SUBMITTED", "UNDER_REVIEW"}:
                return "INVALID_REQUEST_TRANSITION", "当前申请状态不允许审批或拒绝，请先查看最新状态。"
        if action_code == "REVOKE_USAGE_AUTHORIZATION":
            if not can_revoke(request, user):
                return "REQUEST_REVOKE_DENIED", "仅申请方或提供方可提交撤回复核请求。"
            if _request_status(request) not in {"SUBMITTED", "UNDER_REVIEW", "APPROVED"}:
                return "INVALID_REQUEST_TRANSITION", "当前申请状态不允许撤回或撤销。"
        return None
    if target_type == "privacy_compute_job":
        job = db.get(PrivacyComputeJob, target_id)
        if job is None or not _job_visible(db, user, job):
            return "COMPUTE_SCOPE_DENIED", "计算任务不存在或不在当前主体参与的任务范围内。"
        return None
    audit_id = target_id
    if target_type == "blockchain_evidence":
        evidence = db.get(BlockchainEvidence, target_id)
        audit_id = evidence.task_id if evidence else None
    elif target_type == "audit_report":
        report = db.get(AuditReport, target_id)
        audit_id = report.task_id if report else None
    if action_code in {"VERIFY_EVIDENCE_SUMMARY", "EXPLAIN_AUDIT"}:
        if not audit_id or not _audit_visible(db, user, audit_id):
            return "AUDIT_SCOPE_DENIED", "该对象不存在或超出当前账号已获授的审计任务范围。"
        return None
    task = _settlement(db, user, target_id)
    if task is None:
        return "TTC_SCOPE_DENIED", "任务不存在或不在当前账号创建、参与或获授的范围内。"
    if action_code == "ADVANCE_TTC_STATE":
        if not trust_space._task_visible(db, task, user):
            return "TTC_OPERATION_FORBIDDEN", "审计查看授权不包含代他方推进任务的操作权限。"
        identity = trust_space._actor_did(db, user)
        if identity is None or identity.credential_status != "VALID":
            return "TTC_OPERATION_FORBIDDEN", "当前主体没有可用于任务操作的有效身份凭证。"
        if not any(action.startswith("transition:") for action in trust_space._ttc_allowed_actions(user, task)):
            return "TTC_OPERATION_FORBIDDEN", "当前任务没有允许人工申请推进的状态转移。"
    return None


def _item(entity_id: str, entity_type: str, label: str, status: str, **extra: Any) -> dict[str, Any]:
    encoded = quote(entity_id, safe="")
    paths = {
        "data_asset": f"/trusted-space/assets/{encoded}",
        "data_usage_request": f"/trusted-space/authorizations?request={encoded}",
        "settlement_task": f"/trusted-space/ttc/{encoded}",
        "privacy_compute_job": f"/trusted-space/mpc/{encoded}",
        "audit_report": f"/trusted-space/audit?view=reports&report_id={encoded}",
        "blockchain_evidence": "/trusted-space/audit",
        "notification": "/trusted-space/workbench",
    }
    return {"entity_id": entity_id, "entity_type": entity_type, "label": label,
            "status": status, "href": paths.get(entity_type, "/trusted-space/workbench"), **extra}


def _filtered(items: list[dict[str, Any]], search: str | None, status_filter: str | None = None) -> list[dict[str, Any]]:
    needle = search.strip().casefold() if search else ""
    status = status_filter.strip().upper() if status_filter else ""
    accepted = STATUS_GROUPS.get(status, frozenset({status}))
    selected = [item for item in items
                if (not needle or needle in f"{item['label']} {item['entity_id']}".casefold())
                and (not status or status == "ALL" or (item.get("ttc_state") or item["status"]) in accepted)]
    return sorted(selected, key=lambda item: (item["label"].casefold(), item["entity_type"], item["entity_id"]))


def _list_result(items: list[dict[str, Any]], search: str | None, *, status_filter: str | None = None, **extra: Any) -> dict[str, Any]:
    selected = _filtered(items, search, status_filter)
    return {"status": "SUCCEEDED", "items": selected[:PAGE_SIZE], "total": len(selected),
            "page": 1, "page_size": PAGE_SIZE, "has_more": len(selected) > PAGE_SIZE,
            "raw_data_accessed": False, **extra}


def _asset_list(db: Session, user: User, *, own: bool, search: str | None, status_filter: str | None = None) -> dict[str, Any]:
    organizations, sources = trust_space._organization_map(db), trust_space._source_map(db)
    items = []
    for asset in _asset_rows(db, user, own=own):
        # Project registered metadata; arbitrary asset/source metadata never leaves.
        metadata = trust_space._asset_item(db, asset, organizations, sources, user)
        version = metadata.get("latest_version") or {}
        items.append(_item(asset.asset_id, "data_asset", metadata["asset_name"], asset.status,
            asset_id=asset.asset_id, asset_name=metadata["asset_name"], asset_type=asset.asset_type,
            domain=metadata["domain"], version_no=version.get("version_no"),
            record_count=version.get("record_count"), period_start=version.get("period_start"),
            period_end=version.get("period_end")))
    return _list_result(items, search, status_filter=status_filter, scope="OWN_ORGANIZATION" if own else "VISIBLE_METADATA",
                        organization_id=user.org_id, metadata_only=True, usage_authority_granted=False)


def _authorized_asset_list(db: Session, user: User, *, search: str | None, status_filter: str | None) -> dict[str, Any]:
    """Project usable grant versions; listing does not reserve or consume a use."""
    items: dict[tuple[str, str], dict[str, Any]] = {}
    organizations, sources = trust_space._organization_map(db), trust_space._source_map(db)

    def add(asset: DataAsset, version: DataAssetVersion, **grant: Any) -> None:
        metadata = trust_space._asset_item(db, asset, organizations, sources, user)
        start = end = None
        schema = version.schema_json if isinstance(version.schema_json, dict) else {}
        try:
            first, last = date.fromisoformat(str(schema.get("period_start", ""))), date.fromisoformat(str(schema.get("period_end", "")))
            if first <= last:
                start, end = first.isoformat(), last.isoformat()
        except ValueError:
            pass
        row = _item(asset.asset_id, "data_asset", f"{metadata['asset_name']} · 第 {version.version_no} 版", asset.status,
                    asset_id=asset.asset_id, asset_name=metadata["asset_name"], asset_type=asset.asset_type,
                    domain=metadata["domain"], version_id=version.version_id, asset_version_id=version.version_id,
                    version_no=version.version_no, record_count=version.record_count, period_start=start, period_end=end, **grant)
        if grant.get("authorization_id"):
            row["href"] = f"/trusted-space/authorizations?request={quote(grant['authorization_id'], safe='')}"
        items.setdefault((asset.asset_id, version.version_id), row)

    for asset in _asset_rows(db, user, own=True):
        metadata = trust_space._asset_item(db, asset, organizations, sources, user)
        if not metadata["actions"]["can_compute_own"]:
            continue
        try:
            own_asset, version, _organization, _identity = _owned_asset(db, user, asset.asset_id)
        except UsageRequestError:
            continue
        add(own_asset, version, access_basis="OWN_COMPUTE_PERMISSION")
    if user.status == "ACTIVE" and "CREATE_COMPUTE_TASK" in set(user.permissions_json or []):
        requests = db.scalars(select(DataUsageRequest).where(
            DataUsageRequest.applicant_org_id == user.org_id,
            DataUsageRequest.status == "APPROVED", DataUsageRequest.expires_at > utc_now(),
            DataUsageRequest.revoked_at.is_(None), DataUsageRequest.agreement_id.is_not(None),
            DataUsageRequest.contract_id.is_not(None),
        ).order_by(DataUsageRequest.request_id.asc())).all()
        for request in requests:
            budget = _usage_budget(db, request)
            if not budget or budget.get("usable") is not True:
                continue
            asset, version = db.get(DataAsset, request.asset_id), db.get(DataAssetVersion, request.asset_version_id)
            contract = db.get(DataContract, request.contract_id)
            source = db.get(DataSource, asset.source_id) if asset else None
            provider = db.get(Organization, request.provider_org_id)
            now = utc_now()
            if (asset is None or asset.status != "ACTIVE" or asset.owner_org_id != request.provider_org_id
                    or version is None or version.asset_id != asset.asset_id or version.status != "ACTIVE"
                    or version.effective_from and version.effective_from > now or version.effective_until and version.effective_until <= now
                    or source is None or source.status != "ACTIVE" or source.owner_org_id != request.provider_org_id
                    or provider is None or provider.status != "ACTIVE" or contract is None or contract.status != "ACTIVE"
                    or contract.provider_org_id != request.provider_org_id or contract.consumer_type != user.org_id
                    or contract.valid_from and contract.valid_from > now or contract.expires_at and contract.expires_at <= now):
                continue
            add(asset, version, access_basis="APPROVED_GRANT", authorization_id=request.request_id,
                remaining_uses=budget["remaining_uses"])
    return _list_result(list(items.values()), search, status_filter=status_filter, scope="CURRENTLY_AUTHORIZED_VERSIONS",
                        metadata_only=True, usage_authority_granted=True, requires_execution_recheck=True)


def _task_items(db: Session, user: User) -> list[dict[str, Any]]:
    items = [_item(task.task_id, "settlement_task", task.task_name, task.ttc_state or task.status, task_id=task.task_id, ttc_state=task.ttc_state, legacy_status=task.status)
             for task in db.scalars(trust_space._task_scope_query(db, user)).all()]
    task_exists = select(SettlementTask.task_id).where(SettlementTask.task_id == PrivacyComputeJob.task_id).exists()
    jobs = select(PrivacyComputeJob).where(or_(
        PrivacyComputeJob.task_id.in_(trust_space._task_scope_query(db, user).with_only_columns(SettlementTask.task_id)),
        and_(~task_exists, PrivacyComputeJob.job_id.in_(trust_space._computation_scope_query(db, user).with_only_columns(PrivacyComputeJob.job_id))),
    ))
    for job in db.scalars(jobs).all():
        if _job_visible(db, user, job):
            items.append(_item(job.job_id, "privacy_compute_job", f"计算任务 · {job.job_id}", job.status,
                               job_id=job.job_id, task_id=job.task_id, task_kind="TRUSTED_QUERY" if not db.get(SettlementTask, job.task_id) else "SETTLEMENT"))
    return items


def _report_rows(db: Session, user: User) -> list[AuditReport]:
    return list(db.scalars(select(AuditReport).where(or_(
        AuditReport.task_id.in_(audit_task_ids_query(user)),
        AuditReport.task_id.in_(audit_trusted_query_task_ids_query(user)),
    )).order_by(AuditReport.report_id.asc())).all())


def _request_items(db: Session, user: User) -> list[dict[str, Any]]:
    return [_item(request.request_id, "data_usage_request", f"{request.purpose} · {request.request_id}", _request_status(request),
                  request_id=request.request_id, asset_id=request.asset_id,
                  direction="INBOUND" if request.provider_org_id == user.org_id else "OUTBOUND")
            for request in db.scalars(trust_space._request_scope_query(user)).all()]


def read_action(
    db: Session, user: User, action_code: str, target_id: str | None = None,
    target_type: str | None = None, *, search: str | None = None, status_filter: str | None = None,
) -> dict[str, Any]:
    """Execute one allowed metadata read; never perform business mutations."""
    error = validate_target(db, user, action_code, target_type, target_id)
    if error:
        return _blocked(*error)
    if action_code in WRITE_ACTIONS:
        return _blocked("ASSISTANT_REVIEW_REQUIRED", "业务写入只能记录人工复核请求，不能作为查询执行。")
    if action_code in {"LIST_DATA_ASSETS", "LIST_VISIBLE_DATA_ASSETS"}:
        return _asset_list(db, user, own=action_code == "LIST_DATA_ASSETS", search=search, status_filter=status_filter)
    if action_code == "LIST_AUTHORIZED_DATA_ASSETS":
        return _authorized_asset_list(db, user, search=search, status_filter=status_filter)
    if action_code == "LIST_AUTHORIZATIONS":
        return _list_result(_request_items(db, user), search, status_filter=status_filter, scope="APPLICANT_OR_PROVIDER")
    if action_code == "LIST_TASKS":
        return _list_result(_task_items(db, user), search, status_filter=status_filter, scope="SCOPED_TASKS")
    if action_code == "LIST_AUDIT_REPORTS":
        return _list_result([_item(report.report_id, "audit_report", report.report_title, report.status,
                                  report_id=report.report_id, task_id=report.task_id) for report in _report_rows(db, user)], search, status_filter=status_filter, scope="GRANTED_AUDIT_TASKS")
    if action_code == "LIST_NOTIFICATIONS":
        records = db.scalars(select(UserNotification).where(
            UserNotification.user_id == user.user_id, UserNotification.org_id == user.org_id,
        )).all()
        return _list_result([_item(item.notification_id, "notification", item.title, "READ" if item.read_at else "UNREAD",
                                  notification_id=item.notification_id, severity=item.severity) for item in records], search, status_filter=status_filter, scope="OWN_USER_AND_ORGANIZATION")
    if action_code == "SYSTEM_OVERVIEW":
        from ..routers.system import admin_agents, admin_overview, admin_system

        return {"status": "SUCCEEDED", "scope": "OPERATIONS_ONLY", "overview": admin_overview(user=user, db=db),
                "system": admin_system(user=user, db=db), "agents": admin_agents(user=user, db=db), "raw_data_accessed": False}
    if action_code == "CHECK_ASSET_INTEGRITY":
        detail = trust_space.asset_detail(db, target_id, user)
        latest = detail["versions"][0] if detail["versions"] else None
        passport, quality = (latest.get("passport"), latest.get("quality")) if latest else (None, None)
        return {"status": "SUCCEEDED", "asset_id": target_id, "asset_name": detail["asset"]["asset_name"],
                "asset_status": detail["asset"]["status"],
                "version": {key: latest[key] for key in ("version_id", "version_no", "data_hash", "immutable_hash", "status")} if latest else None,
                "passport": {key: passport[key] for key in ("passport_id", "passport_hash", "status")} if passport else None,
                "quality": {key: quality[key] for key in ("quality_id", "quality_hash", "decision")} if quality else None,
                "integrity": {"version_present": bool(latest), "passport_present": bool(passport), "quality_present": bool(quality), "raw_data_accessed": False},
                "raw_data_accessed": False}
    if action_code == "QUERY_AUTHORIZATION_STATUS":
        request = db.get(DataUsageRequest, target_id)
        return {"status": "SUCCEEDED", "request_id": request.request_id, "status_value": _request_status(request),
                "persisted_status": request.status, "asset_id": request.asset_id, "applicant_org_id": request.applicant_org_id,
                "provider_org_id": request.provider_org_id, "contract_id": request.contract_id,
                "agreement_id": request.agreement_id, "state_version": request.state_version, "raw_data_accessed": False}
    if action_code == "CHECK_TTC_STATUS":
        if target_type == "privacy_compute_job":
            job = db.get(PrivacyComputeJob, target_id)
            return {"status": "SUCCEEDED", "job_id": job.job_id, "task_id": job.task_id,
                    "task_kind": "SETTLEMENT" if db.get(SettlementTask, job.task_id) else "TRUSTED_QUERY",
                    "status_value": job.status, "raw_data_accessed": False}
        task = _settlement(db, user, target_id)
        attempt = db.scalar(select(TtcAttempt).where(TtcAttempt.task_id == task.task_id).order_by(TtcAttempt.attempt_no.desc()))
        transitions = db.scalar(select(func.count(TtcStateTransition.transition_id)).where(TtcStateTransition.task_id == task.task_id)) or 0
        return {"status": "SUCCEEDED", "task_id": task.task_id, "task_name": task.task_name,
                "ttc_state": task.ttc_state, "status_value": task.status, "current_attempt": task.current_attempt,
                "attempt_id": attempt.attempt_id if attempt else None, "snapshot_id": task.execution_snapshot_id,
                "transition_count": int(transitions), "raw_data_accessed": False}
    if action_code == "VERIFY_EVIDENCE_SUMMARY":
        evidence = db.get(BlockchainEvidence, target_id) if target_type == "blockchain_evidence" else None
        task_id = evidence.task_id if evidence else target_id
        rows = [evidence] if evidence else db.scalars(select(BlockchainEvidence).where(BlockchainEvidence.task_id == task_id).order_by(BlockchainEvidence.created_at.asc(), BlockchainEvidence.evidence_id.asc())).all()
        return {"status": "SUCCEEDED", "task_id": task_id, "items": [
            {"evidence_id": item.evidence_id, "stage": item.stage, "biz_type": item.biz_type, "biz_id": item.biz_id,
             "evidence_hash": item.evidence_hash, "verify": LocalEvidenceLedgerAdapter.verify(item),
             "chain_code": item.chain_code, "status": item.status} for item in rows], "raw_data_accessed": False}
    if action_code == "EXPLAIN_AUDIT":
        report = db.get(AuditReport, target_id) if target_type == "audit_report" else None
        task_id = report.task_id if report else target_id
        detail = trust_space.audit_task(db, task_id, user)
        state = detail["task"]["ttc_state"]
        counts = {"audit_log_count": len(detail["audit_chain"]), "report_count": len(detail["reports"]), "evidence_count": len(detail["evidence"])}
        return {"status": "SUCCEEDED", "task_id": task_id, "ttc_state": state, **counts,
                **({"report_id": report.report_id} if report else {}),
                "explanation": f"任务当前处于 {state or detail['task']['status']}，已记录 {counts['audit_log_count']} 条审计日志、{counts['report_count']} 份报告和 {counts['evidence_count']} 条证据；助手未读取原始业务数据。",
                "raw_data_accessed": False}
    return _blocked("UNKNOWN_ASSISTANT_ACTION", "这条指令尚无受控查询实现。")


def target_candidates(
    db: Session, user: User, action_code: str, *, search: str | None = None, status_filter: str | None = None,
) -> list[dict[str, str]]:
    """Return at most twenty deterministic, already-authorized target choices."""
    if _role_error(user, action_code):
        return []
    if action_code in LIST_ACTIONS:
        rows = read_action(db, user, action_code, search=search, status_filter=status_filter).get("items", [])
    elif action_code in {"CHECK_ASSET_INTEGRITY", "SUBMIT_USAGE_REQUEST"}:
        rows = [_item(asset.asset_id, "data_asset", asset.asset_name, asset.status)
                for asset in _asset_rows(db, user, own=action_code == "CHECK_ASSET_INTEGRITY" and user.role_code in trust_space.ENTERPRISE_ROLES)]
    elif action_code in {"QUERY_AUTHORIZATION_STATUS", "APPROVE_USAGE_REQUEST", "REJECT_USAGE_REQUEST", "REVOKE_USAGE_AUTHORIZATION"}:
        rows = _request_items(db, user)
    elif action_code in {"CHECK_TTC_STATUS", "ADVANCE_TTC_STATE"}:
        rows = _task_items(db, user)
    else:
        rows = [_item(task.task_id, "settlement_task", task.task_name, task.status)
                for task in db.scalars(audit_task_scope_query(user)).all()]
        if action_code == "EXPLAIN_AUDIT":
            rows.extend(_item(report.report_id, "audit_report", report.report_title, report.status) for report in _report_rows(db, user))
        else:
            evidence = db.scalars(select(BlockchainEvidence).where(or_(
                BlockchainEvidence.task_id.in_(audit_task_ids_query(user)),
                BlockchainEvidence.task_id.in_(audit_trusted_query_task_ids_query(user)),
            ))).all()
            rows.extend(_item(item.evidence_id, "blockchain_evidence", f"{item.stage} · {item.evidence_id}", item.status) for item in evidence)
    selected = _filtered(rows, search, status_filter)
    if action_code not in LIST_ACTIONS:
        selected = [item for item in selected if validate_target(db, user, action_code, item["entity_type"], item["entity_id"]) is None]
    return [{key: item[key] for key in ("entity_id", "entity_type", "label", "status")} for item in selected[:PAGE_SIZE]]
