from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import bearer, get_current_user
from ..models import DidIdentity, Organization, RevokedAccessToken, User, utc_now
from ..schemas import LoginRequest
from ..security import access_token_digest, create_access_token, decode_access_token, verify_password
from ..services.common import add_audit_log, model_dict
from ..services.rate_limit import limiter


router = APIRouter(prefix="/auth", tags=["auth"])


BUSINESS_ROLES = [
    "GENERATOR",
    "RETAILER",
    "COAL_ENTERPRISE",
    "HEAT_ENTERPRISE",
    "GAS_ENTERPRISE",
    "OIL_ENTERPRISE",
    "EXCHANGE",
    "REGULATOR",
]
APP_ROLES = [*BUSINESS_ROLES, "ADMIN"]
REVIEW_ROLES = ["EXCHANGE", "REGULATOR", "ADMIN"]

MODULES = [
    {"code": "overview", "path": "/trusted-space/workbench", "roles": BUSINESS_ROLES},
    {"code": "query", "path": "/trusted-space/query", "roles": BUSINESS_ROLES},
    {"code": "catalog", "path": "/trusted-space/catalog", "roles": BUSINESS_ROLES},
    {"code": "connector", "path": "/trusted-space/connector", "roles": [role for role in BUSINESS_ROLES if role != "REGULATOR"]},
    {"code": "authorization", "path": "/trusted-space/authorizations", "roles": BUSINESS_ROLES},
    {"code": "compute", "path": "/trusted-space/mpc", "roles": BUSINESS_ROLES},
    {"code": "audit", "path": "/trusted-space/audit", "roles": ["REGULATOR"]},
    {"code": "participants", "path": "/trusted-space/identity", "roles": BUSINESS_ROLES},
    {"code": "workbench", "path": "/workbench", "roles": APP_ROLES},
    {"code": "data-space", "path": "/data-space", "roles": APP_ROLES},
    {"code": "rules", "path": "/rules", "roles": REVIEW_ROLES},
    {"code": "compute", "path": "/compute", "roles": APP_ROLES},
    {"code": "settlements", "path": "/settlements", "roles": APP_ROLES},
    {"code": "results", "path": "/results", "roles": APP_ROLES},
    {"code": "evidence", "path": "/evidence", "roles": APP_ROLES},
    {"code": "audit", "path": "/audit", "roles": REVIEW_ROLES},
    {"code": "reports", "path": "/reports", "roles": REVIEW_ROLES},
    {"code": "anomalies", "path": "/anomalies", "roles": REVIEW_ROLES},
    {"code": "trusted-execution", "path": "/trusted-execution", "roles": REVIEW_ROLES},
    {"code": "overview", "path": "/overview", "roles": ["ADMIN"]},
    {"code": "system", "path": "/system", "roles": ["ADMIN"]},
    {"code": "agents", "path": "/agents", "roles": ["ADMIN"]},
    {"code": "metrics", "path": "/metrics", "roles": ["ADMIN"]},
    {"code": "logs", "path": "/logs", "roles": ["ADMIN"]},
]


def _user_payload(db: Session, user: User) -> dict:
    org = db.get(Organization, user.org_id)
    did = db.scalar(select(DidIdentity).where(DidIdentity.owner_id == user.org_id))
    public_user = {
        "user_id": user.user_id,
        "org_id": user.org_id,
        "username": user.username,
        "display_name": user.display_name,
        "role_code": user.role_code,
        "permissions": list(user.permissions_json or []),
        "is_org_owner": bool(user.is_org_owner),
        "status": user.status,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }
    return {
        "user": public_user,
        "org": model_dict(org) if org else None,
        "did": model_dict(did) if did else None,
        "menus": [item for item in MODULES if user.role_code in item["roles"]],
        "field_scopes": {
            "raw_data": "ENTERPRISE_CONNECTOR_ONLY" if user.role_code != "ADMIN" else "NONE",
            "result": "AUTHORIZED_SCOPE_ONLY" if user.role_code != "ADMIN" else "NONE",
            "audit_evidence": "AUTHORIZED_SCOPE_ONLY" if user.role_code != "ADMIN" else "SANITIZED_OPERATIONS_ONLY",
        },
    }


@router.post("/login")
@limiter.limit(settings.auth_login_rate_limit)
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        add_audit_log(
            db,
            action="LOGIN",
            target_type="USER",
            target_id=payload.username,
            result="FAILED",
            actor_name=payload.username,
            details={"reason": "INVALID_CREDENTIALS"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    user.last_login_at = utc_now()
    add_audit_log(
        db,
        action="LOGIN",
        target_type="USER",
        target_id=user.user_id,
        result="SUCCESS",
        user=user,
        details={"role": user.role_code},
    )
    db.commit()
    return {
        "access_token": create_access_token(user.user_id, user.role_code, user.org_id),
        "token_type": "bearer",
        **_user_payload(db, user),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return _user_payload(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已失效")
    try:
        payload = decode_access_token(credentials.credentials)
        expires_at = datetime.fromtimestamp(float(payload["exp"]), UTC).replace(tzinfo=None)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效访问令牌") from exc

    token_hash = access_token_digest(credentials.credentials)
    if db.get(RevokedAccessToken, token_hash) is None:
        db.add(
            RevokedAccessToken(
                token_hash=token_hash,
                user_id=user.user_id,
                expires_at=expires_at,
            )
        )
        add_audit_log(
            db,
            action="LOGOUT",
            target_type="USER",
            target_id=user.user_id,
            result="SUCCESS",
            user=user,
            details={"reason": "USER_REQUEST"},
        )
        db.commit()
