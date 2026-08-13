from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..config import settings
from ..models import AgentEvent, BlockchainEvidence, SettlementTask, TaskParticipant, User
from ..schemas import AgentBatchInvokeRequest, AgentInvokeRequest
from ..services.adapters import AGENT_DEFINITIONS, MockBlockchainAdapter
from ..services.common import add_audit_log, model_dict
from ..services.llm import DeepSeekUnavailable
from ..services.workflow import AGENT_DEFAULT_INSTRUCTIONS, invoke_deepseek_agent


router = APIRouter(tags=["trust"])


def _authorized_task_ids(db: Session, user: User) -> list[str] | None:
    if user.role_code in {"EXCHANGE", "REGULATOR", "ADMIN"}:
        return None
    return list(db.scalars(select(TaskParticipant.task_id).where(TaskParticipant.org_id == user.org_id)).all())


@router.get("/chain/evidence")
def list_evidence(
    task_id: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(BlockchainEvidence).order_by(BlockchainEvidence.block_height.desc())
    if task_id:
        query = query.where(BlockchainEvidence.task_id == task_id)
    scoped = _authorized_task_ids(db, user)
    if scoped is not None:
        query = query.where(BlockchainEvidence.task_id.in_(scoped or ["__none__"]))
    return [model_dict(item) for item in db.scalars(query).all()]


@router.get("/chain/evidence/{evidence_id}/verify")
def verify_evidence(
    evidence_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    evidence = db.get(BlockchainEvidence, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    scoped = _authorized_task_ids(db, user)
    if scoped is not None and evidence.task_id not in scoped:
        raise HTTPException(status_code=403, detail="无权核验该证据")
    result = MockBlockchainAdapter.verify(evidence)
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
    return result


@router.get("/agents/definitions")
def agent_definitions(
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
) -> list[dict]:
    return [
        {
            **item,
            "default_instruction": AGENT_DEFAULT_INSTRUCTIONS[item["code"]],
            "llm_provider": "deepseek",
            "llm_model": settings.deepseek_model,
        }
        for item in AGENT_DEFINITIONS
    ]


@router.get("/agents/llm/status")
def agent_llm_status(
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    latest = db.scalar(
        select(AgentEvent)
        .where(AgentEvent.message_type == "DeepSeekAgentAnalysis")
        .order_by(AgentEvent.created_at.desc())
    )
    latest_details = latest.details_json if latest else {}
    return {
        "enabled": settings.deepseek_enabled,
        "key_configured": bool(settings.deepseek_api_key),
        "configured": settings.deepseek_enabled and bool(settings.deepseek_api_key),
        "provider": "deepseek",
        "model": settings.deepseek_model,
        "supported_agent_count": len(AGENT_DEFINITIONS),
        "live_verified": bool(
            latest
            and latest_details.get("provider") == "deepseek"
            and latest_details.get("fallback") is False
        ),
        "last_success": (
            {
                "agent_code": latest.agent_code,
                "event_id": latest.event_id,
                "request_id": latest_details.get("request_id"),
                "duration_ms": latest_details.get("duration_ms"),
                "created_at": latest.created_at.isoformat(),
            }
            if latest
            else None
        ),
        "security_boundary": "DeepSeek只分析结构化摘要；确定性结算、权限和安全闸门仍由本地受控组件执行。",
    }


def _invoke_and_log(
    db: Session,
    *,
    agent_code: str,
    task_id: str,
    instruction: str,
    user: User,
) -> dict:
    result = invoke_deepseek_agent(
        db,
        task_id=task_id,
        agent_code=agent_code,
        instruction=instruction,
    )
    add_audit_log(
        db,
        action="INVOKE_DEEPSEEK_AGENT",
        target_type="AGENT",
        target_id=agent_code,
        result="SUCCESS",
        user=user,
        details={
            "task_id": task_id,
            "event_id": result["event_id"],
            "provider": result["provider"],
            "model": result["model"],
            "request_id": result["request_id"],
            "duration_ms": result["duration_ms"],
        },
    )
    db.commit()
    return result


@router.post("/agents/invoke-all")
def invoke_all_agents(
    payload: AgentBatchInvokeRequest,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(SettlementTask, payload.task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    results: list[dict] = []
    for definition in AGENT_DEFINITIONS:
        agent_code = definition["code"]
        try:
            result = _invoke_and_log(
                db,
                agent_code=agent_code,
                task_id=payload.task_id,
                instruction=AGENT_DEFAULT_INSTRUCTIONS[agent_code],
                user=user,
            )
            results.append({"success": True, **result})
        except DeepSeekUnavailable as exc:
            db.rollback()
            results.append(
                {
                    "success": False,
                    "agent_code": agent_code,
                    "agent_name": definition["name"],
                    "error": str(exc),
                }
            )
            break
    return {
        "task_id": payload.task_id,
        "all_succeeded": len(results) == len(AGENT_DEFINITIONS)
        and all(item["success"] for item in results),
        "success_count": sum(bool(item["success"]) for item in results),
        "expected_count": len(AGENT_DEFINITIONS),
        "results": results,
    }


@router.post("/agents/{agent_code}/invoke")
def invoke_agent(
    agent_code: str,
    payload: AgentInvokeRequest,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    normalized_code = agent_code.upper()
    if normalized_code not in AGENT_DEFAULT_INSTRUCTIONS:
        raise HTTPException(status_code=404, detail="Agent不存在")
    try:
        return _invoke_and_log(
            db,
            agent_code=normalized_code,
            task_id=payload.task_id,
            instruction=payload.instruction,
            user=user,
        )
    except DeepSeekUnavailable as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=f"DeepSeek调用失败：{str(exc)}") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agents/events")
def agent_events(
    task_id: str | None = None,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(AgentEvent).order_by(AgentEvent.created_at.desc(), AgentEvent.sequence_no.desc())
    if task_id:
        query = query.where(AgentEvent.task_id == task_id)
    return [model_dict(item) for item in db.scalars(query).all()]
