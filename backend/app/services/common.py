from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def trace_id() -> str:
    # Reuse the active OpenTelemetry trace when the optional instrumentation is
    # enabled, so the database audit record and an external trace can be
    # correlated without putting request payloads into telemetry.
    try:
        from opentelemetry import trace

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            return f"trace-{span_context.trace_id:032x}"
    except (ImportError, AttributeError, RuntimeError):
        pass
    try:
        from asgi_correlation_id import correlation_id

        request_id = correlation_id.get()
        if request_id:
            return f"trace-{request_id}"
    except (ImportError, AttributeError, RuntimeError):
        pass
    return f"trace-{uuid.uuid4().hex[:20]}"


def add_audit_log(
    db: Session,
    *,
    action: str,
    target_type: str,
    target_id: str,
    result: str,
    user: User | None = None,
    actor_name: str | None = None,
    actor_org_id: str | None = None,
    details: dict[str, Any] | None = None,
    current_trace_id: str | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=user.user_id if user else None,
        actor_org_id=user.org_id if user else actor_org_id,
        actor_name=user.display_name if user else actor_name or "SYSTEM",
        action_code=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        trace_id=current_trace_id or trace_id(),
        details_json=details or {},
    )
    db.add(log)
    return log


def model_dict(model: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        result[column.name] = value
    return result
