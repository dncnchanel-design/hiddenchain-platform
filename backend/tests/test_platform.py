from __future__ import annotations


def test_login_response_never_exposes_password_hash(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "exchange", "password": "exchange123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert "password_hash" not in payload["user"]
    assert "password" not in str(payload["user"]).lower()


def test_role_and_data_domain_boundaries(client, auth_headers):
    forbidden = client.get("/api/system/users", headers=auth_headers["generator"])
    assert forbidden.status_code == 403

    own_data = client.get(
        "/api/data/uploads?asset_type=GENERATION_DATA",
        headers=auth_headers["generator"],
    )
    assert own_data.status_code == 200
    assert own_data.json()
    assert all(item["owner_org_id"] == "org-generator-demo" for item in own_data.json())
    assert all(item["raw_payload_exposed"] is False for item in own_data.json())
    assert all("energy_mwh" not in item for item in own_data.json())

    denied_upload = client.post(
        "/api/data/uploads",
        headers=auth_headers["generator"],
        json={
            "asset_type": "RETAIL_DATA",
            "trade_batch_no": "TB-DENIED-001",
            "label": "越权数据",
            "local_payload": {"energy_mwh": 10},
        },
    )
    assert denied_upload.status_code == 403


def test_complete_agent_native_settlement_workflow(client, auth_headers):
    response = client.post(
        "/api/settlement/tasks/task-ready-demo/run",
        headers=auth_headers["exchange"],
        json={"compute_mode": "MPC_MOCK", "algorithm_code": "SETTLEMENT_MPC_V1"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["task"]["status"] == "AUDITED"
    assert result["task"]["risk_level"] == "LOW"
    assert result["compute_job"]["status"] == "SUCCESS"
    assert result["compute_job"]["raw_data_exposed"] is False
    assert len(result["results"]) >= 2
    assert len(result["evidence"]) >= 4
    assert result["report"]["conclusion"] == "PASS"
    coordination = result["task"]["scenario_coordination"]
    assert {item["code"] for item in coordination} == {
        "RENEWABLE_CONSUMPTION",
        "MARKET_TRADING",
        "VPP_OPERATION",
        "GRID_DISPATCH",
    }
    assert all(item["status"] == "PASSED" for item in coordination)
    assert result["compute_job"]["result_json"]["gross_deviation_mwh"] > result["compute_job"]["result_json"]["deviation_mwh"]

    events = client.get(
        "/api/agents/events?task_id=task-ready-demo",
        headers=auth_headers["exchange"],
    )
    assert events.status_code == 200
    event_codes = {item["agent_code"] for item in events.json()}
    assert {
        "ORCHESTRATOR",
        "DATA_ACCESS",
        "RULE_CONTRACT",
        "SECURE_SETTLEMENT",
        "AUDIT_RISK",
        "REPORT_EXPLAIN",
    }.issubset(event_codes)

    evidence = client.get(
        "/api/chain/evidence?task_id=task-ready-demo",
        headers=auth_headers["regulator"],
    ).json()
    assert {item["stage"] for item in evidence} >= {"PRE_COMPUTE", "IN_COMPUTE", "POST_COMPUTE"}
    for item in evidence:
        verification = client.get(
            f"/api/chain/evidence/{item['evidence_id']}/verify",
            headers=auth_headers["regulator"],
        )
        assert verification.status_code == 200
        assert verification.json()["matched"] is True


def test_privacy_analysis_returns_only_aggregate_results(client, auth_headers):
    response = client.post(
        "/api/privacy/analysis/jobs",
        headers=auth_headers["retailer"],
        json={
            "analysis_name": "园区负荷聚合分析",
            "dataset_ids": ["upload-load-curve-a", "upload-load-curve-b"],
            "analysis_type": "DR_POTENTIAL",
            "privacy_level": "DIFFERENTIAL_PRIVACY",
            "privacy_budget": 1.0,
        },
    )
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "SUCCESS"
    assert job["raw_records_returned"] is False
    assert len(job["result_json"]["aggregate_curve"]) == 24
    assert "load_curve" not in str(job["result_json"])
    assert job["result_json"]["compute_strategy"]["primary"] == "SECRET_SHARING_HE"


def test_dashboard_exposes_four_scenario_and_four_chain_operating_state(client, auth_headers):
    response = client.get("/api/dashboard/summary", headers=auth_headers["exchange"])
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["scenario_coordination"]) == 4
    assert {item["code"] for item in payload["four_chain_fusion"]} == {
        "DID",
        "PRIVACY",
        "BLOCKCHAIN",
        "AGENT",
    }

    catalog = client.get("/api/privacy/strategy/catalog", headers=auth_headers["exchange"])
    assert catalog.status_code == 200
    assert {item["scenario_code"] for item in catalog.json()} == {
        "RENEWABLE_FORECAST",
        "MARKET_SETTLEMENT",
        "VPP_AGGREGATION",
        "GRID_SECURITY_CHECK",
    }


def test_data_space_catalog_and_protocol_are_visible(client, auth_headers):
    catalog = client.get(
        "/api/data/catalog?trade_batch_no=TB-2026-07-DEMO",
        headers=auth_headers["exchange"],
    )
    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload["protocol_version"] == "HCDS-1.0"
    assert payload["raw_data_exposed"] is False
    assert "USER_LOAD_CURVE" in payload["supported_asset_types"]
    assert {item["asset_type"] for item in payload["entries"]} >= {
        "GENERATION_DATA",
        "RETAIL_DATA",
        "RENEWABLE_FORECAST",
        "VPP_RESOURCE",
        "GRID_CONSTRAINT",
    }
    assert all(item["data_product_id"].startswith("DP-") for item in payload["entries"])
    assert all(item["semantic_ref"].startswith("energy:") for item in payload["entries"])

    protocol = client.get("/api/data-space/protocol", headers=auth_headers["regulator"])
    assert protocol.status_code == 200
    protocol_payload = protocol.json()
    assert "CONTRACT_NEGOTIATION" in protocol_payload["capabilities"]
    assert "USAGE_CONTROL" in protocol_payload["capabilities"]
    assert protocol_payload["raw_data_transferred"] is False


def test_settlement_records_connector_agreements_and_enforces_usage_control(client, auth_headers):
    response = client.post(
        "/api/settlement/tasks/task-ready-demo/run",
        headers=auth_headers["exchange"],
        json={"compute_mode": "MPC_MOCK", "algorithm_code": "SETTLEMENT_MPC_V1"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    data_space = result["data_space"]
    assert data_space["protocol_version"] == "HCDS-1.0"
    assert data_space["agreement_count"] >= 3
    assert data_space["raw_data_transferred"] is False
    assert all(item["state"] == "CONSUMED" for item in data_space["agreements"])
    assert result["compute_job"]["execution_attestation_json"]["raw_data_exported"] is False
    assert result["compute_job"]["result_json"]["capsule_id"] == result["task"]["capsule_id"]

    agreement_id = data_space["agreements"][0]["agreement_id"]
    denied = client.post(
        "/api/data-space/usage-control/check",
        headers=auth_headers["regulator"],
        json={
            "agreement_id": agreement_id,
            "purpose": "POWER_SETTLEMENT",
            "algorithm_code": "UNAUTHORIZED_ALGORITHM",
            "raw_data_export": False,
            "output_mode": "AGGREGATE_ONLY",
            "execution_environment": "AUTHORIZED_COMPUTE_SANDBOX",
        },
    )
    assert denied.status_code == 200
    assert denied.json()["decision"] == "DENY"
    assert "USE_LIMIT_REACHED" in denied.json()["reasons"]


def test_usage_control_rejects_raw_output_and_wrong_algorithm(client, auth_headers):
    response = client.post(
        "/api/settlement/tasks/task-ready-demo/run",
        headers=auth_headers["exchange"],
        json={"compute_mode": "MPC_MOCK", "algorithm_code": "SETTLEMENT_MPC_V1"},
    )
    assert response.status_code == 200, response.text
    agreement_id = response.json()["data_space"]["agreements"][0]["agreement_id"]
    denied = client.post(
        "/api/data-space/usage-control/check",
        headers=auth_headers["regulator"],
        json={
            "agreement_id": agreement_id,
            "purpose": "POWER_SETTLEMENT",
            "algorithm_code": "SETTLEMENT_MPC_V1",
            "raw_data_export": True,
            "output_mode": "RAW_RECORDS",
            "execution_environment": "UNTRUSTED_CLIENT",
        },
    )
    assert denied.status_code == 200
    reasons = set(denied.json()["reasons"])
    assert {"RAW_DATA_EXPORT_NOT_ALLOWED", "OUTPUT_MODE_NOT_ALLOWED", "EXECUTION_ENVIRONMENT_NOT_ALLOWED"} <= reasons


def test_audit_query_is_grounded_in_evidence(client, auth_headers):
    response = client.post(
        "/api/agent/query",
        headers=auth_headers["regulator"],
        json={"task_id": "task-ready-demo", "question": "本次结算是否完整可信？"},
    )
    assert response.status_code == 200
    answer = response.json()
    assert answer["citations"]
    assert answer["raw_data_accessed"] is False
    assert answer["grounded"] is True
    assert answer["fallback"] is True
    assert answer["provider"] == "template_fallback"


def test_deepseek_agent_endpoint_never_fakes_success_when_disabled(client, auth_headers):
    status = client.get("/api/agents/llm/status", headers=auth_headers["regulator"])
    assert status.status_code == 200
    assert status.json()["enabled"] is False
    response = client.post(
        "/api/agents/ORCHESTRATOR/invoke",
        headers=auth_headers["regulator"],
        json={
            "task_id": "task-ready-demo",
            "instruction": "核对当前任务编排状态。",
        },
    )
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_invalid_upload_payload_is_rejected_before_persistence(client, auth_headers):
    response = client.post(
        "/api/data/uploads",
        headers=auth_headers["retailer"],
        json={
            "asset_type": "USER_LOAD_CURVE",
            "trade_batch_no": "TB-INVALID-001",
            "label": "错误负荷曲线",
            "local_payload": {"period": "2026-08", "load_curve": [1, 2, 3]},
        },
    )
    assert response.status_code == 422
    assert "24" in response.text


def test_result_confirmation_and_data_signing_are_idempotent(client, auth_headers):
    upload = client.get(
        "/api/data/uploads?asset_type=GENERATION_DATA", headers=auth_headers["generator"]
    ).json()[0]
    first_signature = client.post(
        f"/api/data/{upload['upload_id']}/sign", headers=auth_headers["generator"]
    )
    second_signature = client.post(
        f"/api/data/{upload['upload_id']}/sign", headers=auth_headers["generator"]
    )
    assert first_signature.status_code == second_signature.status_code == 200
    assert first_signature.json() == second_signature.json()

    result = client.get(
        "/api/settlement/results", headers=auth_headers["generator"]
    ).json()[0]
    first_confirmation = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers=auth_headers["generator"],
        json={"opinion": "同意结算结果"},
    )
    second_confirmation = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers=auth_headers["generator"],
        json={"opinion": "同意结算结果"},
    )
    assert first_confirmation.status_code == second_confirmation.status_code == 200
    assert first_confirmation.json() == second_confirmation.json()


def test_task_creation_rejects_invalid_participant_shape(client, auth_headers):
    rules = client.get("/api/rules", headers=auth_headers["exchange"])
    rule_id = rules.json()[0]["rule_id"]
    response = client.post(
        "/api/settlement/tasks",
        headers=auth_headers["exchange"],
        json={
            "task_name": "非法参与方任务",
            "trade_batch_no": "TB-INVALID-002",
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "rule_id": rule_id,
            "participants": [
                {"org_id": "org-generator-demo", "role_in_task": "GENERATOR"},
                {"org_id": "org-generator-demo", "role_in_task": "GENERATOR"},
            ],
        },
    )
    assert response.status_code == 400
    assert "参与主体不能重复" in response.json()["detail"]


def test_retailer_cannot_analyze_another_organization_load_curve(client, auth_headers):
    created = client.post(
        "/api/data/uploads",
        headers=auth_headers["admin"],
        json={
            "asset_type": "USER_LOAD_CURVE",
            "owner_org_id": "org-generator-demo",
            "trade_batch_no": "TB-CROSS-ORG-001",
            "label": "发电侧负荷曲线测试数据",
            "local_payload": {"period": "2026-08", "load_curve": [1] * 24},
        },
    )
    assert created.status_code == 201, created.text
    upload_id = created.json()["upload_id"]
    denied = client.post(
        "/api/privacy/analysis/jobs",
        headers=auth_headers["retailer"],
        json={
            "analysis_name": "越权发电数据分析",
            "dataset_ids": [upload_id],
            "analysis_type": "DR_POTENTIAL",
            "privacy_level": "AGGREGATED",
        },
    )
    assert denied.status_code == 403
