from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_roles
from ..models import (
    AgentEvent,
    AnomalyEvent,
    AuditLog,
    AuditReport,
    BlockchainEvidence,
    DidIdentity,
    SettlementTask,
    Signature,
    User,
)
from ..schemas import (
    AgentQueryRequest,
    AnomalyResolve,
    AuditReportCreate,
    AuditReportDecisionRequest,
)
from ..security import sha256_json, sign_value
from ..services.adapters import LocalEvidenceLedgerAdapter
from ..services.common import add_audit_log, model_dict
from ..services.lineage import read_run_events
from ..services.trust_domain import (
    TTCState,
    TtcStateMachine,
    TrustDomainError,
    verify_active_identity,
)
from ..services.workflow import answer_audit_question, create_audit_report
from ..trust_models import TtcAttempt


router = APIRouter(tags=["audit"])


@router.get("/audit/timeline/{task_id}")
def audit_timeline(
    task_id: str,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    task = db.get(SettlementTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    agent_events = db.scalars(
        select(AgentEvent).where(AgentEvent.task_id == task_id).order_by(AgentEvent.sequence_no)
    ).all()
    evidences = db.scalars(
        select(BlockchainEvidence).where(BlockchainEvidence.task_id == task_id).order_by(BlockchainEvidence.block_height)
    ).all()
    anomalies = db.scalars(
        select(AnomalyEvent).where(AnomalyEvent.task_id == task_id).order_by(AnomalyEvent.created_at)
    ).all()
    timeline = [
        {
            "kind": "AGENT_EVENT",
            "time": item.created_at.isoformat(),
            "title": f"{item.agent_code} · {item.message_type}",
            "status": item.status,
            "reference": item.event_id,
            "details": item.details_json,
        }
        for item in agent_events
    ] + [
        {
            "kind": "EVIDENCE_RECORD",
            "time": item.created_at.isoformat(),
            "title": f"{item.stage} · {item.biz_type}",
            "status": item.status,
            "reference": item.evidence_id,
            "details": {"tx_hash": item.tx_hash, "block_height": item.block_height},
        }
        for item in evidences
    ] + [
        {
            "kind": "ANOMALY",
            "time": item.created_at.isoformat(),
            "title": item.title,
            "status": item.status,
            "reference": item.event_id,
            "details": item.evidence_json,
        }
        for item in anomalies
    ]
    timeline.sort(key=lambda item: item["time"])
    return {
        "task": model_dict(task),
        "events": timeline,
        "evidence_records": [model_dict(item) for item in evidences],
        "raw_data_included": False,
    }


@router.get("/audit/reports")
def list_reports(
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    reports = db.scalars(
        select(AuditReport)
        .join(SettlementTask, SettlementTask.task_id == AuditReport.task_id)
        .join(
            TtcAttempt,
            and_(
                TtcAttempt.task_id == SettlementTask.task_id,
                TtcAttempt.attempt_no == SettlementTask.current_attempt,
                TtcAttempt.attempt_id == AuditReport.attempt_id,
            ),
        )
        .order_by(AuditReport.created_at.desc())
    ).all()
    return [model_dict(item) for item in reports]


@router.post("/audit/reports", status_code=status.HTTP_201_CREATED)
def generate_report(
    payload: AuditReportCreate,
    user: User = Depends(require_roles("REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        report = create_audit_report(db, payload.task_id, payload.template_code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    add_audit_log(
        db,
        action="GENERATE_AUDIT_REPORT",
        target_type="AUDIT_REPORT",
        target_id=report.report_id,
        result="SUCCESS",
        user=user,
        details={"report_hash": report.report_hash},
    )
    db.commit()
    return model_dict(report)


@router.post("/audit/reports/{report_id}/decision")
def decide_report(
    report_id: str,
    payload: AuditReportDecisionRequest,
    response: Response,
    user: User = Depends(require_roles("REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    report_reference = db.get(AuditReport, report_id)
    if report_reference is None:
        raise HTTPException(status_code=404, detail="审计报告不存在")
    task = db.scalar(
        select(SettlementTask)
        .where(SettlementTask.task_id == report_reference.task_id)
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    report = db.scalar(
        select(AuditReport)
        .where(AuditReport.report_id == report_id)
        .with_for_update()
    )
    if report is None:
        raise HTTPException(status_code=404, detail="审计报告不存在")
    attempt = db.scalar(
        select(TtcAttempt).where(
            TtcAttempt.task_id == task.task_id,
            TtcAttempt.attempt_no == task.current_attempt,
        )
    )
    if attempt is None or report.attempt_id != attempt.attempt_id:
        raise HTTPException(status_code=409, detail="该审计报告不属于当前执行尝试")

    actor_identity = db.scalar(
        select(DidIdentity)
        .where(
            DidIdentity.owner_id == user.org_id,
            DidIdentity.org_id == user.org_id,
            DidIdentity.owner_type == "ORG",
        )
        .order_by(DidIdentity.created_at.desc())
    )
    if actor_identity is None:
        raise HTTPException(status_code=403, detail="当前审核主体缺少有效 DID")
    try:
        verify_active_identity(db, actor_identity.did_id)
    except TrustDomainError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc

    target_type = f"AUDIT_REPORT_{payload.decision}"
    expected_status = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
    existing = db.scalar(
        select(Signature)
        .where(
            Signature.task_id == task.task_id,
            Signature.target_type == target_type,
            Signature.target_id == report.report_id,
            Signature.target_hash == report.report_hash,
            Signature.verify_status == "VALID",
        )
        .order_by(Signature.created_at.desc())
    )
    if report.status in {"APPROVED", "REJECTED"}:
        if report.status == expected_status and existing is not None:
            response.headers["ETag"] = f'"{int(task.state_version or 1)}"'
            return {
                **model_dict(report),
                "decision": payload.decision,
                "signature_id": existing.signature_id,
                "idempotent_replay": True,
            }
        raise HTTPException(status_code=409, detail="审计报告已经形成不可变的审核结论")
    if report.status != "GENERATED":
        raise HTTPException(status_code=409, detail="当前审计报告状态不允许审核")
    if task.status not in {"PENDING_CONFIRMATION", "PARTIALLY_CONFIRMED"}:
        raise HTTPException(status_code=409, detail="任务不在结果确认阶段")
    try:
        current_state = TTCState(task.ttc_state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="任务 TTC 状态无效") from exc
    if current_state != TTCState.RESULT_CONFIRM:
        raise HTTPException(status_code=409, detail="任务 TTC 状态不允许审核结论")

    signed_payload = {
        "task_id": task.task_id,
        "attempt_id": attempt.attempt_id,
        "report_id": report.report_id,
        "report_hash": report.report_hash,
        "decision": payload.decision,
        "opinion": payload.opinion,
    }
    signature = Signature(
        task_id=task.task_id,
        signer_org_id=user.org_id,
        signer_did=actor_identity.did_id,
        target_type=target_type,
        target_id=report.report_id,
        target_hash=report.report_hash,
        signature_value=sign_value(signed_payload, actor_identity.did_id),
        verify_status="VALID",
    )
    db.add(signature)
    db.flush()
    report.status = expected_status
    if payload.decision == "REJECT":
        try:
            TtcStateMachine.transition(
                db,
                task,
                TTCState.REWORK,
                actor_identity.did_id,
                "AUDIT_REPORT_REJECTED",
                payload.opinion,
                agent_did="did:hiddenchain:agent:audit-risk",
            )
        except TrustDomainError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        task.status = "DRAFT"
        task.current_stage = "审计退回待重算"
    else:
        task.state_version = int(task.state_version or 1) + 1

    decision_evidence = LocalEvidenceLedgerAdapter().anchor(
        db,
        task_id=task.task_id,
        stage="POST_COMPUTE",
        biz_type="AUDIT_REPORT_DECISION",
        biz_id=report.report_id,
        payload={
            "attempt_id": attempt.attempt_id,
            "report_hash": report.report_hash,
            "decision": payload.decision,
            "opinion_hash": sha256_json(payload.opinion),
            "signature_id": signature.signature_id,
            "signer_did": actor_identity.did_id,
            "raw_opinion_included": False,
        },
    )
    add_audit_log(
        db,
        action="REVIEW_AUDIT_REPORT",
        target_type="AUDIT_REPORT",
        target_id=report.report_id,
        result=expected_status,
        user=user,
        details={
            "decision": payload.decision,
            "opinion": payload.opinion,
            "signature_id": signature.signature_id,
            "evidence_id": decision_evidence.evidence_id,
        },
    )
    db.commit()
    response.headers["ETag"] = f'"{int(task.state_version or 1)}"'
    return {
        **model_dict(report),
        "decision": payload.decision,
        "signature_id": signature.signature_id,
        "evidence_id": decision_evidence.evidence_id,
        "idempotent_replay": False,
    }


@router.post("/agent/query")
def agent_query(
    payload: AgentQueryRequest,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        answer = answer_audit_question(db, payload.task_id, payload.question)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    add_audit_log(
        db,
        action="AGENT_AUDIT_QUERY",
        target_type="SETTLEMENT_TASK",
        target_id=payload.task_id,
        result="SUCCESS",
        user=user,
        details={"question": payload.question, "citation_count": len(answer["citations"])},
    )
    db.commit()
    return answer


@router.get("/anomalies")
def list_anomalies(
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [model_dict(item) for item in db.scalars(select(AnomalyEvent).order_by(AnomalyEvent.created_at.desc())).all()]


@router.post("/anomalies/{event_id}/resolve")
def resolve_anomaly(
    event_id: str,
    payload: AnomalyResolve,
    user: User = Depends(require_roles("REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    event = db.get(AnomalyEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="异常不存在")
    event.status = "RESOLVED"
    event.resolution = payload.resolution
    task = db.get(SettlementTask, event.task_id)
    remaining_open = db.scalar(
        select(AnomalyEvent).where(
            AnomalyEvent.task_id == event.task_id,
            AnomalyEvent.status == "OPEN",
            AnomalyEvent.event_id != event.event_id,
        )
    )
    if task is not None and remaining_open is None:
        previous_status = str(event.evidence_json.get("previous_task_status") or "DRAFT")
        task.status = previous_status if previous_status != "EXCEPTION" else "DRAFT"
        task.risk_level = str(event.evidence_json.get("previous_risk_level") or "LOW")
        task.current_stage = {
            "DRAFT": "任务准备",
            "READY": "待启动结算",
            "RUNNING": "执行中",
            "PENDING_CONFIRMATION": "待主体确认",
            "PARTIALLY_CONFIRMED": "待主体确认",
            "AUDITED": "结算完成",
        }.get(task.status, "任务准备")
    add_audit_log(
        db,
        action="RESOLVE_ANOMALY",
        target_type="ANOMALY_EVENT",
        target_id=event.event_id,
        result="SUCCESS",
        user=user,
        details={"resolution": payload.resolution},
    )
    db.commit()
    return model_dict(event)


@router.get("/audit/logs")
def list_logs(
    action_code: str | None = None,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(500)
    if action_code:
        query = query.where(AuditLog.action_code == action_code)
    return [model_dict(item) for item in db.scalars(query).all()]


@router.get("/audit/lineage/{run_id}")
def lineage_events(
    run_id: str,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR", "ADMIN")),
) -> dict:
    """Return redacted OpenLineage events for a trusted execution run."""

    events = read_run_events(run_id)
    return {
        "run_id": run_id,
        "events": events,
        "event_count": len(events),
        "raw_data_included": False,
    }
