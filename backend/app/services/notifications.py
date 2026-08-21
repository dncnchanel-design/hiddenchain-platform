from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..models import (
    AuditReport,
    ContractNegotiationEvent,
    DataUsageRequest,
    PrivacyComputeJob,
    SettlementTask,
    User,
    UserNotification,
    utc_now,
)


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
    query = select(User).where(User.status == "ACTIVE")
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
) -> int:
    """Publish notifications after a domain transaction has committed.

    The caller deliberately invokes this after its primary commit.  Any
    notification error is swallowed and rolled back here, so an unavailable
    inbox never invalidates an already committed business decision.
    """

    recipients = _recipient_query(
        db,
        user_ids=user_ids,
        org_ids=org_ids,
        role_codes=role_codes,
        exclude_user_id=exclude_user_id,
    )
    created = 0
    try:
        for recipient in recipients:
            existing = db.scalar(
                select(UserNotification).where(
                    UserNotification.user_id == recipient.user_id,
                    UserNotification.dedupe_key == dedupe_key,
                )
            )
            if existing is not None:
                continue
            db.add(
                UserNotification(
                    user_id=recipient.user_id,
                    org_id=recipient.org_id,
                    notification_type=notification_type,
                    title=title,
                    body=body,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    severity=severity,
                    dedupe_key=dedupe_key,
                )
            )
            created += 1
        if created:
            db.commit()
    except Exception:
        db.rollback()
        return 0
    return created


def list_notifications(
    db: Session,
    user: User,
    *,
    page: int,
    page_size: int,
    notification_type: str | None = None,
    unread_only: bool = False,
) -> dict[str, Any]:
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
    )


def publish_audit_report(
    db: Session,
    report: AuditReport,
    *,
    actor_user_id: str | None = None,
) -> int:
    return publish(
        db,
        notification_type="AUDIT_REPORT",
        title="审计报告已生成",
        body=f"任务 {report.task_id} 的审计报告已生成，当前状态为 {report.status}。",
        dedupe_key=f"audit-report:{report.report_id}:GENERATED",
        entity_type="AUDIT_REPORT",
        entity_id=report.report_id,
        role_codes=["EXCHANGE", "REGULATOR", "ADMIN"],
        exclude_user_id=actor_user_id,
    )
