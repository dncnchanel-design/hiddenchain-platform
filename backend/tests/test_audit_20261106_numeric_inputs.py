"""Boundary inputs must not persist unusable rules or escape validation."""
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import SettlementRule


RULE = {
    "rule_name": "数值边界复查",
    "contract_price": 420,
    "deviation_threshold_mwh": 100,
    "deviation_penalty_rate": 150,
    "service_fee_rate": 3.2,
}


@pytest.mark.parametrize("field", ["contract_price", "deviation_threshold_mwh", "deviation_penalty_rate", "service_fee_rate"])
@pytest.mark.parametrize("value", ["Infinity", "1e10000"])
def test_nonfinite_rule_parameters_are_rejected_without_polluting_rule_list(client, auth_headers, field, value):
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(SettlementRule))
    # Observe the real HTTP response instead of allowing JSON render errors to
    # short-circuit the persistence and catalog assertions below.
    with TestClient(client.app, raise_server_exceptions=False) as observed:
        response = observed.post("/api/rules", headers=auth_headers["exchange"], json={**RULE, field: value})
        listed = observed.get("/api/rules", headers=auth_headers["exchange"])
    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(SettlementRule))
    assert (response.status_code, listed.status_code, after) == (422, 200, before)


@pytest.mark.parametrize("asset_type,payload", [
    ("GENERATION_DATA", {"period": "2026-11", "energy_mwh": 10 ** 400}),
    ("USER_LOAD_CURVE", {"period": "2026-11", "load_curve": [10 ** 400] + [1] * 23}),
])
def test_oversized_integer_upload_is_a_validation_error(client, auth_headers, asset_type, payload):
    role = "generator" if asset_type == "GENERATION_DATA" else "retailer"
    with TestClient(client.app, raise_server_exceptions=False) as observed:
        response = observed.post("/api/data/uploads", headers=auth_headers[role], json={
            "asset_type": asset_type, "trade_batch_no": "NUMERIC-INPUT-AUDIT",
            "label": "超限整数输入", "local_payload": payload,
        })
    assert response.status_code == 422, response.text


def test_finite_rule_parameters_still_create_a_readable_rule(client, auth_headers):
    response = client.post("/api/rules", headers=auth_headers["exchange"], json=RULE)
    assert response.status_code == 201, response.text
    assert response.json()["parameters_json"]["contract_price"] == 420
    listed = client.get("/api/rules", headers=auth_headers["exchange"])
    assert listed.status_code == 200
    assert response.json()["rule_id"] in {item["rule_id"] for item in listed.json()}
