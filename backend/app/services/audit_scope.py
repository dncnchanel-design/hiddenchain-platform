from __future__ import annotations

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.orm import Session

from ..models import SettlementTask, TaskParticipant, TrustedQueryTask, User


AUDIT_PERMISSION = "VIEW_AUDIT"
AUDIT_SCOPE_ALL = "VIEW_AUDIT:ALL"
AUDIT_SCOPE_TASK_PREFIX = "VIEW_AUDIT:TASK:"
AUDIT_SCOPE_ORG_PREFIX = "VIEW_AUDIT:ORG:"


def _permission_codes(user: User) -> set[str]:
    return {item for item in (user.permissions_json or []) if isinstance(item, str)}


def has_audit_permission(user: User) -> bool:
    """Individual capability gate; a role name alone never grants audit access."""

    return user.role_code != "ADMIN" and AUDIT_PERMISSION in _permission_codes(user)


def audit_task_scope_query(user: User):
    """Return the one authoritative task/resource boundary for audit reads.

    Scope can come from the actor's own organization, task participation, or an
    explicit per-user task/organization/global audit grant.  The global grant is
    deliberately separate from ``VIEW_AUDIT`` so two users with the same role
    can have different audit reach.
    """

    query = select(SettlementTask)
    permissions = _permission_codes(user)
    if not has_audit_permission(user):
        return query.where(false())
    if user.role_code == "REGULATOR" and AUDIT_SCOPE_ALL in permissions:
        return query

    task_ids = {
        item.removeprefix(AUDIT_SCOPE_TASK_PREFIX)
        for item in permissions
        if item.startswith(AUDIT_SCOPE_TASK_PREFIX) and item != AUDIT_SCOPE_TASK_PREFIX
    }
    org_ids = {
        item.removeprefix(AUDIT_SCOPE_ORG_PREFIX)
        for item in permissions
        if item.startswith(AUDIT_SCOPE_ORG_PREFIX) and item != AUDIT_SCOPE_ORG_PREFIX
    }
    participant_org_ids = {user.org_id, *org_ids}
    conditions = [
        SettlementTask.creator_org_id.in_(participant_org_ids),
        SettlementTask.task_id.in_(
            select(TaskParticipant.task_id).where(TaskParticipant.org_id.in_(participant_org_ids))
        ),
    ]
    if task_ids:
        conditions.append(SettlementTask.task_id.in_(task_ids))
    return query.where(or_(*conditions))


def audit_task_ids_query(user: User):
    return audit_task_scope_query(user).with_only_columns(SettlementTask.task_id)


def audit_trusted_query_task_scope_query(user: User):
    """Scope query tasks without treating the REGULATOR role as a global grant.

    A matching settlement task is authoritative.  Only standalone query tasks
    fall back to explicit audit grants and applicant/provider organization
    boundaries.
    """

    query = select(TrustedQueryTask)
    permissions = _permission_codes(user)
    if not has_audit_permission(user):
        return query.where(false())

    settlement_exists = select(SettlementTask.task_id).where(
        SettlementTask.task_id == TrustedQueryTask.task_id
    ).exists()
    settlement_scoped = TrustedQueryTask.task_id.in_(audit_task_ids_query(user))
    if user.role_code == "REGULATOR" and AUDIT_SCOPE_ALL in permissions:
        standalone_scope = true()
    else:
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
        visible_org_ids = {user.org_id, *org_ids}
        standalone_scope = or_(
            TrustedQueryTask.task_id.in_(task_ids),
            TrustedQueryTask.applicant_org_id.in_(visible_org_ids),
            TrustedQueryTask.provider_org_id.in_(visible_org_ids),
        )
    return query.where(
        or_(settlement_scoped, and_(~settlement_exists, standalone_scope))
    )


def audit_trusted_query_task_ids_query(user: User):
    return audit_trusted_query_task_scope_query(user).with_only_columns(
        TrustedQueryTask.task_id
    )


def scoped_audit_task(db: Session, user: User, task_id: str) -> SettlementTask | None:
    return db.scalar(audit_task_scope_query(user).where(SettlementTask.task_id == task_id))
