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
    User,
)
from ..security import sha256_json
from ..services.common import add_audit_log
from .assistant_language import DESCRIPTIONS, understand
from . import assistant_catalog
from ..trust_models import AgentTool


ENTERPRISE_ASSISTANT_ROLES = frozenset({"GENERATOR", "RETAILER", "COAL_ENTERPRISE", "HEAT_ENTERPRISE", "GAS_ENTERPRISE", "OIL_ENTERPRISE"})
ALL_ASSISTANT_ROLES = ENTERPRISE_ASSISTANT_ROLES | frozenset({"EXCHANGE", "REGULATOR"})
OVERSIGHT_ROLES = frozenset({"EXCHANGE", "REGULATOR"})

ACTION_ROLES: dict[str, frozenset[str]] = {
    "LIST_DATA_ASSETS": ALL_ASSISTANT_ROLES,
    "CHECK_ASSET_INTEGRITY": ALL_ASSISTANT_ROLES,
    "QUERY_AUTHORIZATION_STATUS": ALL_ASSISTANT_ROLES,
    "CHECK_TTC_STATUS": ALL_ASSISTANT_ROLES,
    "VERIFY_EVIDENCE_SUMMARY": OVERSIGHT_ROLES,
    "EXPLAIN_AUDIT": OVERSIGHT_ROLES,
    "SUBMIT_USAGE_REQUEST": ALL_ASSISTANT_ROLES,
    "APPROVE_USAGE_REQUEST": ENTERPRISE_ASSISTANT_ROLES | frozenset({"EXCHANGE"}),
    "REJECT_USAGE_REQUEST": ENTERPRISE_ASSISTANT_ROLES | frozenset({"EXCHANGE"}),
    "REVOKE_USAGE_AUTHORIZATION": ALL_ASSISTANT_ROLES,
    "ADVANCE_TTC_STATE": OVERSIGHT_ROLES,
}

LIST_ACTIONS = frozenset({"LIST_DATA_ASSETS", "LIST_VISIBLE_DATA_ASSETS", "LIST_AUTHORIZED_DATA_ASSETS", "LIST_AUTHORIZATIONS", "LIST_TASKS", "LIST_AUDIT_REPORTS", "LIST_NOTIFICATIONS", "SYSTEM_OVERVIEW"})
LOCAL_ACTIONS = frozenset({"ASSISTANT_HELP", "NAVIGATE_QUERY", "NAVIGATE_ELECTRICITY"})
for action in LIST_ACTIONS - {"SYSTEM_OVERVIEW", "LIST_AUDIT_REPORTS"}:
    ACTION_ROLES[action] = ALL_ASSISTANT_ROLES
ACTION_ROLES["LIST_AUDIT_REPORTS"] = frozenset({"REGULATOR"})
ACTION_ROLES["SYSTEM_OVERVIEW"] = frozenset({"ADMIN"})
ACTION_ROLES["ASSISTANT_HELP"] = ALL_ASSISTANT_ROLES | frozenset({"ADMIN"})
ACTION_ROLES["NAVIGATE_QUERY"] = ACTION_ROLES["NAVIGATE_ELECTRICITY"] = ALL_ASSISTANT_ROLES


ACTION_TOOL_CODES: dict[str, str] = {
    "LIST_DATA_ASSETS": "EDCAdapter+OPAAdapter",
    "CHECK_ASSET_INTEGRITY": "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine",
    "QUERY_AUTHORIZATION_STATUS": "EDCAdapter+OPAAdapter",
    "CHECK_TTC_STATUS": "WorkflowEngine",
    "VERIFY_EVIDENCE_SUMMARY": "EvidenceGraph+LocalEvidenceLedger+RiskRuleEngine",
    "EXPLAIN_AUDIT": "TemplateAuditFallback",
}

for action in LIST_ACTIONS | LOCAL_ACTIONS:
    ACTION_TOOL_CODES.setdefault(action, "EDCAdapter+OPAAdapter" if "DATA_ASSETS" in action or action == "LIST_AUTHORIZATIONS" else "WorkflowEngine")


READ_ACTIONS = frozenset(
    {
        "LIST_DATA_ASSETS",
        "CHECK_ASSET_INTEGRITY",
        "QUERY_AUTHORIZATION_STATUS",
        "CHECK_TTC_STATUS",
        "VERIFY_EVIDENCE_SUMMARY",
        "EXPLAIN_AUDIT",
    }
)
READ_ACTIONS = READ_ACTIONS | LIST_ACTIONS | LOCAL_ACTIONS
WRITE_ACTIONS = frozenset(set(ACTION_ROLES) - set(READ_ACTIONS))

ACTION_TARGET_TYPES = {
    "LIST_DATA_ASSETS": ("organization",),
    "CHECK_ASSET_INTEGRITY": ("data_asset",),
    "QUERY_AUTHORIZATION_STATUS": ("data_usage_request",),
    "CHECK_TTC_STATUS": ("settlement_task", "privacy_compute_job"),
    "VERIFY_EVIDENCE_SUMMARY": ("settlement_task", "blockchain_evidence", "privacy_compute_job"),
    "EXPLAIN_AUDIT": ("settlement_task", "audit_report", "privacy_compute_job"),
    "SUBMIT_USAGE_REQUEST": ("data_asset",),
    "APPROVE_USAGE_REQUEST": ("data_usage_request",),
    "REJECT_USAGE_REQUEST": ("data_usage_request",),
    "REVOKE_USAGE_AUTHORIZATION": ("data_usage_request",),
    "ADVANCE_TTC_STATE": ("settlement_task", "privacy_compute_job"),
}
for action in LIST_ACTIONS | LOCAL_ACTIONS:
    ACTION_TARGET_TYPES[action] = ("organization",)

TARGET_GUIDANCE = {
    "organization": "请使用当前账号查询本方数据目录。",
    "data_asset": "请先打开数据资产详情，或在指令中填写资产编号。",
    "data_usage_request": "请先选择一条授权申请，或在指令中填写申请编号。",
    "settlement_task": "请先打开对应任务详情，或在指令中填写任务编号。",
}


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
                ["execute", "cancel"] if step.status in {"READY", "PENDING_REVIEW"}
                else ["cancel"] if step.status in {"FAILED", "BLOCKED"} else ["view"]
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
            allowed_actions=["execute", "cancel"] if plan.status in {"READY", "PENDING_REVIEW"}
            else (["cancel"] if any(item.action_code not in ACTION_ROLES or item.error_code in {"ASSISTANT_ROLE_DENIED", "ASSISTANT_CATALOG_SCOPE_DENIED"} or _target_error(item.action_code, item.target_type, item.target_id) for item in steps) else ["cancel", "retry"])
            if plan.status in {"FAILED", "BLOCKED"} else ["cancel"] if plan.status == "NEEDS_INPUT" else ["view"],
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


def _explicit_target(content: str) -> str | None:
    # Ordinary English command words are not identifiers. Accept a complete
    # UUID or a declared/prefixed business identifier, never a partial UUID.
    match = re.search(r"(?<![\w-])(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|(?:asset|request|task|job|report|evidence)[-_:][A-Za-z0-9:_-]{1,90})(?![\w-])", content)
    if match:
        return match.group(0)
    match = re.search(r"(?:资产|申请|任务|报告|证据)(?:编号|[Ii][Dd])\s*[:：=]?\s*([A-Za-z0-9:_-]{3,96})(?![\w-])", content)
    return match.group(1) if match else None


def _target_from_text(session: AssistantSession, content: str) -> str | None:
    return _explicit_target(content) or session.entity_id


def _target_type(action_code: str, session: AssistantSession, content: str) -> str | None:
    allowed = ACTION_TARGET_TYPES.get(action_code, ())
    explicit = _explicit_target(content)
    if not explicit:
        return session.entity_type
    prefixes = {"asset": "data_asset", "request": "data_usage_request", "task": "settlement_task", "job": "privacy_compute_job", "report": "audit_report", "evidence": "blockchain_evidence"}
    for prefix, kind in prefixes.items():
        if explicit.startswith((prefix + "-", prefix + "_", prefix + ":")):
            return kind
    # An explicit UUID is interpreted only in the requested action's declared
    # type, preserving a compatible typed page context when there is one.
    return session.entity_type if session.entity_type in allowed else allowed[0] if allowed else None


def _target_error(action_code: str, target_type: str | None, target_id: str | None) -> tuple[str, str] | None:
    allowed = ACTION_TARGET_TYPES.get(action_code)
    if not allowed:
        return None
    guidance = TARGET_GUIDANCE.get(allowed[0], "请先选择该指令对应的业务对象。")
    if not target_id:
        return "ASSISTANT_TARGET_REQUIRED", guidance
    if target_type not in allowed:
        return "ASSISTANT_TARGET_TYPE_MISMATCH", "当前页面的对象不能用于这条指令。" + guidance
    return None


def _execution_error(db: Session, user: User, step: AssistantPlanStep) -> tuple[str, str] | None:
    if step.action_code not in ACTION_ROLES:
        return "UNKNOWN_ASSISTANT_ACTION", "还没识别出要查询的内容。可以试试“我有哪些数据”或下方常用指令。"
    if step.action_code in ACTION_ROLES and user.role_code not in ACTION_ROLES[step.action_code]:
        return "ASSISTANT_ROLE_DENIED", "当前角色没有执行该助手指令的权限。"
    if step.action_code in LIST_ACTIONS | LOCAL_ACTIONS and step.target_id != user.org_id:
        return "ASSISTANT_CATALOG_SCOPE_DENIED", "数据目录查询只能使用当前账号的主体范围。"
    invalid_target = _target_error(step.action_code, step.target_type, step.target_id)
    if invalid_target:
        return invalid_target
    if step.action_code in READ_ACTIONS and step.action_code != "ASSISTANT_HELP" and _tool_available(db, step.action_code) is None:
        return "ASSISTANT_TOOL_UNAVAILABLE", "该指令对应的工具当前不可用。"
    if step.action_code not in LOCAL_ACTIONS:
        return assistant_catalog.validate_target(db, user, step.action_code, step.target_type, step.target_id)
    return None


def _resolve_language(db: Session, session: AssistantSession, user: User, content: str) -> dict[str, Any]:
    previous = db.scalar(select(AssistantPlan).where(AssistantPlan.session_id == session.session_id).order_by(AssistantPlan.created_at.desc(), AssistantPlan.plan_id.desc()))
    prior = previous.plan_json if previous else {}
    previous_action = prior.get("pending_action") or (previous.intent_code if previous else None)
    detail_actions = {"LIST_DATA_ASSETS": "CHECK_ASSET_INTEGRITY", "LIST_VISIBLE_DATA_ASSETS": "CHECK_ASSET_INTEGRITY", "LIST_AUTHORIZED_DATA_ASSETS": "CHECK_ASSET_INTEGRITY", "LIST_AUTHORIZATIONS": "QUERY_AUTHORIZATION_STATUS", "LIST_TASKS": "CHECK_TTC_STATUS", "LIST_AUDIT_REPORTS": "EXPLAIN_AUDIT"}
    previous_action = detail_actions.get(previous_action, previous_action)
    old_candidates = prior.get("candidates", [])
    if previous and not old_candidates:
        old_step = db.scalar(select(AssistantPlanStep).where(AssistantPlanStep.plan_id == previous.plan_id).order_by(AssistantPlanStep.sequence_no))
        old_candidates = (old_step.output_json or {}).get("items", []) if old_step else []
    history = db.scalars(select(AssistantMessage.content).where(AssistantMessage.session_id == session.session_id, AssistantMessage.role == "USER").order_by(AssistantMessage.sequence_no.desc()).limit(4)).all()
    # Exact labels can only refer to the immediately preceding scoped result.
    exact_names = [item for item in old_candidates if item.get("label") == content.strip()]
    if exact_names and previous_action:
        language = {"action": previous_action, "source": "LOCAL", "model_used": False, "search": content.strip(), "effective_text": content.strip(), "reference": True, "clarify": len(exact_names) > 1,
                    "selection": old_candidates.index(exact_names[0]) + 1 if len(exact_names) == 1 else None,
                    "selection_rule": "PREVIOUS_SCOPED_CANDIDATE", "message": "同名对象不止一项，请回复序号选择。"}
    else:
        language = understand(content, available_actions=sorted(action for action, roles in ACTION_ROLES.items() if user.role_code in roles), previous_action=previous_action, entity_type=session.entity_type, history=list(reversed(history)))
    action = language["action"]
    result = {"action": action, "mode": "READ" if action in READ_ACTIONS else "WRITE" if action in WRITE_ACTIONS else "NEEDS_INPUT", "explanation": DESCRIPTIONS.get(action, "请选择要查询的内容。"), "target_type": None, "target_id": None, "error_code": None, "candidates": [], "understanding": {k: v for k, v in language.items() if k not in {"effective_text", "search"}}}
    if user.role_code not in ACTION_ROLES.get(action, frozenset()):
        result.update(mode="BLOCKED", error_code="ASSISTANT_ROLE_DENIED", explanation="当前账号没有执行这项操作的权限。可查询的功能见下方常用指令。")
        if action == "UNKNOWN_INTENT":
            result.update(mode="BLOCKED" if language.get("blocked") else "NEEDS_INPUT", error_code="ASSISTANT_MODEL_UNAVAILABLE" if language.get("source") == "FALLBACK" else "ASSISTANT_INTENT_REQUIRED", explanation=language.get("message") or "还不确定你要查询什么。可以说明数据、授权、任务或系统状态，或选择下方指令。")
        return result
    if language.get("clarify"):
        result.update(mode="BLOCKED" if language.get("blocked") else "NEEDS_INPUT", explanation=language.get("message") or "请确认要执行的查询或复核动作。", error_code="ASSISTANT_INTENT_REQUIRED", candidates=assistant_catalog.target_candidates(db, user, action) if exact_names else [])
        return result
    if action in LIST_ACTIONS | LOCAL_ACTIONS:
        result.update(target_type="organization", target_id=user.org_id)
        return result
    candidates = assistant_catalog.target_candidates(db, user, action, status_filter=language.get("status_filter"))
    effective = language.get("effective_text", content)
    ids = re.findall(r"(?<![\w-])(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|(?:asset|request|task|job|report|evidence)[-_:][A-Za-z0-9:_-]{1,90})(?![\w-])", effective)
    ids.extend(re.findall(r"(?:资产|申请|任务|报告|证据)(?:编号|[Ii][Dd])\s*[:：=]?\s*([A-Za-z0-9:_-]{3,96})(?![\w-])", effective))
    ids = list(dict.fromkeys(ids))
    selected = None
    selection = language.get("selection")
    if selection and 0 < selection <= len(old_candidates):
        choice = old_candidates[selection - 1]
        if choice.get("entity_type") in ACTION_TARGET_TYPES.get(action, ()):
            selected = choice
    if len(ids) == 1:
        target_id = ids[0]
        target_type = _target_type(action, session, effective)
        selected = next((item for item in candidates if item["entity_id"] == target_id), {"entity_id": target_id, "entity_type": target_type})
    elif len(ids) > 1:
        result.update(mode="NEEDS_INPUT", error_code="ASSISTANT_TARGET_REQUIRED", explanation="你提到了多个编号，请先选择本次要查询的一个对象。", candidates=candidates)
        return result
    if selected is None:
        names = [item for item in candidates if item["label"] and item["label"] in effective]
        search = language.get("search")
        if search:
            names = [item for item in candidates if search.casefold() in item["label"].casefold()]
        if len(names) == 1:
            selected = names[0]
    if selected is None and language.get("reference") and previous:
        if prior.get("target_type") in ACTION_TARGET_TYPES.get(action, ()) and prior.get("target_id"):
            selected = {"entity_id": prior["target_id"], "entity_type": prior["target_type"]}
    if selected is None and not selection and not language.get("search") and session.entity_type in ACTION_TARGET_TYPES.get(action, ()) and session.entity_id:
        selected = {"entity_id": session.entity_id, "entity_type": session.entity_type}
    if selected is None:
        result.update(mode="NEEDS_INPUT", error_code="ASSISTANT_TARGET_REQUIRED", explanation="请选择要处理的对象，也可以回复“第一个”“第二个”或完整名称。" if candidates else "当前账号没有可选的对应对象。可以先查看列表或提供可访问的完整编号。", candidates=candidates)
        return result
    result.update(target_type=selected.get("entity_type"), target_id=selected.get("entity_id"))
    error = _target_error(action, result["target_type"], result["target_id"]) or assistant_catalog.validate_target(db, user, action, result["target_type"], result["target_id"])
    if error:
        result.update(mode="BLOCKED", error_code=error[0], explanation=error[1])
    return result


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
    resolved = _resolve_language(db, session, user, content)
    action_code, mode, explanation = resolved["action"], resolved["mode"], resolved["explanation"]
    target_id, target_type, error_code = resolved["target_id"], resolved["target_type"], resolved["error_code"]
    tool = _tool_available(db, action_code)
    if mode == "READ" and action_code != "ASSISTANT_HELP" and tool is None:
        mode, error_code, explanation = "BLOCKED", "ASSISTANT_TOOL_UNAVAILABLE", "该查询工具暂不可用，可以稍后重试。"
    plan_status = step_status = {"READ": "READY", "WRITE": "PENDING_REVIEW", "NEEDS_INPUT": "NEEDS_INPUT"}.get(mode, "BLOCKED")
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
            "planner": "DEEPSEEK_STRUCTURED_INTENT" if resolved["understanding"].get("model_used") else "LOCAL_INTENT_FALLBACK",
            "understanding": resolved["understanding"],
            "pending_action": action_code,
            "candidates": resolved["candidates"],
            "question": content.strip(),
            "intent_code": action_code,
            "mode": mode,
            "target_type": target_type,
            "target_id": target_id,
            "explanation": explanation,
            "raw_data_accessed": False,
        },
        plan_hash=sha256_json(
            {
                "intent_code": action_code,
                "mode": mode,
                "target_type": target_type,
                "target_id": target_id,
                "explanation": explanation,
            }
        ),
        capability_label=("ADAPTER" if resolved["understanding"].get("model_used") else "LOCAL_REAL_DETERMINISTIC") if mode == "READ" else "BLOCKED" if mode == "BLOCKED" else "PENDING_REVIEW",
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
        target_type=target_type,
        target_id=target_id,
        mode=mode,
        status=step_status,
        state_version=1,
        request_id=request_id,
        input_json={"page_path": session.page_path, "entity_type": target_type, "target_id": target_id},
        output_json={},
        error_code=error_code,
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


def _run_read_action(db: Session, user: User, action_code: str, target_id: str | None, target_type: str | None = None, *, question: str = "", status_filter: str | None = None) -> dict[str, Any]:
    if action_code == "ASSISTANT_HELP":
        prompts = {"LIST_DATA_ASSETS": "我有哪些数据", "LIST_VISIBLE_DATA_ASSETS": "查看可见数据", "LIST_AUTHORIZED_DATA_ASSETS": "我能用哪些数据", "LIST_AUTHORIZATIONS": "查看授权列表", "LIST_TASKS": "查看任务列表", "LIST_NOTIFICATIONS": "查看通知", "LIST_AUDIT_REPORTS": "查看审计报告", "SYSTEM_OVERVIEW": "系统运行情况"}
        return {"status": "SUCCEEDED", "help_actions": [{"action_code": action, "label": DESCRIPTIONS[action], "prompt": prompt} for action, prompt in prompts.items() if user.role_code in ACTION_ROLES[action]], "raw_data_accessed": False}
    if action_code in {"NAVIGATE_QUERY", "NAVIGATE_ELECTRICITY"}:
        from urllib.parse import urlencode
        return {"status": "SUCCEEDED", "navigation": {"path": "/trusted-space/query?" + urlencode({"question": question}) if action_code == "NAVIGATE_QUERY" else "#electricity", "question": question}, "raw_data_accessed": False}
    return assistant_catalog.read_action(db, user, action_code, target_id, target_type, status_filter=status_filter)


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
    if step.status in {"BLOCKED", "NEEDS_INPUT"}:
        return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan, replay=True)}
    # Validate before both read invocation and write-review side effects.
    target_error = _execution_error(db, user, step)
    if target_error:
        step.status = plan.status = "BLOCKED"
        step.error_code = target_error[0]
        step.output_json = {"status": "BLOCKED", "error_code": target_error[0], "message": target_error[1], "raw_data_accessed": False}
        step.state_version += 1
        plan.state_version += 1
        add_audit_log(db, action="ASSISTANT_TARGET_REJECTED", target_type="ASSISTANT_PLAN_STEP", target_id=step.step_id, result="BLOCKED", user=user, details={"action_code": step.action_code, "target_type": step.target_type, "error_code": target_error[0], "raw_data_accessed": False})
        db.commit()
        return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan)}
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
    invocation_id = f"assistant-invocation-{step.step_id}"
    output = _run_read_action(db, user, step.action_code, step.target_id, step.target_type, question=str(plan.plan_json.get("question", "")), status_filter=plan.plan_json.get("understanding", {}).get("status_filter"))
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
        if step.status in {"READY", "PENDING_REVIEW", "NEEDS_INPUT", "BLOCKED", "FAILED"}:
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
    if plan.status == "NEEDS_INPUT":
        return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan, replay=True)}
    if plan.status not in {"FAILED", "BLOCKED"}:
        raise ValueError("ASSISTANT_PLAN_NOT_RETRYABLE")
    steps = db.scalars(select(AssistantPlanStep).where(AssistantPlanStep.plan_id == plan.plan_id)).all()
    if any(_execution_error(db, user, step) for step in steps):
        return {"session": _session_payload(session, user), "plan": _plan_payload(db, plan, replay=True)}
    plan.status = "READY"
    plan.state_version += 1
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
