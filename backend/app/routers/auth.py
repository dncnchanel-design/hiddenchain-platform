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


MODULES = [
    {"code": "overview", "path": "/overview", "roles": ["ADMIN"]},
    {"code": "workbench", "path": "/workbench", "roles": ["GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "generation-data", "path": "/data/generation", "roles": ["GENERATOR", "EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "retail-data", "path": "/data/retail", "roles": ["RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "data-space", "path": "/data-space", "roles": ["GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "trusted-execution", "path": "/trusted-execution", "roles": ["EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "rules", "path": "/rules", "roles": ["EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "settlements", "path": "/settlements", "roles": ["GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "compute", "path": "/compute", "roles": ["GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "results", "path": "/results", "roles": ["GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "evidence", "path": "/evidence", "roles": ["GENERATOR", "RETAILER", "EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "audit", "path": "/audit", "roles": ["EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "agents", "path": "/agents", "roles": ["ADMIN"]},
    {"code": "anomalies", "path": "/anomalies", "roles": ["EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "logs", "path": "/logs", "roles": ["ADMIN"]},
    {"code": "system", "path": "/system", "roles": ["ADMIN"]},
    {"code": "reports", "path": "/reports", "roles": ["EXCHANGE", "REGULATOR", "ADMIN"]},
    {"code": "metrics", "path": "/metrics", "roles": ["ADMIN"]},
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
        "status": user.status,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }
    return {
        "user": public_user,
        "org": model_dict(org) if org else None,
        "did": model_dict(did) if did else None,
        "menus": [item for item in MODULES if user.role_code in item["roles"]],
        "field_scopes": {
            "raw_data": "OWN_ORG_ONLY" if user.role_code in {"GENERATOR", "RETAILER"} else "NONE",
            "settlement_result": "OWN_ORG_ONLY" if user.role_code in {"GENERATOR", "RETAILER"} else "AUTHORIZED_ALL",
            "audit_evidence": "FULL" if user.role_code == "REGULATOR" else "ROLE_SCOPED",
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
