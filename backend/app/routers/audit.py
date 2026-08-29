from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import and_, func, literal, select, union_all, update
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
    NotificationOutbox,
    SettlementTask,
    Signature,
    User,
    utc_now,
)
from ..schemas import (
    AgentQueryRequest,
    AnomalyResolve,
    AuditReportCreate,
    AuditReportDecisionRequest,
)
from ..security import sha256_json, sign_value
from ..services.adapters import LocalEvidenceLedgerAdapter
from ..services.anomaly_scope import anomaly_events_scope_query
from ..services.audit_scope import audit_task_ids_query, has_audit_permission, scoped_audit_task
from ..services.common import add_audit_log
from ..services.lineage import read_run_events
from ..services.notifications import process_notification_outbox, process_notification_outbox_best_effort, publish_audit_report
from ..services.trust_domain import (
    TTCState,
    TtcStateMachine,
    TrustDomainError,
    verify_active_identity,
)
from ..services.workflow import answer_audit_question, create_audit_report
from ..trust_models import TtcAttempt


router = APIRouter(tags=["audit"])


@router.get("/notification-outbox/status")
def notification_outbox_status(
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    del user
    rows = db.execute(select(NotificationOutbox.status, func.count(NotificationOutbox.outbox_id)).group_by(NotificationOutbox.status)).all()
    return {"counts": {status_code: int(count) for status_code, count in rows}, "business_payload_exposed": False}


@router.post("/notification-outbox/process")
def recover_notification_outbox(
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    del user
    return {**process_notification_outbox(db), "business_payload_exposed": False}


def _require_audit_permission(user: User) -> None:
    if not has_audit_permission(user):
        raise HTTPException(status_code=403, detail="当前账号未获授审计查看权限")


def _scoped_task_or_404(db: Session, user: User, task_id: str) -> SettlementTask:
    _require_audit_permission(user)
    task = scoped_audit_task(db, user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _task_audit_dto(task: SettlementTask) -> dict:
    """Expose business audit state without persistence-only replay material."""

    return {
        "task_id": task.task_id,
        "capsule_id": task.capsule_id,
        "task_name": task.task_name,
        "trade_batch_no": task.trade_batch_no,
        "period_start": task.period_start,
        "period_end": task.period_end,
        "rule_id": task.rule_id,
        "creator_org_id": task.creator_org_id,
        "status": task.status,
        "risk_level": task.risk_level,
        "current_stage": task.current_stage,
        "ttc_state": task.ttc_state,
        "current_attempt": task.current_attempt,
        "state_version": task.state_version,
        "last_transition_at": task.last_transition_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _evidence_audit_dto(evidence: BlockchainEvidence) -> dict:
    """Return verifiable evidence pointers, never the anchored source payload."""

    return {
        "evidence_id": evidence.evidence_id,
        "task_id": evidence.task_id,
        "stage": evidence.stage,
        "biz_type": evidence.biz_type,
        "biz_id": evidence.biz_id,
        "evidence_hash": evidence.evidence_hash,
        "tx_hash": evidence.tx_hash,
        "block_height": evidence.block_height,
        "chain_code": evidence.chain_code,
        "status": evidence.status,
        "created_at": evidence.created_at,
        "updated_at": evidence.updated_at,
    }


def _audit_report_dto(report: AuditReport) -> dict:
    return {
        "report_id": report.report_id,
        "task_id": report.task_id,
        "attempt_id": report.attempt_id,
        "template_code": report.template_code,
        "report_title": report.report_title,
        "report_content": report.report_content,
        "report_hash": report.report_hash,
        "risk_level": report.risk_level,
        "evidence_refs_json": report.evidence_refs_json,
        "status": report.status,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def _anomaly_audit_dto(event: AnomalyEvent) -> dict:
    """Expose disposition state without internal evidence/replay fingerprints."""

    return {
        "event_id": event.event_id,
        "task_id": event.task_id,
        "event_type": event.event_type,
        "risk_level": event.risk_level,
        "title": event.title,
        "description": event.description,
        "status": event.status,
        "resolution": event.resolution,
        "disposition": event.disposition,
        "state_version": event.state_version,
        "resolved_at": event.resolved_at,
        "resolved_by_user_id": event.resolved_by_user_id,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


@router.get("/audit/timeline/{task_id}")
def audit_timeline(
    task_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> dict:
    task = _scoped_task_or_404(db, user, task_id)
    combined = union_all(
        select(
            literal("AGENT_EVENT").label("kind"),
            AgentEvent.event_id.label("reference"),
            AgentEvent.created_at.label("event_time"),
        ).where(AgentEvent.task_id == task_id),
        select(
            literal("EVIDENCE_RECORD").label("kind"),
            BlockchainEvidence.evidence_id.label("reference"),
            BlockchainEvidence.created_at.label("event_time"),
        ).where(BlockchainEvidence.task_id == task_id),
        select(
            literal("ANOMALY").label("kind"),
            AnomalyEvent.event_id.label("reference"),
            AnomalyEvent.created_at.label("event_time"),
        ).where(AnomalyEvent.task_id == task_id),
    ).subquery()
    total = int(db.scalar(select(func.count()).select_from(combined)) or 0)
    rows = db.execute(
        select(combined)
        .order_by(combined.c.event_time, combined.c.reference)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    agent_ids = [row.reference for row in rows if row.kind == "AGENT_EVENT"]
    evidence_ids = [row.reference for row in rows if row.kind == "EVIDENCE_RECORD"]
    anomaly_ids = [row.reference for row in rows if row.kind == "ANOMALY"]
    agent_map = {
        item.event_id: item
        for item in db.scalars(
            select(AgentEvent)
            .where(AgentEvent.event_id.in_(agent_ids))
            .limit(page_size)
        ).all()
    } if agent_ids else {}
    evidence_map = {
        item.evidence_id: item
        for item in db.scalars(
            select(BlockchainEvidence)
            .where(BlockchainEvidence.evidence_id.in_(evidence_ids))
            .limit(page_size)
        ).all()
    } if evidence_ids else {}
    anomaly_map = {
        item.event_id: item
        for item in db.scalars(
            select(AnomalyEvent)
            .where(AnomalyEvent.event_id.in_(anomaly_ids))
            .limit(page_size)
        ).all()
    } if anomaly_ids else {}
    timeline = []
    for row in rows:
        if row.kind == "AGENT_EVENT":
            item = agent_map[row.reference]
            timeline.append({
                "kind": row.kind,
                "time": item.created_at.isoformat(),
                "title": f"{item.agent_code} · {item.message_type}",
                "status": item.status,
                "reference": item.event_id,
                "details": {
                    "sequence_no": item.sequence_no,
                    "agent_code": item.agent_code,
                    "message_type": item.message_type,
                    "tool_name": item.tool_name,
                },
            })
        elif row.kind == "EVIDENCE_RECORD":
            item = evidence_map[row.reference]
            timeline.append({
                "kind": row.kind,
                "time": item.created_at.isoformat(),
                "title": f"{item.stage} · {item.biz_type}",
                "status": item.status,
                "reference": item.evidence_id,
                "details": {"tx_hash": item.tx_hash, "block_height": item.block_height},
            })
        else:
            item = anomaly_map[row.reference]
            timeline.append({
                "kind": row.kind,
                "time": item.created_at.isoformat(),
                "title": item.title,
                "status": item.status,
                "reference": item.event_id,
                "details": {
                    "event_type": item.event_type,
                    "risk_level": item.risk_level,
                    "disposition": item.disposition,
                },
            })
    return {
        "task": _task_audit_dto(task),
        "events": timeline,
        "evidence_records": [
            _evidence_audit_dto(evidence_map[row.reference])
            for row in rows
            if row.kind == "EVIDENCE_RECORD"
        ],
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "raw_data_included": False,
    }


@router.get("/audit/reports")
def list_reports(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> list[dict]:
    _require_audit_permission(user)
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
        .where(SettlementTask.task_id.in_(audit_task_ids_query(user)))
        .order_by(AuditReport.created_at.desc(), AuditReport.report_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [_audit_report_dto(item) for item in reports]


@router.post("/audit/reports", status_code=status.HTTP_201_CREATED)
def generate_report(
    payload: AuditReportCreate,
    user: User = Depends(require_roles("REGULATOR")),
    db: Session = Depends(get_db),
) -> dict:
    _scoped_task_or_404(db, user, payload.task_id)
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
    publish_audit_report(db, report, actor_user_id=user.user_id)
    db.commit()
    process_notification_outbox_best_effort(db)
    return _audit_report_dto(report)


@router.post("/audit/reports/{report_id}/decision")
def decide_report(
    report_id: str,
    payload: AuditReportDecisionRequest,
    response: Response,
    user: User = Depends(require_roles("REGULATOR")),
    db: Session = Depends(get_db),
) -> dict:
    _require_audit_permission(user)
    report_reference = db.get(AuditReport, report_id)
    if report_reference is None:
        raise HTTPException(status_code=404, detail="审计报告不存在")
    task = db.scalar(
        select(SettlementTask)
        .where(
            SettlementTask.task_id == report_reference.task_id,
            SettlementTask.task_id.in_(audit_task_ids_query(user)),
        )
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="审计报告不存在")
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
                **_audit_report_dto(report),
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
        **_audit_report_dto(report),
        "decision": payload.decision,
        "signature_id": signature.signature_id,
        "evidence_id": decision_evidence.evidence_id,
        "idempotent_replay": False,
    }


@router.post("/agent/query")
def agent_query(
    payload: AgentQueryRequest,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> dict:
    _scoped_task_or_404(db, user, payload.task_id)
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> list[dict]:
    _require_audit_permission(user)
    query = (
        anomaly_events_scope_query(user)
        .order_by(AnomalyEvent.created_at.desc(), AnomalyEvent.event_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [_anomaly_audit_dto(item) for item in db.scalars(query).all()]


@router.post("/anomalies/{event_id}/resolve")
def resolve_anomaly(
    event_id: str,
    payload: AnomalyResolve,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(require_roles("REGULATOR")),
    db: Session = Depends(get_db),
) -> dict:
    _require_audit_permission(user)
    event = db.scalar(
        anomaly_events_scope_query(user)
        .where(AnomalyEvent.event_id == event_id)
        .with_for_update()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="异常不存在")
    if if_match is None or idempotency_key is None or not idempotency_key.strip():
        raise HTTPException(status_code=428, detail="处置异常必须提供 If-Match 与 Idempotency-Key")
    normalized_key = idempotency_key.strip()
    if len(normalized_key) > 160:
        raise HTTPException(status_code=422, detail="Idempotency-Key 长度不能超过 160 个字符")
    fingerprint = sha256_json({"resolution": payload.resolution.strip(), "disposition": payload.disposition})
    if event.resolution_idempotency_key == normalized_key:
        if event.resolution_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="同一幂等键不能用于不同处置内容")
        response.headers["ETag"] = f'"{event.state_version}"'
        return {**(event.resolution_response_json or _anomaly_audit_dto(event)), "idempotent_replay": True}
    try:
        expected_version = int(if_match.strip().strip('"'))
    except ValueError as exc:
        raise HTTPException(status_code=412, detail="If-Match 版本无效") from exc
    if event.status != "OPEN":
        raise HTTPException(status_code=409, detail="异常事件已闭合")
    if int(event.state_version or 1) != expected_version:
        raise HTTPException(status_code=412, detail="异常事件版本已变化")

    transition_id = None
    if payload.disposition == "REWORK":
        task = db.get(SettlementTask, event.task_id)
        if task is None or task.ttc_state != TTCState.FAILED.value:
            raise HTTPException(status_code=409, detail="仅 FAILED 状态任务可以通过异常处置进入 REWORK")
        actor_identity = db.scalar(select(DidIdentity).where(
            DidIdentity.owner_id == user.org_id,
            DidIdentity.org_id == user.org_id,
            DidIdentity.owner_type == "ORG",
        ).order_by(DidIdentity.created_at.desc()))
        if actor_identity is None:
            raise HTTPException(status_code=403, detail="当前处置主体缺少有效 DID")
        try:
            transition = TtcStateMachine.transition(
                db, task, TTCState.REWORK, actor_identity.did_id,
                "ANOMALY_DISPOSITION_REWORK", payload.resolution.strip(),
            )
        except TrustDomainError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": exc.detail},
            ) from exc
        transition_id = transition.transition_id
    next_version = expected_version + 1
    resolved_at = utc_now()
    result_payload = {
        "event_id": event.event_id,
        "task_id": event.task_id,
        "status": "RESOLVED",
        "resolution": payload.resolution.strip(),
        "disposition": payload.disposition,
        "state_version": next_version,
        "resolved_at": resolved_at.isoformat(),
        "resolved_by_user_id": user.user_id,
        "transition_id": transition_id,
    }
    updated = db.execute(update(AnomalyEvent).where(
        AnomalyEvent.event_id == event.event_id,
        AnomalyEvent.status == "OPEN",
        AnomalyEvent.state_version == expected_version,
    ).values(
        status="RESOLVED", resolution=payload.resolution.strip(), disposition=payload.disposition,
        state_version=next_version, resolved_at=resolved_at, resolved_by_user_id=user.user_id,
        resolution_idempotency_key=normalized_key, resolution_fingerprint=fingerprint,
        resolution_response_json=result_payload,
    ))
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=412, detail="异常事件版本已变化")
    add_audit_log(
        db,
        action="RESOLVE_ANOMALY",
        target_type="ANOMALY_EVENT",
        target_id=event.event_id,
        result="SUCCESS",
        user=user,
        details={"resolution": payload.resolution, "disposition": payload.disposition, "transition_id": transition_id},
    )
    db.commit()
    response.headers["ETag"] = f'"{next_version}"'
    return {**result_payload, "idempotent_replay": False}


@router.get("/audit/logs")
def list_logs(
    action_code: str | None = None,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    technical_targets = {"SYSTEM", "RUNTIME", "PLATFORM", "DEPLOYMENT", "MIGRATION"}
    query = (
        select(AuditLog)
        .where(AuditLog.target_type.in_(technical_targets))
        .order_by(AuditLog.occurred_at.desc())
        .limit(500)
    )
    if action_code:
        query = query.where(AuditLog.action_code == action_code)
    return [
        {
            "log_id": item.log_id,
            "occurred_at": item.occurred_at,
            "actor_name": "平台服务",
            "action_code": item.action_code,
            "target_type": item.target_type,
            "target_id": "已脱敏",
            "result": item.result,
            "trace_id": item.trace_id,
            "details_json": {"message": "业务内容不向平台运维账号开放"},
        }
        for item in db.scalars(query).all()
    ]


@router.get("/audit/lineage/{run_id}")
def lineage_events(
    run_id: str,
    user: User = Depends(require_roles("EXCHANGE", "REGULATOR")),
    db: Session = Depends(get_db),
) -> dict:
    """Return redacted OpenLineage events for a trusted execution run."""

    _require_audit_permission(user)
    task = db.get(SettlementTask, run_id)
    if task is None:
        return {
            "run_id": run_id,
            "events": [],
            "event_count": 0,
            "raw_data_included": False,
        }
    if scoped_audit_task(db, user, run_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    events = read_run_events(run_id)
    return {
        "run_id": run_id,
        "events": events,
        "event_count": len(events),
        "raw_data_included": False,
    }
