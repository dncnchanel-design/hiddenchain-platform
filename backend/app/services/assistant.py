from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AssistantMessage,
    AssistantPlan,
    AssistantPlanStep,
    AssistantSession,
    AuditLog,
    AuditReport,
    BlockchainEvidence,
    DataUsageRequest,
    Organization,
    SettlementTask,
    TaskParticipant,
    User,
)
from ..security import sha256_json
from ..services.adapters import LocalEvidenceLedgerAdapter
from ..services.common import add_audit_log
from ..services.trust_domain import TTCState
from ..trust_models import AgentTool, AssetQuality, DataAsset, DataAssetPassport, DataAssetVersion, TtcAttempt, TtcStateTransition


ALL_ASSISTANT_ROLES = frozenset({"GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"})
OVERSIGHT_ROLES = frozenset({"EXCHANGE", "REGULATOR", "ADMIN"})

ACTION_ROLES: dict[str, frozenset[str]] = {
    "CHECK_ASSET_INTEGRITY": ALL_ASSISTANT_ROLES,
    "QUERY_AUTHORIZATION_STATUS": ALL_ASSISTANT_ROLES,
    "CHECK_TTC_STATUS": ALL_ASSISTANT_ROLES,
    "VERIFY_EVIDENCE_SUMMARY": OVERSIGHT_ROLES,
    "EXPLAIN_AUDIT": OVERSIGHT_ROLES,
    "SUBMIT_USAGE_REQUEST": frozenset({"EXCHANGE", "REGULATOR"}),
    "APPROVE_USAGE_REQUEST": frozenset({"GENERATOR", "RETAILER", "ADMIN"}),
    "REJECT_USAGE_REQUEST": frozenset({"GENERATOR", "RETAILER", "ADMIN"}),
    "REVOKE_USAGE_AUTHORIZATION": frozenset({"GENERATOR", "RETAILER", "ADMIN"}),
    "ADVANCE_TTC_STATE": OVERSIGHT_ROLES,
}

ACTION_TOOL_CODES: dict[str, str] = {
    "CHECK_ASSET_INTEGRITY": "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine",
    "QUERY_AUTHORIZATION_STATUS": "EDCAdapter+OPAAdapter",
    "CHECK_TTC_STATUS": "WorkflowEngine",
    "VERIFY_EVIDENCE_SUMMARY": "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine",
    "EXPLAIN_AUDIT": "TemplateAuditFallback",
}

READ_ACTIONS = frozenset(
    {
        "CHECK_ASSET_INTEGRITY",
        "QUERY_AUTHORIZATION_STATUS",
        "CHECK_TTC_STATUS",
        "VERIFY_EVIDENCE_SUMMARY",
        "EXPLAIN_AUDIT",
    }
)
WRITE_ACTIONS = frozenset(set(ACTION_ROLES) - set(READ_ACTIONS))


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _capability(
    *,
    capability_state: str = "LOCAL_REAL_DETERMINISTIC",
    source_of_truth: str,
    allowed_actions: Iterable[str] = (),
    **extra: Any,
) -> dict[str, Any]:
    return {
        "capability_state": capability_state,
        "source_of_truth": source_of_truth,
        "allowed_actions": sorted(set(allowed_actions)),
        **extra,
    }


def _session_visible(session: AssistantSession, user: User) -> bool:
    return session.user_id == user.user_id and session.org_id == user.org_id


def _require_session(db: Session, session_id: str, user: User) -> AssistantSession:
    session = db.get(AssistantSession, session_id)
    if session is None:
        raise LookupError("ASSISTANT_SESSION_NOT_FOUND")
    if not _session_visible(session, user):
        raise PermissionError("ASSISTANT_SESSION_SCOPE_DENIED")
    return session


def _if_match(value: str | None, current: int) -> None:
    if not value:
        raise ValueError("ASSISTANT_IF_MATCH_REQUIRED")
    normalized = value.strip()
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    normalized = normalized.strip('"')
    try:
        expected = int(normalized)
    except ValueError as exc:
        raise ValueError("ASSISTANT_IF_MATCH_INVALID") from exc
    if expected != int(current):
        raise ValueError("ASSISTANT_VERSION_CONFLICT")


def _session_payload(session: AssistantSession, user: User, *, replay: bool = False) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "user_id": session.user_id,
        "org_id": session.org_id,
        "page_path": session.page_path,
        "entity_type": session.entity_type,
        "entity_id": session.entity_id,
        "status": session.status,
        "state_version": session.state_version,
        "last_message_at": _iso(session.last_message_at),
        "idempotent_replay": replay,
        **_capability(
            source_of_truth="assistant_sessions",
            allowed_actions=["send_message", "list_messages", "list_plans", "resume"],
            session_scope="user_and_org",
        ),
    }


def _message_payload(message: AssistantMessage, *, replay: bool = False) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "session_id": message.session_id,
        "plan_id": message.plan_id,
        "sequence_no": message.sequence_no,
        "role": message.role,
        "content": message.content,
        "intent_code": message.intent_code,
        "status": message.status,
        "created_at": _iso(message.created_at),
        "idempotent_replay": replay,
        **_capability(
            source_of_truth="assistant_messages",
            allowed_actions=["view"],
        ),
    }


def _step_payload(step: AssistantPlanStep) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "plan_id": step.plan_id,
        "sequence_no": step.sequence_no,
        "action_code": step.action_code,
        "tool_code": step.tool_code,
        "target_type": step.target_type,
        "target_id": step.target_id,
        "mode": step.mode,
        "status": step.status,
        "state_version": step.state_version,
        "request_id": step.request_id,
        "invocation_id": step.invocation_id,
        "input": step.input_json,
        "output": step.output_json,
        "error_code": step.error_code,
        **_capability(
            capability_state=step.capability_label,
            source_of_truth=step.source_of_truth,
            allowed_actions=(
                ["execute", "cancel"]
                if step.status in {"READY", "FAILED", "BLOCKED", "PENDING_REVIEW"}
                else ["view"]
            ),
        ),
    }


def _plan_payload(db: Session, plan: AssistantPlan, *, replay: bool = False) -> dict[str, Any]:
    steps = db.scalars(
        select(AssistantPlanStep)
        .where(AssistantPlanStep.plan_id == plan.plan_id)
        .order_by(AssistantPlanStep.sequence_no.asc())
    ).all()
    return {
        "plan_id": plan.plan_id,
        "session_id": plan.session_id,
        "trigger_message_id": plan.trigger_message_id,
        "intent_code": plan.intent_code,
        "status": plan.status,
        "state_version": plan.state_version,
        "plan": plan.plan_json,
        "plan_hash": plan.plan_hash,
        "steps": [_step_payload(item) for item in steps],
        "idempotent_replay": replay,
        **_capability(
            capability_state=plan.capability_label,
            source_of_truth=plan.source_of_truth,
            allowed_actions=["execute", "cancel", "retry"]
            if plan.status in {"READY", "FAILED", "BLOCKED", "PENDING_REVIEW"}
            else ["view"],
        ),
    }


def create_session(
    db: Session,
    user: User,
    *,
    page_path: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if idempotency_key:
        existing = db.scalar(
            select(AssistantSession).where(
                AssistantSession.user_id == user.user_id,
                AssistantSession.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return _session_payload(existing, user, replay=True)
    session = AssistantSession(
        user_id=user.user_id,
        org_id=user.org_id,
        page_path=page_path,
        entity_type=entity_type,
        entity_id=entity_id,
        status="ACTIVE",
        state_version=1,
        idempotency_key=idempotency_key,
    )
    db.add(session)
    db.commit()
    return _session_payload(session, user)


def resume_session(
    db: Session,
    session_id: str,
    user: User,
    *,
    if_match: str | None,
) -> dict[str, Any]:
    session = _require_session(db, session_id, user)
    if session.status == "ACTIVE":
        return _session_payload(session, user, replay=True)
    _if_match(if_match, session.state_version)
    session.status = "ACTIVE"
    session.state_version += 1
    db.commit()
    return _session_payload(session, user)


def list_messages(db: Session, session_id: str, user: User) -> dict[str, Any]:
    session = _require_session(db, session_id, user)
    rows = db.scalars(
        select(AssistantMessage)
        .where(AssistantMessage.session_id == session.session_id)
        .order_by(AssistantMessage.sequence_no.asc())
    ).all()
    return {
        "session": _session_payload(session, user),
        "items": [_message_payload(item) for item in rows],
        "total": len(rows),
        **_capability(source_of_truth="assistant_messages", allowed_actions=["view"]),
    }


def list_plans(db: Session, session_id: str, user: User) -> dict[str, Any]:
    session = _require_session(db, session_id, user)
    rows = db.scalars(
        select(AssistantPlan)
        .where(AssistantPlan.session_id == session.session_id)
        .order_by(AssistantPlan.created_at.desc())
    ).all()
    return {
        "session": _session_payload(session, user),
        "items": [_plan_payload(db, item) for item in rows],
        "total": len(rows),
        **_capability(source_of_truth="assistant_plans/assistant_plan_steps", allowed_actions=["view"]),
    }


def _target_from_text(session: AssistantSession, content: str) -> str | None:
    if session.entity_id:
        return session.entity_id
    match = re.search(r"\b[A-Za-z][A-Za-z0-9:_-]{3,95}\b", content)
    return match.group(0) if match else None


def _plan_intent(session: AssistantSession, content: str) -> tuple[str, str, str, str | None]:
    normalized = content.strip().lower()
    target_id = _target_from_text(session, content)
    if any(token in normalized for token in ("资产完整", "资产校验", "asset integrity", "asset passport")):
        return "CHECK_ASSET_INTEGRITY", "READ", "检查资产护照、版本、质量与哈希引用，不读取原始数据。", target_id
    if any(token in normalized for token in ("授权申请状态", "授权申请", "access request", "authorization status")) and not any(
        token in normalized for token in ("提交", "批准", "拒绝", "撤销", "approve", "submit", "revoke")
    ):
        return "QUERY_AUTHORIZATION_STATUS", "READ", "查询当前主体可见的授权申请状态与合同引用。", target_id
    if any(token in normalized for token in ("ttc", "任务状态", "任务进度", "transaction capsule")):
        return "CHECK_TTC_STATUS", "READ", "读取真实 TTC 状态、当前 Attempt、快照与转移计数。", target_id
    if any(token in normalized for token in ("证据摘要", "核验证据", "证据核验", "evidence summary", "verify evidence")):
        return "VERIFY_EVIDENCE_SUMMARY", "READ", "核验可见证据摘要与本地账本哈希，不写入业务状态。", target_id
    if any(token in normalized for token in ("审计解释", "解释审计", "审计报告说明", "audit explanation")):
        return "EXPLAIN_AUDIT", "READ", "基于审计日志、报告、TTC 转移和证据计数生成确定性解释。", target_id
    if any(token in normalized for token in ("提交申请", "submit request", "submit access")):
        return "SUBMIT_USAGE_REQUEST", "WRITE", "创建待人工审核的使用申请控制请求，不直接提交业务申请。", target_id
    if any(token in normalized for token in ("批准授权", "approve authorization", "批准申请")):
        return "APPROVE_USAGE_REQUEST", "WRITE", "创建待人工审核的授权审批控制请求，不直接改变授权状态。", target_id
    if any(token in normalized for token in ("拒绝授权", "reject authorization", "拒绝申请")):
        return "REJECT_USAGE_REQUEST", "WRITE", "创建待人工审核的授权拒绝控制请求，不直接改变授权状态。", target_id
    if any(token in normalized for token in ("撤销授权", "revoke authorization")):
        return "REVOKE_USAGE_AUTHORIZATION", "WRITE", "创建待人工审核的授权撤销控制请求，不直接撤销授权。", target_id
    if any(token in normalized for token in ("推进状态", "advance ttc", "推进 ttc", "推进任务")):
        return "ADVANCE_TTC_STATE", "WRITE", "创建待人工审核的 TTC 状态推进控制请求，不直接推进状态机。", target_id
    return "UNKNOWN_INTENT", "BLOCKED", "该意图不在助手 allowlist 中，需要明确的受支持查询或人工动作。", target_id


def _tool_available(db: Session, action_code: str) -> AgentTool | None:
    tool_code = ACTION_TOOL_CODES.get(action_code)
    if not tool_code:
        return None
    return db.scalar(
        select(AgentTool).where(AgentTool.tool_code == tool_code, AgentTool.enabled.is_(True))
    )


def post_message(
    db: Session,
    session_id: str,
    user: User,
    *,
    content: str,
    if_match: str | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    session = _require_session(db, session_id, user)
    if session.status != "ACTIVE":
        raise ValueError("ASSISTANT_SESSION_NOT_ACTIVE")
    _if_match(if_match, session.state_version)
    if idempotency_key:
        existing = db.scalar(
            select(AssistantMessage).where(
                AssistantMessage.session_id == session_id,
                AssistantMessage.role == "USER",
                AssistantMessage.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            plan = db.get(AssistantPlan, existing.plan_id) if existing.plan_id else None
            assistant = db.scalar(
                select(AssistantMessage).where(
                    AssistantMessage.session_id == session_id,
                    AssistantMessage.plan_id == existing.plan_id,
                    AssistantMessage.role == "ASSISTANT",
                )
            )
            return {
                "message": _message_payload(existing, replay=True),
                "assistant_message": _message_payload(assistant, replay=True) if assistant else None,
                "plan": _plan_payload(db, plan, replay=True) if plan else None,
                "session": _session_payload(session, user, replay=True),
            }
    action_code, mode, explanation, target_id = _plan_intent(session, content)
    if action_code != "UNKNOWN_INTENT" and user.role_code not in ACTION_ROLES.get(action_code, frozenset()):
        mode = "BLOCKED"
        explanation = "当前角色没有执行该助手意图的权限；未创建业务写操作。"
    tool = _tool_available(db, action_code)
    if mode == "READ" and tool is None:
        mode = "BLOCKED"
        explanation = "对应真实 Agent Tool 尚未登记或已禁用；未执行查询。"
    if mode == "READ":
        plan_status = "READY"
        step_status = "READY"
    elif mode == "WRITE":
        plan_status = "PENDING_REVIEW"
        step_status = "PENDING_REVIEW"
    else:
        plan_status = "BLOCKED"
        step_status = "BLOCKED"
    latest_sequence = int(
        db.scalar(
            select(func.max(AssistantMessage.sequence_no)).where(
                AssistantMessage.session_id == session_id
            )
        )
        or 0
    )
    user_message = AssistantMessage(
        session_id=session_id,
        sequence_no=latest_sequence + 1,
        role="USER",
        content=content.strip(),
        intent_code=action_code,
        status="RECORDED",
        idempotency_key=idempotency_key,
    )
    db.add(user_message)
    db.flush()
    request_id = f"assistant-review-{user_message.message_id}" if mode == "WRITE" else None
    plan = AssistantPlan(
        session_id=session_id,
        trigger_message_id=user_message.message_id,
        intent_code=action_code,
        status=plan_status,
        state_version=1,
        plan_json={
            "planner": "LOCAL_REAL_DETERMINISTIC",
            "intent_code": action_code,
            "mode": mode,
            "target_id": target_id,
            "explanation": explanation,
            "raw_data_accessed": False,
        },
        plan_hash=sha256_json(
            {
                "intent_code": action_code,
                "mode": mode,
                "target_id": target_id,
                "explanation": explanation,
            }
        ),
        capability_label="LOCAL_REAL_DETERMINISTIC" if mode == "READ" else "BLOCKED" if mode == "BLOCKED" else "PENDING_REVIEW",
        source_of_truth="assistant_planner/role_capabilities/agent_tools",
        idempotency_key=idempotency_key,
    )
    db.add(plan)
    db.flush()
    user_message.plan_id = plan.plan_id
    step = AssistantPlanStep(
        plan_id=plan.plan_id,
        sequence_no=1,
        action_code=action_code,
        tool_code=tool.tool_code if tool else ACTION_TOOL_CODES.get(action_code),
        target_type=session.entity_type,
        target_id=target_id,
        mode=mode,
        status=step_status,
        state_version=1,
        request_id=request_id,
        input_json={"page_path": session.page_path, "entity_type": session.entity_type, "target_id": target_id},
        output_json={},
        capability_label="LOCAL_REAL_DETERMINISTIC" if mode == "READ" else "BLOCKED" if mode == "BLOCKED" else "PENDING_REVIEW",
        source_of_truth="agent_tools/assistant_planner",
        idempotency_key=idempotency_key,
    )
    db.add(step)
    assistant_message = AssistantMessage(
        session_id=session_id,
        plan_id=plan.plan_id,
        sequence_no=latest_sequence + 2,
        role="ASSISTANT",
        content=explanation,
        intent_code=action_code,
        status="RECORDED",
        capability_label="LOCAL_REAL_DETERMINISTIC" if mode == "READ" else "BLOCKED" if mode == "BLOCKED" else "PENDING_REVIEW",
        source_of_truth="assistant_planner",
    )
    db.add(assistant_message)
    session.state_version += 1
    session.last_message_at = assistant_message.created_at
    add_audit_log(
        db,
        action="ASSISTANT_MESSAGE_PLANNED",
        target_type="ASSISTANT_SESSION",
        target_id=session.session_id,
        result=plan_status,
        user=user,
        details={
            "message_id": user_message.message_id,
            "plan_id": plan.plan_id,
            "intent_code": action_code,
            "mode": mode,
            "raw_data_accessed": False,
        },
    )
    db.commit()
    return {
        "message": _message_payload(user_message),
        "assistant_message": _message_payload(assistant_message),
        "plan": _plan_payload(db, plan),
        "session": _session_payload(session, user),
    }


def tool_catalog(db: Session, user: User) -> dict[str, Any]:
    tools = db.scalars(
        select(AgentTool).where(AgentTool.enabled.is_(True)).order_by(AgentTool.tool_code.asc())
    ).all()
    items: list[dict[str, Any]] = []
    for tool in tools:
        actions = [
            action
            for action, code in ACTION_TOOL_CODES.items()
            if code == tool.tool_code and user.role_code in ACTION_ROLES.get(action, frozenset())
        ]
        if not actions and user.role_code not in OVERSIGHT_ROLES and tool.tool_code not in {
            "WorkflowEngine",
            "EDCAdapter+OPAAdapter",
            "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine",
        }:
            continue
        items.append(
            {
                "tool_code": tool.tool_code,
                "tool_name": tool.tool_name,
                "service_code": tool.service_code,
                "assistant_actions": actions,
                "enabled": tool.enabled,
                **_capability(
                    capability_state=tool.capability_label,
                    source_of_truth="agent_tools",
                    allowed_actions=["execute_read"] if actions else ["view"],
                ),
            }
        )
    return {
        "items": items,
        "total": len(items),
        **_capability(source_of_truth="agent_tools/role_capabilities", allowed_actions=["view"]),
    }


def _asset_read(db: Session, user: User, target_id: str | None) -> dict[str, Any]:
    if not target_id:
        return {"status": "BLOCKED", "error_code": "TARGET_ASSET_REQUIRED", "raw_data_accessed": False}
    asset = db.get(DataAsset, target_id)
    if asset is None:
        return {"status": "BLOCKED", "error_code": "ASSET_NOT_FOUND", "raw_data_accessed": False}
    if user.role_code in {"GENERATOR", "RETAILER"} and asset.owner_org_id != user.org_id:
        return {"status": "BLOCKED", "error_code": "ASSET_SCOPE_DENIED", "raw_data_accessed": False}
    version = db.scalar(
        select(DataAssetVersion)
        .where(DataAssetVersion.asset_id == asset.asset_id)
        .order_by(DataAssetVersion.version_no.desc())
    )
    passport = db.scalar(
        select(DataAssetPassport)
        .where(DataAssetPassport.asset_version_id == (version.version_id if version else "__none__"))
        .order_by(DataAssetPassport.passport_version.desc())
    )
    quality = db.scalar(
        select(AssetQuality)
        .where(AssetQuality.asset_version_id == (version.version_id if version else "__none__"))
        .order_by(AssetQuality.evaluated_at.desc())
    )
    return {
        "status": "SUCCEEDED",
        "asset_id": asset.asset_id,
        "asset_name": asset.asset_name,
        "asset_status": asset.status,
        "version": {
            "version_id": version.version_id,
            "version_no": version.version_no,
            "data_hash": version.data_hash,
            "immutable_hash": version.immutable_hash,
            "status": version.status,
        }
        if version
        else None,
        "passport": {
            "passport_id": passport.passport_id,
            "passport_hash": passport.passport_hash,
            "status": passport.status,
        }
        if passport
        else None,
        "quality": {
            "quality_id": quality.quality_id,
            "quality_hash": quality.quality_hash,
            "decision": quality.decision,
        }
        if quality
        else None,
        "integrity": {
            "version_present": version is not None,
            "passport_present": passport is not None,
            "quality_present": quality is not None,
            "raw_data_accessed": False,
        },
        "raw_data_accessed": False,
    }


def _request_read(db: Session, user: User, target_id: str | None) -> dict[str, Any]:
    if not target_id:
        return {"status": "BLOCKED", "error_code": "TARGET_REQUEST_REQUIRED", "raw_data_accessed": False}
    request = db.get(DataUsageRequest, target_id)
    if request is None:
        return {"status": "BLOCKED", "error_code": "REQUEST_NOT_FOUND", "raw_data_accessed": False}
    if user.role_code not in OVERSIGHT_ROLES and user.role_code != "EXCHANGE" and user.org_id not in {
        request.applicant_org_id,
        request.provider_org_id,
    }:
        return {"status": "BLOCKED", "error_code": "REQUEST_SCOPE_DENIED", "raw_data_accessed": False}
    return {
        "status": "SUCCEEDED",
        "request_id": request.request_id,
        "status_value": request.status,
        "asset_id": request.asset_id,
        "applicant_org_id": request.applicant_org_id,
        "provider_org_id": request.provider_org_id,
        "contract_id": request.contract_id,
        "agreement_id": request.agreement_id,
        "state_version": request.state_version,
        "raw_data_accessed": False,
    }


def _task_read(db: Session, user: User, target_id: str | None) -> dict[str, Any]:
    if not target_id:
        return {"status": "BLOCKED", "error_code": "TARGET_TASK_REQUIRED", "raw_data_accessed": False}
    task = db.get(SettlementTask, target_id)
    if task is None:
        return {"status": "BLOCKED", "error_code": "TTC_TASK_NOT_FOUND", "raw_data_accessed": False}
    if user.role_code not in OVERSIGHT_ROLES and user.role_code != "EXCHANGE":
        participant = db.scalar(
            select(TaskParticipant.participant_id).where(
                TaskParticipant.task_id == task.task_id,
                TaskParticipant.org_id == user.org_id,
            )
        )
        if participant is None:
            return {"status": "BLOCKED", "error_code": "TTC_SCOPE_DENIED", "raw_data_accessed": False}
    attempt = db.scalar(
        select(TtcAttempt)
        .where(TtcAttempt.task_id == task.task_id)
        .order_by(TtcAttempt.attempt_no.desc())
    )
    transition_count = int(
        db.scalar(
            select(func.count(TtcStateTransition.transition_id)).where(
                TtcStateTransition.task_id == task.task_id
            )
        )
        or 0
    )
    return {
        "status": "SUCCEEDED",
        "task_id": task.task_id,
        "task_name": task.task_name,
        "ttc_state": task.ttc_state,
        "status_value": task.status,
        "current_attempt": task.current_attempt,
        "attempt_id": attempt.attempt_id if attempt else None,
        "snapshot_id": task.execution_snapshot_id,
        "transition_count": transition_count,
        "raw_data_accessed": False,
    }


def _evidence_read(db: Session, user: User, target_id: str | None) -> dict[str, Any]:
    if not target_id:
        return {"status": "BLOCKED", "error_code": "TARGET_EVIDENCE_OR_TASK_REQUIRED", "raw_data_accessed": False}
    evidence = db.get(BlockchainEvidence, target_id)
    if evidence is None:
        task = db.get(SettlementTask, target_id)
        if task is None:
            return {"status": "BLOCKED", "error_code": "EVIDENCE_NOT_FOUND", "raw_data_accessed": False}
        rows = db.scalars(
            select(BlockchainEvidence)
            .where(BlockchainEvidence.task_id == task.task_id)
            .order_by(BlockchainEvidence.created_at.asc())
        ).all()
    else:
        rows = [evidence]
        task = db.get(SettlementTask, evidence.task_id) if evidence.task_id else None
    if task is None:
        return {"status": "BLOCKED", "error_code": "EVIDENCE_TASK_NOT_FOUND", "raw_data_accessed": False}
    task_result = _task_read(db, user, task.task_id)
    if task_result.get("status") != "SUCCEEDED":
        return {"status": "BLOCKED", "error_code": "EVIDENCE_SCOPE_DENIED", "raw_data_accessed": False}
    return {
        "status": "SUCCEEDED",
        "task_id": task.task_id,
        "items": [
            {
                "evidence_id": item.evidence_id,
                "stage": item.stage,
                "biz_type": item.biz_type,
                "biz_id": item.biz_id,
                "evidence_hash": item.evidence_hash,
                "verify": LocalEvidenceLedgerAdapter.verify(item),
                "chain_code": item.chain_code,
                "status": item.status,
            }
            for item in rows
        ],
        "raw_data_accessed": False,
    }


def _audit_read(db: Session, user: User, target_id: str | None) -> dict[str, Any]:
    if user.role_code not in OVERSIGHT_ROLES:
        return {"status": "BLOCKED", "error_code": "AUDIT_SCOPE_DENIED", "raw_data_accessed": False}
    if not target_id:
        return {"status": "BLOCKED", "error_code": "TARGET_TASK_REQUIRED", "raw_data_accessed": False}
    task = db.get(SettlementTask, target_id)
    if task is None:
        return {"status": "BLOCKED", "error_code": "TTC_TASK_NOT_FOUND", "raw_data_accessed": False}
    log_count = int(
        db.scalar(select(func.count(AuditLog.log_id)).where(AuditLog.target_id == task.task_id)) or 0
    )
    report_count = int(
        db.scalar(select(func.count(AuditReport.report_id)).where(AuditReport.task_id == task.task_id)) or 0
    )
    evidence_count = int(
        db.scalar(select(func.count(BlockchainEvidence.evidence_id)).where(BlockchainEvidence.task_id == task.task_id)) or 0
    )
    return {
        "status": "SUCCEEDED",
        "task_id": task.task_id,
        "ttc_state": task.ttc_state,
        "audit_log_count": log_count,
        "report_count": report_count,
        "evidence_count": evidence_count,
        "explanation": (
            f"任务当前处于 {task.ttc_state}，已记录 {log_count} 条审计日志、"
            f"{report_count} 份报告和 {evidence_count} 条证据；助手未读取原始业务数据。"
        ),
        "raw_data_accessed": False,
    }


def _run_read_action(db: Session, user: User, action_code: str, target_id: str | None) -> dict[str, Any]:
    if action_code == "CHECK_ASSET_INTEGRITY":
        return _asset_read(db, user, target_id)
    if action_code == "QUERY_AUTHORIZATION_STATUS":
        return _request_read(db, user, target_id)
    if action_code == "CHECK_TTC_STATUS":
        return _task_read(db, user, target_id)
    if action_code == "VERIFY_EVIDENCE_SUMMARY":
        return _evidence_read(db, user, target_id)
    if action_code == "EXPLAIN_AUDIT":
        return _audit_read(db, user, target_id)
    return {"status": "BLOCKED", "error_code": "UNKNOWN_ASSISTANT_ACTION", "raw_data_accessed": False}


def execute_plan(
    db: Session,
    session_id: str,
    plan_id: str,
    user: User,
    *,
    step_id: str | None,
    if_match: str | None,
) -> dict[str, Any]:
    session = _require_session(db, session_id, user)
    plan = db.get(AssistantPlan, plan_id)
    if plan is None or plan.session_id != session.session_id:
        raise LookupError("ASSISTANT_PLAN_NOT_FOUND")
    _if_match(if_match, plan.state_version)
    query = select(AssistantPlanStep).where(AssistantPlanStep.plan_id == plan.plan_id)
    if step_id:
        query = query.where(AssistantPlanStep.step_id == step_id)
    step = db.scalar(query.order_by(AssistantPlanStep.sequence_no.asc()))
    if step is None:
        raise LookupError("ASSISTANT_STEP_NOT_FOUND")
    if step.status in {"SUCCEEDED", "CANCELLED"}:
        return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan, replay=True)}
    if step.status == "PENDING_REVIEW" and step.mode == "WRITE":
        # A write intent is never executed by the assistant.  The first
        # explicit execution call records a durable review request envelope;
        # repeats replay it without creating a second request or business row.
        if step.output_json.get("review_requested"):
            return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan, replay=True)}
        step.output_json = {
            "status": "PENDING_REVIEW",
            "request_id": step.request_id,
            "review_requested": True,
            "business_mutation": False,
        }
        step.state_version += 1
        plan.state_version += 1
        add_audit_log(
            db,
            action="ASSISTANT_WRITE_REVIEW_REQUESTED",
            target_type="ASSISTANT_PLAN_STEP",
            target_id=step.step_id,
            result="PENDING_REVIEW",
            user=user,
            details={
                "request_id": step.request_id,
                "action_code": step.action_code,
                "business_mutation": False,
                "policy": "human_review_required",
            },
        )
        db.commit()
        return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan)}
    if step.status == "BLOCKED":
        return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan, replay=True)}
    invocation_id = f"assistant-invocation-{step.step_id}"
    output = _run_read_action(db, user, step.action_code, step.target_id)
    step.invocation_id = invocation_id
    step.output_json = output
    step.state_version += 1
    step.status = "SUCCEEDED" if output.get("status") == "SUCCEEDED" else "BLOCKED"
    step.error_code = output.get("error_code")
    plan.status = step.status
    plan.state_version += 1
    add_audit_log(
        db,
        action="ASSISTANT_TOOL_INVOKE",
        target_type="ASSISTANT_PLAN_STEP",
        target_id=step.step_id,
        result=step.status,
        user=user,
        details={
            "invocation_id": invocation_id,
            "action_code": step.action_code,
            "tool_code": step.tool_code,
            "source_of_truth": step.source_of_truth,
            "raw_data_accessed": False,
        },
    )
    db.commit()
    return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan)}


def cancel_plan(
    db: Session,
    session_id: str,
    plan_id: str,
    user: User,
    *,
    if_match: str | None,
) -> dict[str, Any]:
    session = _require_session(db, session_id, user)
    plan = db.get(AssistantPlan, plan_id)
    if plan is None or plan.session_id != session.session_id:
        raise LookupError("ASSISTANT_PLAN_NOT_FOUND")
    if plan.status == "CANCELLED":
        return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan, replay=True)}
    _if_match(if_match, plan.state_version)
    if plan.status == "SUCCEEDED":
        raise ValueError("ASSISTANT_PLAN_ALREADY_SUCCEEDED")
    plan.status = "CANCELLED"
    plan.state_version += 1
    steps = db.scalars(select(AssistantPlanStep).where(AssistantPlanStep.plan_id == plan.plan_id)).all()
    for step in steps:
        if step.status in {"READY", "PENDING_REVIEW", "BLOCKED", "FAILED"}:
            step.status = "CANCELLED"
            step.state_version += 1
    add_audit_log(
        db,
        action="ASSISTANT_PLAN_CANCEL",
        target_type="ASSISTANT_PLAN",
        target_id=plan.plan_id,
        result="CANCELLED",
        user=user,
        details={"business_mutation": False},
    )
    db.commit()
    return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan)}


def retry_plan(
    db: Session,
    session_id: str,
    plan_id: str,
    user: User,
    *,
    if_match: str | None,
) -> dict[str, Any]:
    session = _require_session(db, session_id, user)
    plan = db.get(AssistantPlan, plan_id)
    if plan is None or plan.session_id != session.session_id:
        raise LookupError("ASSISTANT_PLAN_NOT_FOUND")
    _if_match(if_match, plan.state_version)
    if plan.status not in {"FAILED", "BLOCKED"}:
        raise ValueError("ASSISTANT_PLAN_NOT_RETRYABLE")
    plan.status = "READY"
    plan.state_version += 1
    steps = db.scalars(select(AssistantPlanStep).where(AssistantPlanStep.plan_id == plan.plan_id)).all()
    for step in steps:
        if step.status in {"BLOCKED", "FAILED"}:
            step.status = "READY"
            step.error_code = None
            step.output_json = {}
            step.state_version += 1
    add_audit_log(
        db,
        action="ASSISTANT_PLAN_RETRY",
        target_type="ASSISTANT_PLAN",
        target_id=plan.plan_id,
        result="READY",
        user=user,
        details={"business_mutation": False},
    )
    db.commit()
    return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan)}


def plan_status(db: Session, session_id: str, plan_id: str, user: User) -> dict[str, Any]:
    session = _require_session(db, session_id, user)
    plan = db.get(AssistantPlan, plan_id)
    if plan is None or plan.session_id != session.session_id:
        raise LookupError("ASSISTANT_PLAN_NOT_FOUND")
    return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan)}
