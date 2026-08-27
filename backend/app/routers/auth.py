from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import bearer, get_current_user
from ..models import DidIdentity, DidLoginChallenge, Organization, RevokedAccessToken, User, utc_now
from ..schemas import DidLoginChallengeRequest, DidLoginVerifyRequest, LoginRequest
from ..security import access_token_digest, create_access_token, decode_access_token, verify_password
from ..services.common import add_audit_log, model_dict
from ..services.did_login import (
    DidWalletConfigurationError,
    challenge_message,
    configured_did_for_wallet,
    normalize_wallet_address,
    recover_wallet_address,
)
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


def _did_login_host(request: Request) -> str:
    return (request.headers.get("host") or request.url.hostname or "hiddenchain").split(",", 1)[0].strip()


def _did_login_failure(db: Session, wallet_address: str, reason: str) -> None:
    add_audit_log(
        db,
        action="LOGIN_DID",
        target_type="DID_WALLET",
        target_id=wallet_address,
        result="FAILED",
        actor_name=wallet_address,
        details={"reason": reason},
    )
    db.commit()


@router.post("/did/challenge")
@limiter.limit(settings.auth_login_rate_limit)
def did_login_challenge(
    request: Request,
    payload: DidLoginChallengeRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        wallet_address = normalize_wallet_address(payload.wallet_address)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "DID_WALLET_ADDRESS_INVALID", "message": "钱包地址格式无效"},
        ) from exc

    issued_at = utc_now()
    expires_at = issued_at + timedelta(minutes=max(1, settings.did_login_challenge_minutes))
    challenge = secrets.token_urlsafe(32)
    message = challenge_message(
        host=_did_login_host(request),
        wallet_address=wallet_address,
        challenge=challenge,
        expires_at=expires_at,
    )
    db.execute(delete(DidLoginChallenge).where(DidLoginChallenge.expires_at <= issued_at))
    db.add(
        DidLoginChallenge(
            challenge=challenge,
            wallet_address=wallet_address,
            message=message,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    )
    db.commit()
    return {
        "challenge": challenge,
        "wallet_address": wallet_address,
        "message": message,
        "expires_at": expires_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
    }


@router.post("/did/verify")
@limiter.limit(settings.auth_login_rate_limit)
def did_login_verify(
    request: Request,
    payload: DidLoginVerifyRequest,
    db: Session = Depends(get_db),
) -> dict:
    del request
    try:
        wallet_address = normalize_wallet_address(payload.wallet_address)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "DID_WALLET_ADDRESS_INVALID", "message": "钱包地址格式无效"},
        ) from exc

    challenge = db.scalar(
        select(DidLoginChallenge).where(
            DidLoginChallenge.challenge == payload.challenge,
            DidLoginChallenge.wallet_address == wallet_address,
        )
    )
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "DID_LOGIN_CHALLENGE_INVALID", "message": "DID 登录挑战不存在或已失效"},
        )
    now = utc_now()
    if challenge.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DID_LOGIN_CHALLENGE_USED", "message": "DID 登录挑战只能使用一次"},
        )
    if challenge.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "DID_LOGIN_CHALLENGE_EXPIRED", "message": "DID 登录挑战已过期，请重新连接钱包"},
        )

    try:
        recovered_address = recover_wallet_address(challenge.message, payload.signature)
    except (TypeError, ValueError, OverflowError):
        _did_login_failure(db, wallet_address, "INVALID_SIGNATURE")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "DID_LOGIN_SIGNATURE_INVALID", "message": "钱包签名验证失败"},
        ) from None
    if recovered_address != wallet_address:
        _did_login_failure(db, wallet_address, "SIGNER_MISMATCH")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "DID_LOGIN_SIGNATURE_INVALID", "message": "钱包签名与登录地址不一致"},
        )

    consumed = db.execute(
        update(DidLoginChallenge)
        .where(
            DidLoginChallenge.challenge == challenge.challenge,
            DidLoginChallenge.used_at.is_(None),
        )
        .values(used_at=now)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DID_LOGIN_CHALLENGE_USED", "message": "DID 登录挑战只能使用一次"},
        )

    try:
        configured_did = configured_did_for_wallet(
            settings.did_wallet_bindings_json,
            wallet_address,
        )
    except DidWalletConfigurationError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DID_WALLET_CONFIGURATION_INVALID", "message": "DID 钱包绑定配置无效"},
        ) from None

    identity = (
        db.get(DidIdentity, configured_did)
        if configured_did
        else db.scalar(
            select(DidIdentity)
            .where(
                DidIdentity.credential_status == "VALID",
                func.lower(DidIdentity.chain_address) == wallet_address,
            )
            .order_by(DidIdentity.created_at, DidIdentity.did_id)
        )
    )
    if identity is None or identity.credential_status != "VALID" or not identity.org_id:
        _did_login_failure(db, wallet_address, "WALLET_NOT_REGISTERED")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "DID_WALLET_NOT_REGISTERED", "message": "该钱包尚未登记到有效企业 DID"},
        )
    if identity.chain_address != wallet_address:
        identity.chain_address = wallet_address

    organization = db.get(Organization, identity.org_id)
    user = db.scalar(
        select(User)
        .where(
            User.org_id == identity.org_id,
            User.is_org_owner.is_(True),
            User.status == "ACTIVE",
        )
        .order_by(User.created_at, User.user_id)
    )
    if organization is None or organization.status != "ACTIVE" or user is None:
        _did_login_failure(db, wallet_address, "SUBJECT_NOT_ACTIVE")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "DID_LOGIN_SUBJECT_UNAVAILABLE", "message": "DID 所属主体当前不可登录"},
        )

    user.last_login_at = now
    add_audit_log(
        db,
        action="LOGIN_DID",
        target_type="DID_WALLET",
        target_id=identity.did_id,
        result="SUCCESS",
        user=user,
        details={"wallet_address": wallet_address},
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
