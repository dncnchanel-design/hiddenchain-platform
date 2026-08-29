from __future__ import annotations

from sqlalchemy import and_, false, or_, select

from ..models import AnomalyEvent, TrustedQueryTask, User
from .audit_scope import (
    AUDIT_SCOPE_ALL,
    AUDIT_SCOPE_ORG_PREFIX,
    AUDIT_SCOPE_TASK_PREFIX,
    audit_task_ids_query,
    has_audit_permission,
)


TRUSTED_QUERY_ANOMALY_TYPES = frozenset({"TRUSTED_QUERY_TERMINAL_FAILURE"})


def trusted_query_task_ids_query(user: User):
    query = select(TrustedQueryTask.task_id)
    if not has_audit_permission(user):
        return query.where(false())
    permissions = {
        item for item in (user.permissions_json or []) if isinstance(item, str)
    }
    if user.role_code == "REGULATOR":
        if AUDIT_SCOPE_ALL in permissions:
            return query
        task_ids = {
            item.removeprefix(AUDIT_SCOPE_TASK_PREFIX)
            for item in permissions
            if item.startswith(AUDIT_SCOPE_TASK_PREFIX)
            and item != AUDIT_SCOPE_TASK_PREFIX
        }
        org_ids = {
            item.removeprefix(AUDIT_SCOPE_ORG_PREFIX)
            for item in permissions
            if item.startswith(AUDIT_SCOPE_ORG_PREFIX)
            and item != AUDIT_SCOPE_ORG_PREFIX
        }
        conditions = []
        if task_ids:
            conditions.append(TrustedQueryTask.task_id.in_(task_ids))
        if org_ids:
            conditions.append(
                or_(
                    TrustedQueryTask.applicant_org_id.in_(org_ids),
                    TrustedQueryTask.provider_org_id.in_(org_ids),
                )
            )
        return query.where(or_(*conditions) if conditions else false())
    return query.where(
        or_(
            TrustedQueryTask.applicant_user_id == user.user_id,
            TrustedQueryTask.applicant_org_id == user.org_id,
            TrustedQueryTask.provider_org_id == user.org_id,
        )
    )


def anomaly_events_scope_query(user: User):
    trusted_query_type = AnomalyEvent.event_type.in_(TRUSTED_QUERY_ANOMALY_TYPES)
    return select(AnomalyEvent).where(
        or_(
            and_(
                trusted_query_type,
                AnomalyEvent.task_id.in_(trusted_query_task_ids_query(user)),
            ),
            and_(
                ~trusted_query_type,
                AnomalyEvent.task_id.in_(audit_task_ids_query(user)),
            ),
        )
    )
