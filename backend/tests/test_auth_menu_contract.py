from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User


def test_audit_menu_requires_both_regulator_role_and_current_permission(client, auth_headers):
    generator = client.get("/api/auth/me", headers=auth_headers["generator"])
    assert generator.status_code == 200, generator.text
    assert not any(item["code"] == "audit" for item in generator.json()["menus"])

    with SessionLocal() as db:
        regulator = db.scalar(select(User).where(User.username == "regulator"))
        assert regulator is not None
        regulator.permissions_json = [
            permission
            for permission in regulator.permissions_json or []
            if permission != "VIEW_AUDIT"
        ]
        db.commit()

    response = client.get("/api/auth/me", headers=auth_headers["regulator"])
    assert response.status_code == 200, response.text
    menu_codes = {item["code"] for item in response.json()["menus"]}
    assert "audit" not in menu_codes
    assert {"overview", "query", "catalog", "authorization", "compute", "participants"} <= menu_codes
