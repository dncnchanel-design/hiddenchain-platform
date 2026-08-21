from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import User
from ..schemas import AssistantExecuteRequest, AssistantMessageCreate, AssistantSessionCreate
from ..services import assistant as assistant_service


router = APIRouter(prefix="/trust-space/assistant", tags=["trust-space-assistant"])


def _assistant_error(exc: Exception) -> None:
    code = str(exc)
    if code.endswith("_NOT_FOUND"):
        status_code = status.HTTP_404_NOT_FOUND
    elif code.endswith("_SCOPE_DENIED") or code.endswith("_FORBIDDEN") or code.endswith("_DENIED"):
        status_code = status.HTTP_403_FORBIDDEN
    elif code == "ASSISTANT_IF_MATCH_REQUIRED":
        status_code = status.HTTP_428_PRECONDITION_REQUIRED
    elif code in {"ASSISTANT_IF_MATCH_INVALID", "ASSISTANT_VERSION_CONFLICT"}:
        status_code = status.HTTP_412_PRECONDITION_FAILED
    elif code in {
        "ASSISTANT_SESSION_NOT_ACTIVE",
        "ASSISTANT_PLAN_ALREADY_SUCCEEDED",
        "ASSISTANT_PLAN_NOT_RETRYABLE",
    }:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": code},
    ) from exc


def _with_etag(response: Response, payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key, {}).get("state_version")
    if value is not None:
        response.headers["ETag"] = f'"{value}"'
    return payload


def _call(function: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return function(*args, **kwargs)
    except (LookupError, PermissionError, ValueError) as exc:
        _assistant_error(exc)
    raise AssertionError("unreachable")


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    payload: AssistantSessionCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = _call(
        assistant_service.create_session,
        db,
        user,
        page_path=payload.page_path,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        idempotency_key=idempotency_key,
    )
    response.headers["ETag"] = f'"{result["state_version"]}"'
    if result.get("idempotent_replay"):
        response.status_code = status.HTTP_200_OK
    return result


@router.post("/sessions/{session_id}/resume")
def resume_session(
    session_id: str,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = _call(assistant_service.resume_session, db, session_id, user, if_match=if_match)
    response.headers["ETag"] = f'"{result["state_version"]}"'
    return result


@router.get("/sessions/{session_id}/messages")
def list_messages(
    session_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _call(assistant_service.list_messages, db, session_id, user)


@router.get("/sessions/{session_id}/plans")
def list_plans(
    session_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _call(assistant_service.list_plans, db, session_id, user)


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_201_CREATED)
def post_message(
    session_id: str,
    payload: AssistantMessageCreate,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = _call(
        assistant_service.post_message,
        db,
        session_id,
        user,
        content=payload.content,
        if_match=if_match,
        idempotency_key=idempotency_key,
    )
    response.headers["ETag"] = f'"{result["session"]["state_version"]}"'
    if result.get("message", {}).get("idempotent_replay"):
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/tools")
def tool_catalog(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _call(assistant_service.tool_catalog, db, user)


@router.get("/sessions/{session_id}/plans/{plan_id}")
def plan_status(
    session_id: str,
    plan_id: str,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _call(assistant_service.plan_status, db, session_id, plan_id, user)


@router.post("/sessions/{session_id}/plans/{plan_id}/execute")
def execute_plan(
    session_id: str,
    plan_id: str,
    payload: AssistantExecuteRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = _call(
        assistant_service.execute_plan,
        db,
        session_id,
        plan_id,
        user,
        step_id=payload.step_id,
        if_match=if_match,
    )
    return _with_etag(response, result, "plan")


@router.post("/sessions/{session_id}/plans/{plan_id}/cancel")
def cancel_plan(
    session_id: str,
    plan_id: str,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = _call(
        assistant_service.cancel_plan,
        db,
        session_id,
        plan_id,
        user,
        if_match=if_match,
    )
    return _with_etag(response, result, "plan")


@router.post("/sessions/{session_id}/plans/{plan_id}/retry")
def retry_plan(
    session_id: str,
    plan_id: str,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = _call(
        assistant_service.retry_plan,
        db,
        session_id,
        plan_id,
        user,
        if_match=if_match,
    )
    return _with_etag(response, result, "plan")
