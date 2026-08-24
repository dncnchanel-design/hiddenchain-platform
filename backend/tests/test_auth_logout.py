from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditLog


def test_logout_revokes_current_token_only_and_writes_audit(client, auth_headers):
    headers = auth_headers["generator"]

    before = client.get("/api/auth/me", headers=headers)
    assert before.status_code == 200, before.text

    logged_out = client.post("/api/auth/logout", headers=headers)
    assert logged_out.status_code == 204, logged_out.text
    assert logged_out.content == b""

    revoked = client.get("/api/auth/me", headers=headers)
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "登录已退出，请重新登录"

    fresh_login = client.post(
        "/api/auth/login",
        json={"username": "generator", "password": "generator123"},
    )
    assert fresh_login.status_code == 200, fresh_login.text
    fresh_headers = {"Authorization": f"Bearer {fresh_login.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=fresh_headers).status_code == 200

    with SessionLocal() as db:
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.action_code == "LOGOUT")
            .order_by(AuditLog.occurred_at.desc())
        )
        assert audit is not None
        assert audit.actor_name == "发电企业账户"
        assert audit.result == "SUCCESS"
