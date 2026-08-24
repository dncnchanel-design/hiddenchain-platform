from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from .database import get_db
from .models import Organization, RevokedAccessToken, User
from .security import access_token_digest, decode_access_token


bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或登录已失效")
    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效访问令牌") from exc
    revoked = db.get(RevokedAccessToken, access_token_digest(credentials.credentials))
    if revoked is not None and revoked.expires_at > datetime.now(UTC).replace(tzinfo=None):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已退出，请重新登录")
    user = db.get(User, payload.get("sub"))
    if user is None or user.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    organization = db.get(Organization, user.org_id)
    if organization is None or organization.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="所属组织不可用")
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role_code not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权执行此操作")
        return user

    return dependency


BUSINESS_ROLES = (
    "GENERATOR",
    "RETAILER",
    "COAL_ENTERPRISE",
    "HEAT_ENTERPRISE",
    "GAS_ENTERPRISE",
    "OIL_ENTERPRISE",
    "EXCHANGE",
    "REGULATOR",
)
