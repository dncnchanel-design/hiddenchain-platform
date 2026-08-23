from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import get_current_user
from ..models import DidIdentity, Organization, User, utc_now
from ..schemas import LoginRequest
from ..security import create_access_token, verify_password
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

MODULES = [
    {"code": "overview", "path": "/trusted-space/workbench", "roles": BUSINESS_ROLES},
    {"code": "query", "path": "/trusted-space/query", "roles": BUSINESS_ROLES},
    {"code": "catalog", "path": "/trusted-space/catalog", "roles": BUSINESS_ROLES},
    {"code": "connector", "path": "/trusted-space/connector", "roles": [role for role in BUSINESS_ROLES if role != "REGULATOR"]},
    {"code": "authorization", "path": "/trusted-space/authorizations", "roles": BUSINESS_ROLES},
    {"code": "compute", "path": "/trusted-space/mpc", "roles": BUSINESS_ROLES},
    {"code": "audit", "path": "/trusted-space/audit", "roles": BUSINESS_ROLES},
    {"code": "participants", "path": "/trusted-space/identity", "roles": BUSINESS_ROLES},
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
