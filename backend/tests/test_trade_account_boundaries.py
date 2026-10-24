from __future__ import annotations

import pytest


def _payload(client, headers):
    rule = client.get("/api/rules", headers=headers).json()[0]
    return {
        "task_name": "账号流程验收",
        "trade_batch_no": "QA-2026-10-24",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "rule_id": rule["rule_id"],
        "participants": [
            {"org_id": "org-generator-t01", "role_in_task": "GENERATOR"},
            {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"},
        ],
    }


@pytest.mark.parametrize("account", ["exchange_coal", "exchange_heat", "exchange_gas", "exchange_oil"])
def test_non_electric_exchange_cannot_create_an_electricity_settlement(client, auth_headers, account):
    from app.security import create_access_token
    payload = _payload(client, auth_headers["exchange"])
    domain = account.split("_", 1)[1]
    headers = {"Authorization": "Bearer " + create_access_token(f"user-exchange-{domain}", "EXCHANGE", f"org-exchange-{domain}-t01")}
    response = client.post("/api/settlement/tasks", json=payload, headers=headers)
    assert response.status_code == 403, response.text


def test_idempotency_replay_cannot_expose_a_task_from_another_organization(client, auth_headers):
    from app.database import SessionLocal
    from app.models import Organization, User
    from app.security import create_access_token

    key = "account-boundary-create-task"
    payload = _payload(client, auth_headers["exchange"])
    response = client.post("/api/settlement/tasks", json=payload, headers={**auth_headers["exchange"], "Idempotency-Key": key})
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        org = Organization(org_id="org-other-exchange", org_name="另一电力交易中心", org_type="EXCHANGE", energy_domain="electricity", credit_code="QA-OTHER-EXCHANGE", status="ACTIVE")
        db.add(org)
        db.flush()
        user = User(user_id="user-other-exchange", org_id=org.org_id, username="other_exchange", password_hash="unused", display_name="另一交易中心", role_code="EXCHANGE", status="ACTIVE", permissions_json=["CREATE_COMPUTE_TASK"])
        db.add(user)
        db.commit()
    other_headers = {"Authorization": "Bearer " + create_access_token("user-other-exchange", "EXCHANGE", "org-other-exchange"), "Idempotency-Key": key}
    other = client.post("/api/settlement/tasks", json=payload, headers=other_headers)
    assert other.status_code in {403, 409}, other.text
    assert response.json()["task_id"] not in other.text
