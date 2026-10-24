import pytest


@pytest.mark.parametrize("account", ["exchange_coal", "exchange_heat", "exchange_gas", "exchange_oil"])
def test_unconfigured_connector_has_readable_capability_without_upload_permission(client, auth_headers, account):
    from app.seed import USERS
    row = next(item for item in USERS if item[2] == account)
    login = client.post("/api/auth/login", json={"username": account, "password": row[3]})
    assert login.status_code == 200
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    response = client.get("/api/trust-space/connectors/catalog", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["connector"]["capability_state"] == "BLOCKED"
    assert payload["availability"]["can_upload"] is False
    assert payload["availability"]["reason"]
    assert payload["resources"] == []
    assert payload["connector"]["endpoint"] == ""
    ticket = client.post("/api/trust-space/connectors/tickets", headers=headers, json={"resource_id": "price"})
    assert ticket.status_code == 503
