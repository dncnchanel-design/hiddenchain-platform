from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import BlockchainEvidence, User
from ..schemas import (
    ComputationAction,
    ContractNegotiationAction,
    ContractNegotiationEventCreate,
    ResultConfirmRequest,
    TtcTransitionAction,
)
from ..services.adapters import LocalEvidenceLedgerAdapter
from ..services.common import add_audit_log
from ..services import notifications as notification_service
from ..services import trust_space as trust_space_service
from ..services.trust_domain import TrustDomainError


router = APIRouter(prefix="/trust-space", tags=["trust-space"])


_AUDIT_EXPORT_HEADERS = {
    "record_type": "记录类型",
    "record_id": "记录编号",
    "occurred_at": "发生时间",
    "action_code": "操作动作",
    "target_type": "对象类型",
    "target_id": "对象编号",
    "result": "执行结果",
    "actor_org_id": "操作主体组织",
}

_AUDIT_EXPORT_LABELS = {
    "AUDIT_LOG": "审计日志",
    "AUDIT_REPORT": "审计报告",
    "AUDIT_EXPORT": "审计导出记录",
    "LOGIN": "登录平台",
    "EXPORT_AUDIT_RECORDS": "导出审计记录",
    "RUN_TRUSTED_SETTLEMENT_WORKFLOW": "执行可信结算流程",
    "GENERATE_AUDIT_REPORT": "生成审计报告",
    "VERIFY_CHAIN_EVIDENCE": "核验证据台账",
    "REVIEW_AUDIT_REPORT": "审核审计报告",
    "CONFIRM_SETTLEMENT_RESULT": "确认结算结果",
    "CREATE_SETTLEMENT_TASK": "创建结算任务",
    "CHECK_DATA_SPACE_USAGE_CONTROL": "检查数据空间使用控制",
    "CREATE_RULE_PACKAGE": "创建使用规则",
    "ACTIVATE_RULE_PACKAGE": "启用规则版本",
    "RUN_PRIVACY_LOAD_ANALYSIS": "执行隐私负荷分析",
    "INVOKE_DEEPSEEK_AGENT": "调用智能助手",
    "AGENT_AUDIT_QUERY": "发起审计查询",
    "INJECT_TEST_ANOMALY": "注入测试风险事件",
    "RESOLVE_ANOMALY": "处置风险事件",
    "UPLOAD_DATA_REFERENCE": "登记数据引用",
    "UPLOAD_EXCEL_BATCH": "导入表格数据",
    "SIGN_DATA_COMMITMENT": "签署数据承诺",
    "TRUSTED_SETTLEMENT_ATTEMPT_FAILED": "可信结算尝试失败",
    "REJECT_SETTLEMENT_RESULT": "驳回结算结果",
    "IMPORT_AND_RUN_SETTLEMENT": "导入并执行结算",
    "DATA_USAGE_REQUEST_SUBMITTED": "提交数据使用申请",
    "DATA_USAGE_REQUEST_EXPIRED": "数据使用申请过期",
    "DATA_USAGE_REQUEST_APPROVE": "批准数据使用申请",
    "DATA_USAGE_REQUEST_REJECT": "拒绝数据使用申请",
    "DATA_USAGE_REQUEST_REVOKE": "撤销数据使用授权",
    "CANCEL_PRIVACY_COMPUTE": "取消隐私计算任务",
    "CONFIRM_TRUSTED_EXECUTION_REVIEW": "确认可信执行复核",
    "REJECT_TRUSTED_EXECUTION_REVIEW": "驳回可信执行复核",
    "TRUSTED_EXECUTION_CLOSED_LOOP": "完成可信执行闭环",
    "ASSISTANT_MESSAGE_PLANNED": "生成智能助手计划",
    "ASSISTANT_WRITE_REVIEW_REQUESTED": "提交智能助手写入复核",
    "ASSISTANT_TOOL_INVOKE": "调用智能助手工具",
    "ASSISTANT_PLAN_CANCEL": "取消智能助手计划",
    "ASSISTANT_PLAN_RETRY": "重试智能助手计划",
    "USER": "用户",
    "SETTLEMENT_TASK": "结算任务",
    "SETTLEMENT_RESULT": "结果回执",
    "BLOCKCHAIN_EVIDENCE": "证据台账记录",
    "DATA_UPLOAD": "数据引用",
    "EXCEL_IMPORT": "表格导入记录",
    "DATA_SPACE_AGREEMENT": "数据调用协议",
    "SETTLEMENT_RULE": "使用规则",
    "PRIVACY_ANALYSIS_JOB": "隐私分析任务",
    "DATA_USAGE_REQUEST": "数据使用申请",
    "TRUSTED_EXECUTION_REVIEW": "可信执行复核",
    "TRUSTED_EXECUTION": "可信执行任务",
    "DATA_CONTRACT": "数据协议",
    "PRIVACY_COMPUTE_JOB": "隐私计算任务",
    "ASSISTANT_SESSION": "智能助手会话",
    "ASSISTANT_PLAN_STEP": "智能助手计划步骤",
    "ASSISTANT_PLAN": "智能助手计划",
    "ANOMALY_EVENT": "风险事件",
    "AGENT": "能力模块",
    "SUCCESS": "成功",
    "SUCCEEDED": "已完成",
    "GENERATED": "已生成",
    "FAILED": "失败",
    "REJECTED": "已拒绝",
    "DENIED": "已拒绝",
    "PASS": "通过",
    "PASSED": "已通过",
    "VALID": "有效",
    "INVALID": "无效",
    "CONFIRMED": "已确认",
    "AUDITED": "已审计",
    "RESOLVED": "已处理",
    "ACTIVE": "已启用",
    "READY": "已就绪",
    "RUNNING": "执行中",
    "PROCESSING": "处理中",
    "IN_PROGRESS": "进行中",
    "OPEN": "待处置",
    "PENDING": "待处理",
    "PENDING_REVIEW": "待复核",
    "PENDING_CONFIRMATION": "待双方确认",
    "PARTIALLY_CONFIRMED": "部分已确认",
    "UNCONFIRMED": "待确认",
    "CANCELLED": "已取消",
    "EXPIRED": "已过期",
    "DRAFT": "草稿",
    "REVIEW_REQUIRED": "需要复核",
    "HUMAN_REVIEW": "人工复核",
    "REWORK": "返工处理中",
    "ARCHIVED": "已归档",
    "NOT_CONFIGURED": "未配置",
    "BLOCKED": "已阻断",
    "PERMIT": "已授权",
    "LOW": "低风险",
    "MEDIUM": "中风险",
    "HIGH": "高风险",
    "CRITICAL": "严重风险",
}

_AUDIT_EXPORT_JSON_FIELD_LABELS = {
    **_AUDIT_EXPORT_HEADERS,
    "details": "附加详情",
    "record_type_label": "记录类型（中文）",
    "action_code_label": "操作动作（中文）",
    "target_type_label": "对象类型（中文）",
    "result_label": "执行结果（中文）",
}


def _audit_export_label(value: Any, fallback: str = "未登记") -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return fallback
    lookup_key = normalized.upper()
    if lookup_key in _AUDIT_EXPORT_LABELS:
        return _AUDIT_EXPORT_LABELS[lookup_key]
    if normalized.isupper() and all(char.isalnum() or char == "_" for char in normalized):
        return f"{fallback}（{normalized}）"
    return normalized


def _localized_audit_export_item(item: dict[str, Any]) -> dict[str, Any]:
    """Add human-readable labels without changing the raw audit contract."""

    return {
        **item,
        "record_type_label": _audit_export_label(item.get("record_type"), "审计记录"),
        "action_code_label": _audit_export_label(item.get("action_code"), "登记动作"),
        "target_type_label": _audit_export_label(item.get("target_type"), "登记对象"),
        "result_label": _audit_export_label(item.get("result"), "未登记结果"),
    }


@router.get("/context")
def context(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.role_context(db, user)


@router.get("/workbench")
def workbench(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.workbench(db, user)


@router.get("/help")
def help_content(
    view: str = Query(default="workbench", min_length=1, max_length=64),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return trust_space_service.contextual_help(db, user, view)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": str(exc), "message": "不支持的帮助页面"},
        ) from exc


@router.get("/notifications")
def notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    notification_type: str | None = Query(default=None, alias="type", max_length=48),
    unread_only: bool = Query(default=False),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return notification_service.list_notifications(
        db,
        user,
        page=page,
        page_size=page_size,
        notification_type=notification_type,
        unread_only=unread_only,
    )


@router.post("/notifications/{notification_id}/read")
def read_notification(
    notification_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return notification_service.mark_read(db, user, notification_id)
    except notification_service.NotificationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc


@router.post("/notifications/read-all")
def read_all_notifications(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return notification_service.mark_all_read(db, user)


@router.get("/identity")
def identity(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.identity(db, user)


@router.get("/identities")
def identity_directory(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.identity_directory(db, user)


@router.get("/identity/{did_id}/document")
def did_document(
    did_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = trust_space_service.did_document(db, did_id, user)
    if payload is None:
        raise HTTPException(status_code=404, detail="DID 文档不存在")
    return payload


@router.get("/catalog")
def catalog(
    q: str | None = Query(default=None, max_length=128),
    asset_type: str | None = Query(default=None, max_length=64),
    domain: str | None = Query(default=None, max_length=128),
    sensitivity_level: str | None = Query(default=None, max_length=8),
    provider_org_id: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.catalog(
        db,
        user,
        query_text=q,
        asset_type=asset_type,
        domain=domain,
        sensitivity_level=sensitivity_level,
        provider_org_id=provider_org_id,
        page=page,
        page_size=page_size,
    )


@router.get("/assets/{asset_id}")
def asset_detail(
    asset_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = trust_space_service.asset_detail(db, asset_id, user)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DATA_ASSET_NOT_FOUND", "message": "数据资产不存在或当前主体不可见"},
        )
    return payload


def _domain_error(exc: Exception) -> None:
    code = getattr(exc, "code", str(exc))
    message = getattr(exc, "detail", code)
    status_code = status.HTTP_409_CONFLICT
    if code.endswith("_NOT_FOUND"):
        status_code = status.HTTP_404_NOT_FOUND
    elif code.endswith("_FORBIDDEN") or code.endswith("_DENIED"):
        status_code = status.HTTP_403_FORBIDDEN
    elif code in {"IF_MATCH_REQUIRED"}:
        status_code = status.HTTP_428_PRECONDITION_REQUIRED
    elif code in {"IF_MATCH_INVALID", "NEGOTIATION_VERSION_CONFLICT"}:
        status_code = status.HTTP_412_PRECONDITION_FAILED
    elif code in {"COMPUTE_ACTION_IF_MATCH_REQUIRED"}:
        status_code = status.HTTP_428_PRECONDITION_REQUIRED
    elif code in {"COMPUTE_ACTION_VERSION_CONFLICT"}:
        status_code = status.HTTP_412_PRECONDITION_FAILED
    elif code in {
        "COMPUTE_ACTION_IDEMPOTENCY_REQUIRED",
        "COMPUTE_ACTION_IDEMPOTENCY_INVALID",
        "COMPUTE_ACTION_VERSION_INVALID",
    }:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif code in {"TTC_SYSTEM_TRANSITION_REQUIRED", "TTC_OPERATION_FORBIDDEN"}:
        status_code = status.HTTP_403_FORBIDDEN
    elif code.startswith("ATTACHMENT_") or code.endswith("_REQUIRED"):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message}) from exc


@router.get("/contracts")
def contracts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    state: str | None = Query(default=None, max_length=32),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.contract_list(db, user, page=page, page_size=page_size, state=state)


@router.get("/contracts/{contract_id}")
def contract(
    contract_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = trust_space_service.contract_detail(db, contract_id, user)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONTRACT_NOT_FOUND", "message": "合同不存在或当前主体不可见"},
        )
    return payload


def _append_event(
    contract_id: str,
    event_type: str,
    payload: ContractNegotiationEventCreate | ContractNegotiationAction,
    user: User,
    db: Session,
    if_match: str | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    try:
        return trust_space_service.append_contract_event(
            db,
            contract_id,
            user,
            event_type=event_type,
            message=payload.message,
            terms=payload.terms,
            attachments=payload.attachments,
            if_match=if_match,
            idempotency_key=idempotency_key,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        _domain_error(exc)
    raise AssertionError("unreachable")


@router.post("/contracts/{contract_id}/events", status_code=status.HTTP_201_CREATED)
def contract_event(
    contract_id: str,
    payload: ContractNegotiationEventCreate,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return _append_event(contract_id, payload.event_type, payload, user, db, if_match, idempotency_key)


@router.post("/contracts/{contract_id}/accept")
def accept_contract(
    contract_id: str,
    payload: ContractNegotiationAction,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return _append_event(contract_id, "ACCEPT", payload, user, db, if_match, idempotency_key)


@router.post("/contracts/{contract_id}/reject")
def reject_contract(
    contract_id: str,
    payload: ContractNegotiationAction,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return _append_event(contract_id, "REJECT", payload, user, db, if_match, idempotency_key)


@router.post("/contracts/{contract_id}/counter")
def counter_contract(
    contract_id: str,
    payload: ContractNegotiationAction,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return _append_event(contract_id, "COUNTER", payload, user, db, if_match, idempotency_key)


@router.get("/ttc")
def ttc_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.ttc_list(
        db,
        user,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )


@router.get("/ttc/{task_id}")
def ttc(
    task_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = trust_space_service.ttc_detail(db, task_id, user)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TTC_TASK_NOT_FOUND", "message": "TTC 任务不存在或当前主体不可见"},
        )
    return payload


@router.get("/ttc/{task_id}/events")
def ttc_event_page(
    task_id: str,
    cursor: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = trust_space_service.ttc_events(db, task_id, user, cursor=cursor, limit=limit)
    except ValueError as exc:
        _domain_error(exc)
    if payload is None:
        raise HTTPException(status_code=404, detail={"code": "TTC_TASK_NOT_FOUND", "message": "TTC 任务不存在或当前主体不可见"})
    return payload


@router.post("/ttc/{task_id}/transitions")
def ttc_transition(
    task_id: str,
    payload: TtcTransitionAction,
    response: Response,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    try:
        result = trust_space_service.transition_ttc(
            db,
            task_id,
            user,
            to_state=payload.to_state,
            trigger=payload.trigger,
            reason=payload.reason,
            if_match=if_match,
            attempt_id=payload.attempt_id,
            agent_did=payload.agent_did,
            trace_id=payload.trace_id,
        )
    except (LookupError, PermissionError, ValueError, TrustDomainError) as exc:
        _domain_error(exc)
    response.headers["ETag"] = f'"{result["state_version"]}"'
    return result


@router.get("/computations")
def computations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(trust_space_service.PrivacyComputeJob)
    if status_filter:
        query = query.where(trust_space_service.PrivacyComputeJob.status == status_filter.upper())
    jobs = db.scalars(query.order_by(trust_space_service.PrivacyComputeJob.created_at.desc())).all()
    jobs = [item for item in jobs if trust_space_service._compute_visible(db, item, user)]
    total = len(jobs)
    start = (page - 1) * page_size
    items = [trust_space_service.computation_detail(db, item.job_id, user)["job"] for item in jobs[start : start + page_size]]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "empty_state": total == 0,
        "allowed_actions": ["view", "poll_logs"],
        "capability_state": "LOCAL_REAL",
        "source_of_truth": "privacy_compute_jobs",
    }


@router.get("/computations/{job_id}")
def computation(
    job_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = trust_space_service.computation_detail(db, job_id, user)
    if payload is None:
        raise HTTPException(status_code=404, detail={"code": "COMPUTE_JOB_NOT_FOUND", "message": "计算任务不存在或当前主体不可见"})
    return payload


@router.get("/computations/{job_id}/events")
def computation_event_page(
    job_id: str,
    cursor: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = trust_space_service.computation_events(db, job_id, user, cursor=cursor, limit=limit)
    except ValueError as exc:
        _domain_error(exc)
    if payload is None:
        raise HTTPException(status_code=404, detail={"code": "COMPUTE_JOB_NOT_FOUND", "message": "计算任务不存在或当前主体不可见"})
    return payload


def _control_computation(
    job_id: str,
    action: str,
    payload: ComputationAction,
    response: Response,
    user: User,
    db: Session,
    if_match: str | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    try:
        result = trust_space_service.control_computation(
            db,
            job_id,
            user,
            action=action,
            reason=payload.reason,
            if_match=if_match,
            idempotency_key=idempotency_key,
        )
    except (LookupError, PermissionError, ValueError, TrustDomainError) as exc:
        _domain_error(exc)
    response.headers["ETag"] = f'"{result["job"]["state_version"]}"'
    return result


@router.post("/computations/{job_id}/cancel")
def cancel_computation(
    job_id: str,
    payload: ComputationAction,
    response: Response,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return _control_computation(job_id, "CANCEL", payload, response, user, db, if_match, idempotency_key)


@router.post("/computations/{job_id}/retry")
def retry_computation(
    job_id: str,
    payload: ComputationAction,
    response: Response,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    return _control_computation(job_id, "RETRY", payload, response, user, db, if_match, idempotency_key)


@router.get("/results")
def results(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.result_list(db, user, page=page, page_size=page_size)


@router.get("/results/{result_id}")
def result(
    result_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = trust_space_service.result_detail(db, result_id, user)
    if payload is None:
        raise HTTPException(status_code=404, detail={"code": "RESULT_NOT_FOUND", "message": "结果不存在或当前主体不可见"})
    return payload


@router.post("/results/{result_id}/confirm")
def confirm_result_alias(
    result_id: str,
    payload: ResultConfirmRequest,
    response: Response,
    user: User = Depends(require_roles("GENERATOR", "RETAILER")),
    db: Session = Depends(get_db),
    if_match: str = Header(alias="If-Match"),
) -> dict[str, Any]:
    # The existing trade router owns the real signature, state-machine and
    # evidence transaction.  This alias intentionally delegates to it.
    from .trade import confirm_result as existing_confirm_result

    return existing_confirm_result(result_id, payload, response, user, db, if_match)


@router.get("/evidence/{evidence_id}/verify")
def verify_evidence(
    evidence_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    evidence = db.get(BlockchainEvidence, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail={"code": "EVIDENCE_NOT_FOUND", "message": "证据不存在"})
    task = db.get(trust_space_service.SettlementTask, evidence.task_id) if evidence.task_id else None
    if task is None or (
        user.role_code != "REGULATOR"
        and not trust_space_service._task_visible(db, task, user)
    ):
        raise HTTPException(status_code=403, detail={"code": "EVIDENCE_SCOPE_DENIED", "message": "无权核验证据"})
    result = LocalEvidenceLedgerAdapter.verify(evidence)
    external_receipt_verified = (
        evidence.chain_code == "FISCO_BCOS_EVIDENCE_ANCHOR_V1"
        and evidence.status in {"CONFIRMED", "FINALIZED", "PUBLISHED"}
    )
    result["external_receipt_verified"] = external_receipt_verified
    add_audit_log(
        db,
        action="VERIFY_CHAIN_EVIDENCE",
        target_type="BLOCKCHAIN_EVIDENCE",
        target_id=evidence.evidence_id,
        result="SUCCESS" if result["matched"] else "FAILED",
        user=user,
        details=result,
    )
    db.commit()
    return {
        **result,
        "allowed_actions": ["view"],
        "capability_state": "ADAPTER" if external_receipt_verified else "DEMO",
        "source_of_truth": (
            "blockchain_evidence/fisco_bcos_verified_receipt"
            if external_receipt_verified
            else "blockchain_evidence/local_evidence_ledger"
        ),
    }


@router.get("/audit")
def audit(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return trust_space_service.audit_list(db, user, page=page, page_size=page_size)


@router.get("/audit/tasks/{task_id}")
def audit_task(
    task_id: str,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = trust_space_service.audit_task(db, task_id, user)
    if payload is None:
        raise HTTPException(status_code=404, detail={"code": "TTC_TASK_NOT_FOUND", "message": "任务不存在"})
    return payload


@router.get("/audit/export")
def export_audit(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> Response:
    payload = trust_space_service.audit_list(db, user, page=1, page_size=5000)
    add_audit_log(
        db,
        action="EXPORT_AUDIT_RECORDS",
        target_type="AUDIT_EXPORT",
        target_id=f"{user.user_id}:{format}",
        result="SUCCESS",
        user=user,
        details={"format": format, "record_count": payload["total"]},
    )
    db.commit()
    if format == "json":
        localized_items = [
            _localized_audit_export_item(item)
            for item in payload["items"]
        ]
        localized_reports = [
            _localized_audit_export_item(item)
            for item in payload["reports"]
        ]
        localized_payload = {
            **payload,
            "field_labels": _AUDIT_EXPORT_JSON_FIELD_LABELS,
            "items": localized_items,
            "reports": localized_reports,
        }
        return Response(
            content=json.dumps(localized_payload, ensure_ascii=False, default=str),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename*=UTF-8''%E5%AE%A1%E8%AE%A1%E8%AE%B0.json"},
        )
    stream = io.StringIO()
    localized_rows = [
        {
            "记录类型": _audit_export_label(item.get("record_type"), "审计记录"),
            "记录编号": item.get("record_id") or "—",
            "发生时间": item.get("occurred_at") or "—",
            "操作动作": _audit_export_label(item.get("action_code"), "登记动作"),
            "对象类型": _audit_export_label(item.get("target_type"), "登记对象"),
            "对象编号": item.get("target_id") or "—",
            "执行结果": _audit_export_label(item.get("result"), "未登记结果"),
            "操作主体组织": item.get("actor_org_id") or "—",
        }
        for item in payload["items"]
    ]
    writer = csv.DictWriter(
        stream,
        fieldnames=list(_AUDIT_EXPORT_HEADERS.values()),
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(localized_rows)
    return Response(
        content="\ufeff" + stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E5%AE%A1%E8%AE%A1%E8%AE%B0.csv"},
    )
