from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_roles
from ..models import (
    AgentEvent,
    AnomalyEvent,
    AuditLog,
    AuditReport,
    BlockchainEvidence,
    SettlementTask,
    User,
)
from ..schemas import AgentQueryRequest, AnomalyResolve, AuditReportCreate
from ..services.common import add_audit_log, model_dict
from ..services.lineage import read_run_events
from ..services.workflow import answer_audit_question, create_audit_report


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
    return [model_dict(item) for item in db.scalars(select(AuditReport).order_by(AuditReport.created_at.desc())).all()]


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
