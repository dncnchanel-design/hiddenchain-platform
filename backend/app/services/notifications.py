from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    AuditReport,
    ContractNegotiationEvent,
    DataUsageRequest,
    AnomalyEvent,
    NotificationOutbox,
    PrivacyComputeJob,
    SettlementTask,
    TaskParticipant,
    User,
    UserNotification,
    utc_now,
)
from .common import add_audit_log


class NotificationError(Exception):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def _payload(item: UserNotification) -> dict[str, Any]:
    return {
        "notification_id": item.notification_id,
        "user_id": item.user_id,
        "org_id": item.org_id,
        "type": item.notification_type,
        "notification_type": item.notification_type,
        "title": item.title,
        "body": item.body,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "severity": item.severity,
        "dedupe_key": item.dedupe_key,
        "read_at": item.read_at.isoformat() if item.read_at else None,
        "created_at": item.created_at.isoformat(),
    }


def _recipient_query(
    db: Session,
    *,
    user_ids: Iterable[str] = (),
    org_ids: Iterable[str] = (),
    role_codes: Iterable[str] = (),
    exclude_user_id: str | None = None,
) -> list[User]:
    user_ids = tuple({str(item) for item in user_ids if item})
    org_ids = tuple({str(item) for item in org_ids if item})
    role_codes = tuple({str(item) for item in role_codes if item})
    if not user_ids and not org_ids and not role_codes:
        return []
    query = select(User).where(User.status == "ACTIVE", User.role_code != "ADMIN")
    scopes = []
    if user_ids:
        scopes.append(User.user_id.in_(user_ids))
    if org_ids:
        scopes.append(User.org_id.in_(org_ids))
    if role_codes:
        scopes.append(User.role_code.in_(role_codes))
    if scopes:
        query = query.where(or_(*scopes))
    if exclude_user_id:
        query = query.where(User.user_id != exclude_user_id)
    return list(db.scalars(query.order_by(User.user_id.asc())).all())


def publish(
    db: Session,
    *,
    notification_type: str,
    title: str,
    body: str,
    dedupe_key: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    severity: str = "INFO",
    user_ids: Iterable[str] = (),
    org_ids: Iterable[str] = (),
    role_codes: Iterable[str] = (),
    exclude_user_id: str | None = None,
    task_id: str | None = None,
) -> int:
    """Freeze final recipients into the durable outbox in the caller transaction."""

    recipients = _recipient_query(
        db,
        user_ids=user_ids,
        org_ids=org_ids,
        role_codes=role_codes,
        exclude_user_id=exclude_user_id,
    )
    created = 0
    for recipient in recipients:
        if db.scalar(select(NotificationOutbox.outbox_id).where(
            NotificationOutbox.recipient_user_id == recipient.user_id,
            NotificationOutbox.dedupe_key == dedupe_key,
        )):
            continue
        try:
            with db.begin_nested():
                db.add(NotificationOutbox(
                    recipient_user_id=recipient.user_id,
                    recipient_org_id=recipient.org_id,
                    notification_type=notification_type,
                    title=title,
                    body=body,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    severity=severity,
                    dedupe_key=dedupe_key,
                    payload_json={"task_id": task_id or (entity_id if entity_type == "SETTLEMENT_TASK" else None)},
                    next_attempt_at=utc_now(),
                ))
                db.flush()
            created += 1
        except IntegrityError:
            continue
    return created


def _materialize_notification(db: Session, item: NotificationOutbox) -> None:
    existing = db.scalar(select(UserNotification.notification_id).where(
        UserNotification.user_id == item.recipient_user_id,
        UserNotification.dedupe_key == item.dedupe_key,
    ))
    if existing:
        return
    db.add(UserNotification(
        user_id=item.recipient_user_id,
        org_id=item.recipient_org_id,
        notification_type=item.notification_type,
        title=item.title,
        body=item.body,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        severity=item.severity,
        dedupe_key=item.dedupe_key,
    ))
    db.flush()


def process_notification_outbox(db: Session, *, limit: int = 50, recipient_user_id: str | None = None) -> dict[str, int]:
    now = utc_now()
    query = select(NotificationOutbox.outbox_id).where(or_(
        and_(NotificationOutbox.status.in_(("PENDING", "RETRY")), or_(NotificationOutbox.next_attempt_at.is_(None), NotificationOutbox.next_attempt_at <= now)),
        and_(NotificationOutbox.status == "PROCESSING", NotificationOutbox.lease_expires_at <= now),
    ))
    if recipient_user_id:
        query = query.where(NotificationOutbox.recipient_user_id == recipient_user_id)
    ids = list(db.scalars(query.order_by(NotificationOutbox.created_at).limit(limit)).all())
    delivered = retried = dead = 0
    for outbox_id in ids:
        lease_owner = f"notification-{uuid.uuid4().hex}"
        claimed = db.execute(update(NotificationOutbox).where(
            NotificationOutbox.outbox_id == outbox_id,
            or_(
                and_(
                    NotificationOutbox.status.in_(("PENDING", "RETRY")),
                    or_(
                        NotificationOutbox.next_attempt_at.is_(None),
                        NotificationOutbox.next_attempt_at <= now,
                    ),
                ),
                and_(NotificationOutbox.status == "PROCESSING", NotificationOutbox.lease_expires_at <= now),
            ),
        ).values(status="PROCESSING", lease_owner=lease_owner, lease_expires_at=now + timedelta(seconds=30), attempt_count=NotificationOutbox.attempt_count + 1))
        if claimed.rowcount != 1:
            db.rollback()
            continue
        db.commit()
        item = db.get(NotificationOutbox, outbox_id)
        if item is None or item.lease_owner != lease_owner:
            continue
        try:
            _materialize_notification(db, item)
            completed = db.execute(
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.outbox_id == outbox_id,
                    NotificationOutbox.status == "PROCESSING",
                    NotificationOutbox.lease_owner == lease_owner,
                )
                .values(
                    status="DELIVERED",
                    delivered_at=utc_now(),
                    next_attempt_at=None,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error=None,
                )
            )
            if completed.rowcount != 1:
                db.rollback()
                continue
            db.commit()
            delivered += 1
        except Exception as exc:
            db.rollback()
            owned = db.scalar(
                select(NotificationOutbox).where(
                    NotificationOutbox.outbox_id == outbox_id,
                    NotificationOutbox.status == "PROCESSING",
                    NotificationOutbox.lease_owner == lease_owner,
                )
            )
            if owned is None:
                continue
            failed_at = utc_now()
            is_dead_letter = owned.attempt_count >= owned.max_attempts
            failure_values = {
                "status": "DEAD_LETTER" if is_dead_letter else "RETRY",
                "last_error": f"{type(exc).__name__}: {str(exc)}"[:255],
                "lease_owner": None,
                "lease_expires_at": None,
                "next_attempt_at": (
                    None
                    if is_dead_letter
                    else failed_at + timedelta(seconds=min(60, 2 ** owned.attempt_count))
                ),
                "dead_lettered_at": failed_at if is_dead_letter else None,
            }
            failed = db.execute(
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.outbox_id == outbox_id,
                    NotificationOutbox.status == "PROCESSING",
                    NotificationOutbox.lease_owner == lease_owner,
                )
                .values(**failure_values)
            )
            if failed.rowcount != 1:
                db.rollback()
                continue
            if is_dead_letter:
                dedupe = f"notification-dead-letter:{owned.outbox_id}"
                if not db.scalar(select(AnomalyEvent.event_id).where(AnomalyEvent.dedupe_key == dedupe)):
                    db.add(AnomalyEvent(
                        task_id=(owned.payload_json or {}).get("task_id"), event_type="NOTIFICATION_DEAD_LETTER",
                        risk_level="MEDIUM", title="通知投递进入死信", description="通知物化达到最大重试次数",
                        evidence_json={"outbox_id": owned.outbox_id, "recipient_user_id": owned.recipient_user_id}, dedupe_key=dedupe,
                    ))
                    add_audit_log(
                        db,
                        action="NOTIFICATION_OUTBOX_DEAD_LETTER",
                        target_type="NOTIFICATION_OUTBOX",
                        target_id=owned.outbox_id,
                        result="DEAD_LETTER",
                        actor_name="NOTIFICATION_OUTBOX_WORKER",
                        details={"task_id": (owned.payload_json or {}).get("task_id")},
                    )
                dead += 1
            else:
                retried += 1
            db.commit()
    return {"delivered": delivered, "retry": retried, "dead_letter": dead}


def process_notification_outbox_best_effort(db: Session, *, limit: int = 50) -> None:
    try:
        process_notification_outbox(db, limit=limit)
    except Exception:
        db.rollback()


def list_notifications(
    db: Session,
    user: User,
    *,
    page: int,
    page_size: int,
    notification_type: str | None = None,
    unread_only: bool = False,
) -> dict[str, Any]:
    process_notification_outbox(db, recipient_user_id=user.user_id)
    query = select(UserNotification).where(UserNotification.user_id == user.user_id)
    if notification_type:
        query = query.where(UserNotification.notification_type == notification_type)
    if unread_only:
        query = query.where(UserNotification.read_at.is_(None))
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    unread_count = int(
        db.scalar(
            select(func.count()).where(
                UserNotification.user_id == user.user_id,
                UserNotification.read_at.is_(None),
            )
        )
        or 0
    )
    records = db.scalars(
        query.order_by(UserNotification.created_at.desc(), UserNotification.notification_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_payload(item) for item in records],
        "total": total,
        "unread_count": unread_count,
        "page": page,
        "page_size": page_size,
        "empty_state": total == 0,
        "allowed_actions": ["view", "mark_read", "mark_all_read"],
        "capability_state": "LOCAL_REAL",
        "source_of_truth": "user_notifications",
    }


def mark_read(db: Session, user: User, notification_id: str) -> dict[str, Any]:
    item = db.scalar(
        select(UserNotification).where(
            UserNotification.notification_id == notification_id,
            UserNotification.user_id == user.user_id,
        )
    )
    if item is None:
        raise NotificationError(404, "NOTIFICATION_NOT_FOUND", "通知不存在或当前主体不可见")
    if item.read_at is None:
        item.read_at = utc_now()
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    return _payload(item)


def mark_all_read(db: Session, user: User) -> dict[str, Any]:
    now = utc_now()
    try:
        result = db.execute(
            update(UserNotification)
            .where(
                UserNotification.user_id == user.user_id,
                UserNotification.read_at.is_(None),
            )
            .values(read_at=now)
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "updated_count": int(result.rowcount or 0),
        "unread_count": 0,
        "allowed_actions": ["view"],
        "capability_state": "LOCAL_REAL",
        "source_of_truth": "user_notifications",
    }


def publish_access_request_submitted(db: Session, request: DataUsageRequest) -> int:
    return publish(
        db,
        notification_type="DATA_USAGE_REQUEST",
        title="新的数据使用申请",
        body=f"收到针对资产 {request.asset_id} 的数据使用申请，用途：{request.purpose}。",
        dedupe_key=f"data-usage:{request.request_id}:SUBMITTED",
        entity_type="DATA_USAGE_REQUEST",
        entity_id=request.request_id,
        org_ids=[request.provider_org_id],
    )


def publish_access_request_decision(
    db: Session,
    request: DataUsageRequest,
    *,
    action: str,
    actor_user_id: str | None = None,
) -> int:
    normalized = action.upper()
    status_label = {
        "APPROVE": "已批准",
        "REJECT": "已拒绝",
        "REVOKE": "已撤销",
        "EXPIRE": "已过期",
    }.get(normalized, normalized)
    target_orgs = [request.applicant_org_id]
    if normalized in {"REVOKE", "EXPIRE"}:
        target_orgs.append(request.provider_org_id)
    return publish(
        db,
        notification_type="DATA_USAGE_DECISION",
        title=f"数据使用申请{status_label}",
        body=f"申请 {request.request_id} 当前状态为 {request.status}。{request.decision_reason or request.revocation_reason or ''}".strip(),
        dedupe_key=f"data-usage:{request.request_id}:{normalized}",
        entity_type="DATA_USAGE_REQUEST",
        entity_id=request.request_id,
        severity="WARNING" if normalized in {"REJECT", "REVOKE", "EXPIRE"} else "INFO",
        org_ids=target_orgs,
        exclude_user_id=actor_user_id,
    )


def publish_contract_event(
    db: Session,
    event: ContractNegotiationEvent,
    *,
    provider_org_id: str,
    consumer_org_id: str,
) -> int:
    return publish(
        db,
        notification_type="CONTRACT_NEGOTIATION",
        title="合同协商有新事件",
        body=f"合同 {event.contract_id} 产生 {event.event_type} 事件，状态变更为 {event.to_state}。",
        dedupe_key=f"contract:{event.contract_id}:event:{event.event_id}",
        entity_type="DATA_CONTRACT",
        entity_id=event.contract_id,
        org_ids=[provider_org_id, consumer_org_id],
        exclude_user_id=event.actor_user_id,
    )


def publish_ttc_transition(
    db: Session,
    task: SettlementTask,
    *,
    transition_id: str,
    to_state: str,
    actor_user_id: str | None = None,
    participant_org_ids: Iterable[str] = (),
) -> int:
    org_ids = set(participant_org_ids)
    org_ids.add(task.creator_org_id)
    return publish(
        db,
        notification_type="TTC_STATE",
        title="TTC 任务状态已更新",
        body=f"任务 {task.task_id} 已进入 {to_state}。",
        dedupe_key=f"ttc:{task.task_id}:transition:{transition_id}",
        entity_type="SETTLEMENT_TASK",
        entity_id=task.task_id,
        org_ids=org_ids,
        exclude_user_id=actor_user_id,
    )


def publish_computation_action(
    db: Session,
    job: PrivacyComputeJob,
    *,
    action: str,
    actor_user_id: str | None = None,
    org_ids: Iterable[str] = (),
) -> int:
    normalized = action.upper()
    label = {"CANCEL": "已取消"}.get(normalized, normalized)
    return publish(
        db,
        notification_type="COMPUTE_CONTROL",
        title=f"计算任务{label}",
        body=f"计算任务 {job.job_id} 当前状态为 {job.status}。",
        dedupe_key=f"compute:{job.job_id}:action:{normalized}:{job.state_version}",
        entity_type="PRIVACY_COMPUTE_JOB",
        entity_id=job.job_id,
        severity="WARNING" if normalized == "CANCEL" else "INFO",
        org_ids=org_ids,
        exclude_user_id=actor_user_id,
        task_id=job.task_id,
    )


def publish_result_confirmation(
    db: Session,
    *,
    task_id: str,
    result_id: str,
    attempt_id: str | None,
    org_ids: Iterable[str],
) -> int:
    return publish(
        db,
        notification_type="RESULT_CONFIRMATION",
        title="计算结果待确认",
        body=f"任务 {task_id} 已生成需要主体确认的结果。",
        dedupe_key=f"result:{task_id}:{attempt_id or 'legacy'}:{result_id}:CONFIRM",
        entity_type="SETTLEMENT_RESULT",
        entity_id=result_id,
        org_ids=org_ids,
        task_id=task_id,
    )


def publish_audit_report(
    db: Session,
    report: AuditReport,
    *,
    actor_user_id: str | None = None,
) -> int:
    from .audit_scope import scoped_audit_task

    task = db.get(SettlementTask, report.task_id)
    if task is None:
        return 0
    org_ids = {task.creator_org_id, *db.scalars(select(TaskParticipant.org_id).where(TaskParticipant.task_id == task.task_id)).all()}
    recipient_user_ids = set(db.scalars(select(User.user_id).where(User.status == "ACTIVE", User.org_id.in_(org_ids))).all())
    regulators = db.scalars(select(User).where(User.status == "ACTIVE", User.role_code == "REGULATOR")).all()
    recipient_user_ids.update(user.user_id for user in regulators if scoped_audit_task(db, user, task.task_id) is not None)
    return publish(
        db,
        notification_type="AUDIT_REPORT",
        title="审计报告已生成",
        body=f"任务 {report.task_id} 的审计报告已生成，当前状态为 {report.status}。",
        dedupe_key=f"audit-report:{report.report_id}:GENERATED",
        entity_type="AUDIT_REPORT",
        entity_id=report.report_id,
        user_ids=recipient_user_ids,
        exclude_user_id=actor_user_id,
        task_id=report.task_id,
    )
