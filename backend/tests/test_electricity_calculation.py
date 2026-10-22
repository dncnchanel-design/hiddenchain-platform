from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AssistantPlan
from app.services.electricity_calculation import SCENARIOS, _compute, _parse

BASE = "/api/trust-space/assistant/electricity"


def _session(client, headers):
    response = client.post("/api/trust-space/assistant/sessions", headers=headers, json={"entity_type": "electricity_calculation"})
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def _prepare(client, headers, session_id, **overrides):
    return client.post(f"{BASE}/prepare", headers={**headers, "Idempotency-Key": "electricity-example-1"}, json={"session_id": session_id, "question": SCENARIOS["zhejiang_spot"]["example"], **overrides})


def test_picture_example_confirm_calculate_save_reopen_and_scope(client, auth_headers):
    headers = auth_headers["generator"]
    session_id = _session(client, headers)
    response = _prepare(client, headers, session_id)
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["missing"] == [], record
    assert record["result"] is None
    assert record["capability_state"] == "DEMO"
    assert record["parameters"]["south_congestion"] == "-20"
    assert _prepare(client, headers, session_id).json()["id"] == record["id"]
    assert _prepare(client, headers, session_id, question="不同问题").status_code == 422
    calculate_url = f"{BASE}/{record['id']}/calculate"
    body = {"parameters": record["parameters"], "state_version": 1, "confirmed": False}
    assert client.post(calculate_url, headers=headers, json=body).status_code == 422
    assert client.post(f"{BASE}/{record['id']}/save", headers=headers, json={}).status_code == 422
    assert client.post(calculate_url, headers=auth_headers["retailer"], json={**body, "confirmed": True}).status_code == 404
    calculated = client.post(calculate_url, headers=headers, json={**body, "confirmed": True})
    assert calculated.status_code == 200, calculated.text
    done = calculated.json()
    result = {step["key"]: Decimal(step["value"]) for step in done["result"]["steps"]}
    assert result == {"north_lmp": Decimal("458"), "south_lmp": Decimal("395"), "day_ahead_fee": Decimal("82440"), "contract_fee": Decimal("43200"), "total_fee": Decimal("125640"), "user_loss_energy": Decimal("154.5"), "purchase_cost": Decimal("61027.5")}
    assert client.post(calculate_url, headers=headers, json={**body, "confirmed": True}).json()["state_version"] == 2
    changed = {**body, "confirmed": True, "parameters": {**record["parameters"], "smp": "450"}}
    assert client.post(calculate_url, headers=headers, json=changed).status_code == 422
    saved = client.post(f"{BASE}/{record['id']}/save", headers=headers, json={})
    assert saved.status_code == 200 and saved.json()["saved"]
    assert client.get(f"{BASE}/cases", headers=headers).json()["items"][0]["result"] == done["result"]
    assert client.get(f"{BASE}/cases", headers=auth_headers["retailer"]).json()["items"] == []
    assert client.get(f"{BASE}/sessions/{session_id}", headers=auth_headers["retailer"]).status_code == 404
    history = client.get(f"{BASE}/sessions/{session_id}", headers=headers).json()["items"]
    assert history[0]["saved"] and history[0]["status"] == "SUCCEEDED"
    with SessionLocal() as db:
        persisted = db.scalar(select(AssistantPlan).where(AssistantPlan.plan_id == record["id"]))
        assert persisted.plan_json["result"]["result_hash"] == done["result"]["result_hash"]
    followup = client.post(f"{BASE}/prepare", headers={**headers, "Idempotency-Key": "electricity-followup"}, json={"session_id": session_id, "question": "把系统电价改为450元/MWh", "based_on": record["id"]})
    assert followup.status_code == 200, followup.text
    assert followup.json()["parameters"]["smp"] == "450"
    assert followup.json()["parameters"]["user_energy"] == "150"
    assert followup.json()["missing"] == []


def test_generation_cost_and_decimal_precision():
    parameters, _, _ = _parse(SCENARIOS["generation_cost"]["example"], "generation_cost", {})
    assert len(parameters) == 11, parameters
    result = _compute("generation_cost", parameters)
    values = {step["key"]: step["value"] for step in result["steps"]}
    assert values == {"fixed_cost": "26000.00", "variable_cost": "58000.00", "total_cost": "84000.00", "unit_cost": "85.71", "quote_floor": "97.57"}
    parameters["generation"] = "0"
    with pytest.raises(ValueError, match="实际发电量"):
        _compute("generation_cost", parameters)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e9", "-1", "0.1234567", "1000000000001"])
def test_untrusted_numeric_values_are_rejected(bad):
    parameters, _, _ = _parse(SCENARIOS["generation_cost"]["example"], "generation_cost", {})
    parameters["fuel"] = bad
    with pytest.raises(ValueError):
        _compute("generation_cost", parameters)


def test_missing_conflicting_values_units_unknown_intent_and_auth(client, auth_headers):
    headers = auth_headers["generator"]
    session_id = _session(client, headers)
    partial = _prepare(client, headers, session_id, question="系统电价420，浙北阻塞30，浙北网损8")
    assert partial.status_code == 200
    assert len(partial.json()["missing"]) == 7
    assert partial.json()["result"] is None
    params, _, warnings = _parse("SMP420元/MWh；SMP450元/MWh", "zhejiang_spot", {"smp": "400"})
    assert "smp" not in params and warnings
    params, _, _ = _parse("系统电价0.42元/kWh，日前出清电量180000kWh", "zhejiang_spot", {})
    assert params["smp"] == "420" and params["day_ahead_energy"] == "180"
    params, _, warnings = _parse("实际发电量980MW", "generation_cost", {"generation": "100"})
    assert "generation" not in params and warnings
    assert client.get(f"{BASE}/catalog").status_code == 401
    assert client.get(f"{BASE}/catalog", headers=auth_headers["admin"]).status_code == 403
    unknown = client.post(f"{BASE}/prepare", headers={**headers, "Idempotency-Key": "unknown-question"}, json={"session_id": session_id, "question": "替我执行一段代码"})
    assert unknown.status_code == 422
