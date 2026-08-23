from __future__ import annotations

import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

from app.services.adapters import PandapowerGridAdapter
from app.services import adapters as adapter_module
from app.schemas import DataUploadCreate
from app.services.trust_execution import AgenticQueryOrchestrator, DynamicPolicyEngine, ElectricityNode, ResultAuditor, _round_metric


def _etag_headers(client, base_headers: dict[str, str], task_id: str) -> dict[str, str]:
    response = client.get(f"/api/settlement/tasks/{task_id}", headers=base_headers)
    assert response.status_code == 200, response.text
    return {**base_headers, "If-Match": response.headers["etag"]}


def test_login_response_never_exposes_password_hash(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "exchange", "password": "exchange123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert any(item["code"] == "query" for item in payload["menus"])
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
    assert all(item["owner_org_id"] == "org-generator-t01" for item in own_data.json())
    assert all(item["raw_payload_exposed"] is False for item in own_data.json())
    assert all(item["trusted_acquisition"] is True for item in own_data.json())
    assert all(item["secure_transport"]["encryption"] == "TLS1.3" for item in own_data.json())
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


def test_settlement_creation_readiness_and_action_permissions(client, auth_headers):
    ready_payload = {
        "task_name": "2026年7月正式结算复核任务",
        "trade_batch_no": "TB-2026-07-T01",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "rule_id": "rule-settlement-v1",
        "participants": [
            {"org_id": "org-generator-t01", "role_in_task": "GENERATOR"},
            {"org_id": "org-retailer-t01", "role_in_task": "RETAILER"},
        ],
        "compute_mode": "LOCAL_CONTROLLED",
        "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
    }
    forbidden = client.post(
        "/api/settlement/tasks",
        headers=auth_headers["generator"],
        json=ready_payload,
    )
    assert forbidden.status_code == 403

    created = client.post(
        "/api/settlement/tasks",
        headers=auth_headers["exchange"],
        json=ready_payload,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "READY"
    assert created.json()["readiness"]["preflight_passed"] is True

    blocked_payload = {
        **ready_payload,
        "task_name": "2026年8月待准备结算任务",
        "trade_batch_no": "TB-2026-08-NOT-READY",
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
    }
    blocked = client.post(
        "/api/settlement/tasks",
        headers=auth_headers["exchange"],
        json=blocked_payload,
    )
    assert blocked.status_code == 201, blocked.text
    assert blocked.json()["status"] == "DRAFT"
    assert blocked.json()["readiness"]["preflight_passed"] is False
    assert len(blocked.json()["readiness"]["preflight_blockers"]) == 2

    simulated_mode = client.post(
        "/api/settlement/tasks",
        headers=auth_headers["exchange"],
        json={**ready_payload, "task_name": "无效计算模式", "compute_mode": "MPC_MOCK"},
    )
    assert simulated_mode.status_code == 422

    admin_run = client.post(
        f"/api/settlement/tasks/{created.json()['task_id']}/run",
        headers=auth_headers["regulator"],
        json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"},
    )
    assert admin_run.status_code == 403


def test_complete_agent_native_settlement_workflow(client, auth_headers):
    response = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=_etag_headers(client, auth_headers["exchange"], "task-ready-t01"),
        json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["task"]["status"] == "PENDING_CONFIRMATION"
    assert result["task"]["risk_level"] == "MEDIUM"
    assert result["compute_job"]["status"] == "SUCCESS"
    assert result["compute_job"]["execution_attestation_json"]["api_raw_records_returned"] is False
    assert result["compute_job"]["privacy_guarantees"]["api_raw_records_returned"] is False
    assert result["compute_job"]["privacy_guarantees"]["cross_domain_non_export_verified"] is False
    assert result["verification_profile"]["traceable_audit"] is True
    assert result["verification_profile"]["acceptance_metrics"]["api_raw_records_returned"] == 0
    assert len(result["results"]) >= 2
    assert len(result["evidence"]) >= 4
    assert result["report"]["conclusion"] == "REVIEW_REQUIRED"
    coordination = result["task"]["scenario_coordination"]
    assert {item["code"] for item in coordination} == {
        "RENEWABLE_CONSUMPTION",
        "MARKET_TRADING",
        "VPP_OPERATION",
        "GRID_DISPATCH",
    }
    assert all(item["status"] == "PASSED" for item in coordination)
    assert result["compute_job"]["result_json"]["gross_deviation_mwh"] > result["compute_job"]["result_json"]["deviation_mwh"]
    assert result["compute_job"]["result_json"]["grid_security"]["adapter"] == "PANDAPOWER_3_BUS"
    assert result["compute_job"]["result_json"]["grid_security"]["passed"] is True
    assert all(
        item["decision_json"]["policy_engine"] in {"OPA_REST", "OPA_REGO_COMPAT_LOCAL"}
        for item in result["data_space"]["agreements"]
    )
    assert all(item["decision_json"]["policy_input_hash"] for item in result["data_space"]["agreements"])

    scoped_results = [item for item in result["results"] if item["result_scope"] == "ORG"]
    by_org = {item["org_id"]: item for item in scoped_results}
    generator_confirmation = client.post(
        f"/api/results/{by_org['org-generator-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"], "task-ready-t01"),
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )
    assert generator_confirmation.status_code == 200
    assert generator_confirmation.json()["task"]["status"] == "PARTIALLY_CONFIRMED"
    report_approval = client.post(
        f"/api/audit/reports/{result['report']['report_id']}/decision",
        headers=auth_headers["regulator"],
        json={"decision": "APPROVE", "opinion": "中风险结算证据复核通过"},
    )
    assert report_approval.status_code == 200, report_approval.text
    retailer_confirmation = client.post(
        f"/api/results/{by_org['org-retailer-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"], "task-ready-t01"),
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )
    assert retailer_confirmation.status_code == 200
    assert retailer_confirmation.json()["task"]["status"] == "AUDITED"

    events = client.get(
        "/api/agents/events?task_id=task-ready-t01",
        headers=auth_headers["regulator"],
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
        "/api/chain/evidence?task_id=task-ready-t01",
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
    assert job["result_json"]["compute_strategy"]["primary"] == "LOCAL_CONTROLLED_SETTLEMENT_V1"
    assert job["result_json"]["recommended_strategy"]["primary"] == "SECRET_SHARING_HE"


def test_dashboard_exposes_four_scenario_and_four_chain_operating_state(client, auth_headers):
    response = client.get("/api/dashboard/summary", headers=auth_headers["exchange"])
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["scenario_coordination"]) == 4
    assert [item["code"] for item in payload["verification_steps"]] == [
        "TRUSTED_ACQUISITION",
        "SECURE_TRANSPORT",
        "CONTROLLED_USE",
        "PRIVACY_COMPUTE",
        "TRACEABLE_AUDIT",
    ]
    assert {item["code"] for item in payload["four_chain_fusion"]} == {
        "IDENTITY",
        "COMPUTE",
        "EVIDENCE",
        "PROCESS",
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
        "/api/data/catalog?trade_batch_no=TB-2026-07-T01",
        headers=auth_headers["exchange"],
    )
    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload["protocol_version"] == "HCDS-1.0"
    assert payload["raw_data_exposed"] is False
    assert payload["entries"][0]["transport"]["encryption"] == "TLS1.3"
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
    assert protocol_payload["cross_domain_non_export_verification"] == "NOT_PROVIDED"
    assert protocol_payload["api_raw_records_returned"] is False


def test_settlement_records_connector_agreements_and_enforces_usage_control(client, auth_headers):
    response = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=_etag_headers(client, auth_headers["exchange"], "task-ready-t01"),
        json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    data_space = result["data_space"]
    assert data_space["protocol_version"] == "HCDS-1.0"
    assert data_space["agreement_count"] >= 3
    assert data_space["raw_data_transfer_verification"] == "NOT_PROVIDED"
    assert all(item["state"] == "CONSUMED" for item in data_space["agreements"])
    assert result["compute_job"]["execution_attestation_json"]["api_raw_records_returned"] is False
    assert result["compute_job"]["execution_attestation_json"]["cross_domain_non_export_verified"] is False
    assert result["compute_job"]["result_json"]["capsule_id"] == result["task"]["capsule_id"]

    agreements = client.get(
        "/api/data/agreements?task_id=task-ready-t01",
        headers=auth_headers["exchange"],
    )
    assert agreements.status_code == 200
    assert all(item["provider_org_name"] for item in agreements.json())
    assert all(item["consumer_org_name"] for item in agreements.json())

    jobs = client.get(
        "/api/privacy/jobs?task_id=task-ready-t01",
        headers=auth_headers["exchange"],
    )
    assert jobs.status_code == 200
    job = jobs.json()[0]
    assert job["task_name"] == result["task"]["task_name"]
    assert job["trade_batch_no"] == result["task"]["trade_batch_no"]
    assert {item["role_in_task"] for item in job["participants"]} == {"GENERATOR", "RETAILER"}
    assert all(item["org_name"] for item in job["participants"])
    assert len(job["authorization_basis"]) >= 2
    assert all(item["policy_hash"] for item in job["authorization_basis"])
    assert job["rule"]["rule_version"]
    assert job["disclosure"]["output_mode"] == "AGGREGATE_ONLY"
    assert job["disclosure"]["api_raw_records_returned"] is False
    assert job["evidence_count"] >= 1

    party_jobs = client.get(
        "/api/privacy/jobs?task_id=task-ready-t01",
        headers=auth_headers["generator"],
    )
    assert party_jobs.status_code == 200
    assert set(party_jobs.json()[0]["result_json"]) == {"output_hash", "raw_data_exposed", "status"}

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
            "execution_environment": "APPLICATION_PROCESS",
        },
    )
    assert denied.status_code == 200
    assert denied.json()["decision"] == "DENY"
    assert "USE_LIMIT_REACHED" in denied.json()["reasons"]


def test_usage_control_rejects_raw_output_and_wrong_algorithm(client, auth_headers):
    response = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=_etag_headers(client, auth_headers["exchange"], "task-ready-t01"),
        json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"},
    )
    assert response.status_code == 200, response.text
    agreement_id = response.json()["data_space"]["agreements"][0]["agreement_id"]
    denied = client.post(
        "/api/data-space/usage-control/check",
        headers=auth_headers["regulator"],
        json={
            "agreement_id": agreement_id,
            "purpose": "POWER_SETTLEMENT",
            "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
            "raw_data_export": True,
            "output_mode": "RAW_RECORDS",
            "execution_environment": "UNTRUSTED_CLIENT",
        },
    )
    assert denied.status_code == 200
    reasons = set(denied.json()["reasons"])
    assert {"RAW_DATA_EXPORT_NOT_ALLOWED", "OUTPUT_MODE_NOT_ALLOWED", "EXECUTION_ENVIRONMENT_NOT_ALLOWED"} <= reasons
    assert denied.json()["policy_engine"] in {"OPA_REST", "OPA_REGO_COMPAT_LOCAL"}
    assert denied.json()["policy_input_hash"]
    assert denied.json()["decision_hash"]


def test_health_exposes_calculation_services(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["calculation_services"]["policy"]["code"] == "OPA_REGO_COMPAT"
    assert payload["calculation_services"]["grid"]["code"] == "PANDAPOWER_3_BUS"
    assert payload["calculation_services"]["grid"]["installed"] is True


def test_pandapower_adapter_has_pass_and_reject_paths():
    adapter = PandapowerGridAdapter()
    passed = adapter.check(
        generation_mwh=12500,
        retail_mwh=12320,
        vpp_adjustment_mwh=100,
        deviation_mwh=80,
        grid_payload={
            "n_minus_one_passed": True,
            "max_residual_imbalance_mwh": 90,
            "congestion_margin_pct": 14.2,
        },
    )
    assert passed["passed"] is True
    assert passed["metrics"]["max_line_loading_pct"] < passed["constraints"]["max_line_loading_pct"]

    rejected = adapter.check(
        generation_mwh=12500,
        retail_mwh=12320,
        vpp_adjustment_mwh=0,
        deviation_mwh=180,
        grid_payload={
            "n_minus_one_passed": True,
            "max_residual_imbalance_mwh": 999999,
            "line_limit_mw": 0.01,
        },
    )
    assert rejected["passed"] is False
    assert "LINE_LOADING_EXCEEDED" in rejected["reasons"]


def test_opa_rest_adapter_accepts_opa_decision_shape(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        @staticmethod
        def json():
            return {"result": {"allow": True, "reasons": [], "obligations": ["LOG_USAGE"]}}

    monkeypatch.setattr(adapter_module.httpx, "post", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(
        adapter_module,
        "settings",
        SimpleNamespace(
            opa_url="http://opa:8181",
            opa_policy_path="/v1/data/hiddenchain/decision",
            opa_timeout_seconds=1.0,
            opa_local_fallback=False,
        ),
    )
    contract = SimpleNamespace(
        status="ACTIVE",
        purpose="POWER_SETTLEMENT",
        policy_hash="policy-hash",
        policy_json={
            "constraint": {
                "capsule_id": "capsule-1",
                "consumer_did": "did:example:consumer",
                "algorithm_codes": ["CONTROLLED_SETTLEMENT_V1"],
                "execution_environment": "APPLICATION_PROCESS",
                "output_mode": "AGGREGATE_ONLY",
                "raw_data_export": False,
            },
            "obligation": ["LOG_USAGE"],
        },
    )
    result = adapter_module.OPAPolicyAdapter.evaluate(
        contract,
        "POWER_SETTLEMENT",
        "capsule-1",
        consumer_did="did:example:consumer",
    )
    assert result["decision"] == "PERMIT"
    assert result["policy_engine"] == "OPA_REST"
    assert result["policy_remote_configured"] is True


def test_audit_query_is_grounded_in_evidence(client, auth_headers):
    settled = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=_etag_headers(client, auth_headers["exchange"], "task-ready-t01"),
        json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"},
    )
    assert settled.status_code == 200, settled.text
    response = client.post(
        "/api/agent/query",
        headers=auth_headers["regulator"],
        json={"task_id": "task-ready-t01", "question": "本次结算是否完整可信？"},
    )
    assert response.status_code == 200
    answer = response.json()
    assert answer["citations"]
    assert answer["raw_data_accessed"] is False
    assert answer["grounded"] is True
    assert answer["fallback"] is True
    assert answer["provider"] == "template_fallback"


def test_deepseek_agent_endpoint_never_fakes_success_when_disabled(client, auth_headers):
    status = client.get("/api/agents/llm/status", headers=auth_headers["admin"])
    assert status.status_code == 200
    assert status.json()["enabled"] is False
    response = client.post(
        "/api/agents/ORCHESTRATOR/invoke",
        headers=auth_headers["admin"],
        json={
            "task_id": "task-ready-t01",
            "instruction": "核对当前任务编排状态。",
        },
    )
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_anomaly_injection_and_resolution_persist_audit_target(client, auth_headers):
    injected = client.post(
        "/api/anomalies/inject",
        headers=auth_headers["regulator"],
        json={"task_id": "task-ready-t01", "event_type": "UNAUTHORIZED_ACCESS"},
    )
    assert injected.status_code == 201, injected.text
    event = injected.json()
    assert event["event_id"]
    assert event["status"] == "OPEN"

    resolved = client.post(
        f"/api/anomalies/{event['event_id']}/resolve",
        headers=auth_headers["regulator"],
        json={"resolution": "已完成测试处置"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "RESOLVED"

    timeline = client.get(
        "/api/audit/timeline/task-ready-t01", headers=auth_headers["regulator"]
    )
    assert timeline.status_code == 200
    matching = [item for item in timeline.json()["events"] if item["reference"] == event["event_id"]]
    assert matching and matching[0]["status"] == "RESOLVED"


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
    confirmation_headers = _etag_headers(
        client, auth_headers["generator"], result["task_id"]
    )
    first_confirmation = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers=confirmation_headers,
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )
    second_confirmation = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers=confirmation_headers,
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )
    assert first_confirmation.status_code == second_confirmation.status_code == 200
    assert first_confirmation.json()["signature"] == second_confirmation.json()["signature"]
    assert first_confirmation.json()["idempotent_replay"] is False
    assert second_confirmation.json()["idempotent_replay"] is True


def test_data_commitment_can_only_be_signed_by_its_owner(client, auth_headers):
    upload = client.get(
        "/api/data/uploads?asset_type=GENERATION_DATA", headers=auth_headers["generator"]
    ).json()[0]

    exchange_signature = client.post(
        f"/api/data/{upload['upload_id']}/sign", headers=auth_headers["exchange"]
    )
    admin_signature = client.post(
        f"/api/data/{upload['upload_id']}/sign", headers=auth_headers["admin"]
    )

    assert exchange_signature.status_code == 403
    assert exchange_signature.json()["detail"] == "不能签署其他主体的数据"
    assert admin_signature.status_code == 403


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
                {"org_id": "org-generator-t01", "role_in_task": "GENERATOR"},
                {"org_id": "org-generator-t01", "role_in_task": "GENERATOR"},
            ],
        },
    )
    assert response.status_code == 400
    assert "参与主体不能重复" in response.json()["detail"]


def test_retailer_cannot_analyze_another_organization_load_curve(client, auth_headers):
    created = client.post(
        "/api/data/uploads",
        headers=auth_headers["exchange"],
        json={
            "asset_type": "USER_LOAD_CURVE",
            "owner_org_id": "org-exchange-t01",
            "trade_batch_no": "TB-CROSS-ORG-001",
            "label": "交易中心负荷曲线测试数据",
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


def test_import_fixture_runs_settlement_end_to_end(client, auth_headers):
    fixture_path = Path(__file__).resolve().parents[2] / "demo-data" / "2026-08-simulation-input.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["is_simulated"] = False
    response = client.post(
        "/api/settlement/import-and-run",
        headers=auth_headers["exchange"],
        json=fixture,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["uploads"]) == 6
    assert result["task"]["status"] == "PENDING_CONFIRMATION"
    assert result["compute_job"]["status"] == "SUCCESS"
    assert result["compute_job"]["execution_attestation_json"]["api_raw_records_returned"] is False
    assert result["privacy_analysis"]["status"] == "SUCCESS"
    assert result["privacy_analysis"]["raw_records_returned"] is False
    assert result["uploads"][0]["ingress_json"]["protocol"] == "HTTPS"
    assert result["task"]["verification_profile"]["transport_evidence_provided"] is True
    assert result["verification_profile"]["mode"] == "SCENE_DATA_METADATA"
    assert result["verification_profile"]["is_simulated"] is False
    assert len(result["evidence"]) >= 4


def test_full_settlement_fixture_closes_with_expected_amount(client, auth_headers):
    fixture_path = Path(__file__).resolve().parents[2] / "demo-data" / "2026-08-full-settlement-simulation.json"
    expected_path = Path(__file__).resolve().parents[2] / "demo-data" / "2026-08-full-settlement-expected-result.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    imported_response = client.post(
        "/api/settlement/import-and-run",
        headers=auth_headers["exchange"],
        json=fixture,
    )
    assert imported_response.status_code == 200, imported_response.text
    imported = imported_response.json()
    task_id = imported["task"]["task_id"]
    assert len(imported["uploads"]) == 6
    assert imported["task"]["status"] == "PENDING_CONFIRMATION"
    assert imported["task"]["risk_level"] == "MEDIUM"
    assert imported["privacy_analysis"]["status"] == "SUCCESS"
    assert imported["privacy_analysis"]["raw_records_returned"] is False
    assert imported["compute_job"]["execution_attestation_json"]["api_raw_records_returned"] is False

    calculation = imported["compute_job"]["result_json"]
    assert calculation["settlement_energy_mwh"] == expected["calculation"]["settlement_energy_mwh"]
    assert calculation["gross_deviation_mwh"] == expected["calculation"]["gross_deviation_mwh"]
    assert calculation["vpp_adjustment_mwh"] == expected["calculation"]["vpp_adjustment_mwh"]
    assert calculation["deviation_mwh"] == expected["calculation"]["remaining_deviation_mwh"]
    assert calculation["payable_amount_yuan"] == expected["calculation"]["payable_amount_yuan"]

    scoped = {item["org_id"]: item for item in imported["results"] if item["result_scope"] == "ORG"}
    generator_confirmation = client.post(
        f"/api/results/{scoped['org-generator-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"], task_id),
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )
    assert generator_confirmation.status_code == 200, generator_confirmation.text
    assert generator_confirmation.json()["task"]["status"] == "PARTIALLY_CONFIRMED"

    report_approval = client.post(
        f"/api/audit/reports/{imported['report']['report_id']}/decision",
        headers=auth_headers["regulator"],
        json={
            "decision": "APPROVE",
            "opinion": "已核对规则、授权、聚合结果和证据记录，批准本次结算报告",
        },
    )
    assert report_approval.status_code == 200, report_approval.text
    assert report_approval.json()["status"] == "APPROVED"

    retailer_confirmation = client.post(
        f"/api/results/{scoped['org-retailer-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"], task_id),
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )
    assert retailer_confirmation.status_code == 200, retailer_confirmation.text
    assert retailer_confirmation.json()["task"]["status"] == "AUDITED"
    assert retailer_confirmation.json()["formal_evidence"]["status"] == "PUBLISHED_DEMO"


def test_import_accepts_real_scene_flag_and_rolls_back_failed_run(client, auth_headers):
    fixture_path = Path(__file__).resolve().parents[2] / "demo-data" / "2026-08-simulation-input.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["fixture_id"] = "hiddenchain-real-scene-metadata-rollback"
    fixture["is_simulated"] = False
    fixture["batch"]["trade_batch_no"] = "TB-ROLLBACK-202608"
    fixture["business_validation_request"]["task_name"] = "失败后应回滚的可信调用"
    fixture["data_assets"][4]["local_payload"]["n_minus_one_passed"] = False
    fixture["privacy_analysis_request"] = None
    fixture["data_assets"][1]["local_payload"]["energy_mwh"] = 99999
    response = client.post(
        "/api/settlement/import-and-run",
        headers=auth_headers["exchange"],
        json=fixture,
    )
    assert response.status_code == 400
    assert "Grid security gate" in response.json()["detail"]
    tasks = client.get("/api/settlement/tasks", headers=auth_headers["exchange"]).json()
    assert all(item["trade_batch_no"] != "TB-ROLLBACK-202608" for item in tasks)


def test_dynamic_policy_engine_supports_all_five_actions(tmp_path):
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "version": "test-policy/v1",
                "default_action": "PROHIBIT",
                "rules": [
                    {"id": "allow", "priority": 10, "action": "ALLOW", "match": {"data_types": ["TEST_ALLOW"]}},
                    {"id": "delay", "priority": 20, "action": "DELAY", "delay_days": 1, "match": {"data_types": ["TEST_DELAY"]}},
                    {"id": "aggregate", "priority": 30, "action": "AGGREGATE", "group_by": ["region"], "match": {"data_types": ["TEST_AGGREGATE"]}},
                    {"id": "compute", "priority": 40, "action": "COMPUTE_ONLY", "match": {"data_types": ["TEST_COMPUTE"]}},
                    {"id": "prohibit", "priority": 50, "action": "PROHIBIT", "match": {"data_types": ["TEST_PROHIBIT"]}},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    intent = AgenticQueryOrchestrator().resolve(
        {
            "question": "test policy",
            "period_start": "2026-07-01",
            "period_end": "2026-07-31",
            "target_data_types": [],
        }
    )
    engine = DynamicPolicyEngine(str(policy_path))
    decisions = {
        target: engine.decide(intent, target)
        for target in ("TEST_ALLOW", "TEST_DELAY", "TEST_AGGREGATE", "TEST_COMPUTE", "TEST_PROHIBIT")
    }
    assert {item.action.value for item in decisions.values()} == {
        "ALLOW",
        "DELAY",
        "AGGREGATE",
        "COMPUTE_ONLY",
        "PROHIBIT",
    }
    assert decisions["TEST_PROHIBIT"].permitted is False
    assert decisions["TEST_AGGREGATE"].group_by == ("region",)
    assert decisions["TEST_ALLOW"].execution_method == "DIRECT_CONTROLLED_API"
    assert decisions["TEST_COMPUTE"].execution_method == "LOCAL_CONTROLLED_COMPUTE"
    assert decisions["TEST_COMPUTE"].candidate_methods == ("PSI_MPC", "TEE_CONFIDENTIAL_COMPUTE")


def test_policy_uses_requested_granularity_and_spatial_scope():
    orchestrator = AgenticQueryOrchestrator()
    intent = orchestrator.resolve(
        {
            "question": "查询区域内15分钟级负荷趋势",
            "consumer_role": "ENERGY_BUREAU",
            "purpose": "ENERGY_ANALYSIS",
            "requested_granularity": "15_MINUTE",
            "spatial_scope": "REGION",
            "target_data_types": ["GRID_LOAD"],
        }
    )
    decision = DynamicPolicyEngine().decide(intent, "GRID_LOAD")
    assert intent.requested_granularity == "15_MINUTE"
    assert intent.spatial_scope == "REGION"
    assert decision.action.value == "COMPUTE_ONLY"
    assert decision.requires_external_runtime is True

    precise_intent = orchestrator.resolve(
        {
            "question": "查询计量点负荷",
            "consumer_role": "ENERGY_BUREAU",
            "purpose": "ENERGY_ANALYSIS",
            "spatial_scope": "METER_POINT",
            "target_data_types": ["GRID_LOAD"],
        }
    )
    precise_decision = DynamicPolicyEngine().decide(precise_intent, "GRID_LOAD")
    assert precise_decision.action.value == "PROHIBIT"
    assert precise_decision.permitted is False


def test_electricity_node_sums_multiple_same_period_commitments(monkeypatch):
    from app.services import trust_execution as trust_execution_module

    node = ElectricityNode(None)
    uploads = [
        SimpleNamespace(data_ref="domain-ref-a", commitment="commitment-a"),
        SimpleNamespace(data_ref="domain-ref-b", commitment="commitment-b"),
    ]
    payloads = {
        "domain-ref-a": {"period": "2026-07", "energy_mwh": 12680.0},
        "domain-ref-b": {"period": "2026-07", "energy_mwh": 1320.0},
    }
    monkeypatch.setattr(node, "_uploads", lambda asset_type, period: uploads)
    monkeypatch.setattr(trust_execution_module.LocalDomainVault, "read", lambda ref: payloads[ref])

    intent = AgenticQueryOrchestrator().resolve(
        {
            "question": "核对火电出力汇总",
            "consumer_role": "ENERGY_BUREAU",
            "purpose": "CROSS_ENERGY_TREND",
            "period_start": "2026-07-01",
            "period_end": "2026-07-31",
            "target_data_types": ["POWER_THERMAL_OUTPUT"],
            "group_by": ["region", "period"],
        }
    )
    decision = DynamicPolicyEngine().decide(intent, "POWER_THERMAL_OUTPUT")
    row = node.query("POWER_THERMAL_OUTPUT", intent, decision)[0]

    assert row["value"] == 14000.0
    assert row["aggregation"] == "SUM"
    assert row["group_size"] == 2
    assert row["source_commitments"] == ["commitment-a", "commitment-b"]


def test_result_auditor_reconciles_multiple_aggregate_source_rows():
    result = {
        "raw_data_returned": False,
        "series": [
            {
                "period": "2026-07",
                "region": "EAST-CHINA",
                "thermal_output_mwh": 14000.0,
            }
        ],
    }
    source_snapshot = [
        {"data_type": "POWER_THERMAL_OUTPUT", "period": "2026-07", "region": "EAST-CHINA", "value": 12680.0},
        {"data_type": "POWER_THERMAL_OUTPUT", "period": "2026-07", "region": "EAST-CHINA", "value": 1320.0},
    ]

    checks = ResultAuditor.verify_calculation(result, source_snapshot)

    assert checks["passed"] is True
    assert checks["checks"]["source_aggregate_reconciliation"] is True


def test_trusted_metrics_use_decimal_half_up_and_reject_non_finite_values():
    assert _round_metric(1.23485) == 1.2349
    try:
        _round_metric(math.inf)
    except ValueError as exc:
        assert str(exc) == "NON_FINITE_METRIC"
    else:
        raise AssertionError("non-finite metric should fail closed")


def test_upload_contract_rejects_non_finite_numeric_payloads():
    try:
        DataUploadCreate(
            asset_type="GENERATION_DATA",
            trade_batch_no="TB-NAN-001",
            label="非有限数值",
            local_payload={"period": "2026-07", "energy_mwh": float("nan")},
        )
    except ValueError as exc:
        assert "finite" in str(exc)
    else:
        raise AssertionError("non-finite upload payload should be rejected")


def test_trusted_execution_requires_trusted_role(client, auth_headers):
    status_response = client.get(
        "/api/trusted-execution/status",
        headers=auth_headers["generator"],
    )
    assert status_response.status_code == 403

    query_response = client.post(
        "/api/trusted-execution/query",
        headers=auth_headers["retailer"],
        json={
            "question": "查询跨能源趋势",
            "consumer_role": "ENERGY_BUREAU",
            "purpose": "CROSS_ENERGY_TREND",
            "translation": {
                "function": "TREND",
                "target_data_types": ["COAL_INVENTORY", "POWER_THERMAL_OUTPUT", "GRID_LOAD"],
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "requested_granularity": "MONTH",
                "spatial_scope": "REGION",
                "group_by": ["region", "period"],
                "output_mode": "SUMMARY",
            },
            "group_by": ["region", "period"],
            "output_mode": "SUMMARY",
        },
    )
    assert query_response.status_code == 403


def test_trusted_execution_requires_confirmed_translation(client, auth_headers):
    response = client.post(
        "/api/trusted-execution/query",
        headers=auth_headers["exchange"],
        json={"question": "把火电出力和电网负荷加起来"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "请先完成查询翻译并确认后再执行"


def test_offline_translation_is_explicit_and_fixture_only(client, auth_headers):
    response = client.post(
        "/api/trusted-execution/translate",
        headers=auth_headers["exchange"],
        json={
            "question": "查询调度实时出力变化趋势",
            "offline_test": True,
            "requested_granularity": "15_MINUTE",
            "spatial_scope": "REGION",
            "group_by": ["region", "period"],
            "output_mode": "CHART",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "local_offline_fixture"
    assert payload["offline_test"] is True
    assert payload["translation"]["function"] == "TREND"
    assert payload["translation"]["target_data_types"] == ["POWER_DISPATCH"]


def test_deepseek_translation_does_not_fallback_when_disabled(client, auth_headers):
    response = client.post(
        "/api/trusted-execution/translate",
        headers=auth_headers["exchange"],
        json={"question": "查询调度实时出力变化趋势"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "DeepSeek 翻译服务暂时不可用，查询未执行"


def test_trusted_execution_cross_energy_query_is_aggregate_only(client, auth_headers):
    status_response = client.get(
        "/api/trusted-execution/status",
        headers=auth_headers["exchange"],
    )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["security_boundary"] == {
        "api_raw_records_returned": False,
        "cross_domain_non_export_verified": False,
        "anti_inference_check": "LOCAL_OUTPUT_CHECK",
        "topology_coordinates_released": False,
    }
    assert status_payload["audit"] == {
        "asynchronous_evidence_recording": True,
        "evidence_backend": "LOCAL_EVIDENCE_LEDGER_V1",
        "result_hash_required": True,
    }

    response = client.post(
        "/api/trusted-execution/query",
        headers=auth_headers["exchange"],
        json={
            "question": "分析上月由于电煤库存变化引起的火电出力与电网负荷平衡趋势",
            "consumer_role": "ENERGY_BUREAU",
            "purpose": "CROSS_ENERGY_TREND",
            "translation": {
                "function": "TREND",
                "target_data_types": ["COAL_INVENTORY", "POWER_THERMAL_OUTPUT", "GRID_LOAD"],
                "period_start": "2026-07-01",
                "period_end": "2026-07-31",
                "requested_granularity": "MONTH",
                "spatial_scope": "REGION",
                "group_by": ["region", "period"],
                "output_mode": "SUMMARY",
            },
            "translation_hash": "48deb2c8ecd042ad7e87f87718b23574f5fb3db2c1e62d6257eca51118ec386f",
            "group_by": ["region", "period"],
            "output_mode": "SUMMARY",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["execution_status"] == "SUCCEEDED"
    assert [item["code"] for item in payload["workflow_steps"]] == [
        "INGEST",
        "AUTHENTICATE",
        "RESOLVE",
        "ARBITRATE",
        "EXECUTE",
        "AUDIT",
        "DELIVER",
        "LOG",
    ]
    assert set(payload["intent"]["target_data_types"]) == {
        "COAL_INVENTORY",
        "POWER_THERMAL_OUTPUT",
        "GRID_LOAD",
    }
    assert payload["caller_identity"]["did_verified"] is True
    assert payload["caller_identity"]["credential_canonicalization"] == "CANONICALIZED"
    assert len(payload["caller_identity"]["credential_hash"]) == 64
    assert "credential_json" not in json.dumps(payload["caller_identity"], ensure_ascii=False)
    actions = {item["target_data_type"]: item["action"] for item in payload["policy_hits"]}
    assert actions == {
        "COAL_INVENTORY": "AGGREGATE",
        "POWER_THERMAL_OUTPUT": "AGGREGATE",
        "GRID_LOAD": "AGGREGATE",
    }
    result = payload["result"]
    assert result["released"] is True
    assert result["raw_data_returned"] is False
    assert result["output_mode"] == "AGGREGATED_AND_COMPUTE_ONLY"
    assert result["calculation_contract"] == {
        "aggregation_key": ["period", "region", "data_type"],
        "aggregation_method": "SUM_PER_SOURCE_GROUP",
        "rounding_scale": 4,
        "rounding_mode": "HALF_UP",
        "balance_formula": "thermal_output_mwh - grid_load_mwh",
    }
    assert result["privacy_controls"]["compute_environment"] == "APPLICATION_PROCESS"
    assert result["privacy_controls"]["cross_domain_non_export_verified"] is False
    assert result["privacy_controls"]["topology_coordinate_offset"]["coordinates_returned"] is False
    assert result["execution_routing"]["actual_runtime"] == "APPLICATION_PROCESS"
    assert result["execution_routing"]["actual_method"] == "LOCAL_CONTROLLED_COMPUTE"
    assert result["execution_routing"]["implementation_status"] == "TEST_FIXTURE_ONLY"
    assert result["execution_routing"]["external_runtime_required"] is False
    assert any("coal_inventory_tons" in item for item in result["series"])
    assert any("thermal_output_mwh" in item and "grid_load_mwh" in item for item in result["series"])
    assert all(item["raw_data_exposed"] is False for item in result["sources"])
    assert payload["evidence_audit"]["status"] == "QUEUED"

    audit = None
    for _ in range(40):
        audit = client.get(
            f"/api/trusted-execution/audit/{payload['request_id']}",
            headers=auth_headers["regulator"],
        )
        if audit.json()["status"] == "CONFIRMED":
            break
        time.sleep(0.05)
    assert audit is not None
    assert audit.status_code == 200
    audit_payload = audit.json()
    assert audit_payload["status"] == "CONFIRMED"
    chain_payload = audit_payload["items"][0]["payload_json"]
    assert set(
        ("Request_ID", "Caller_Identity", "Target_Data", "Policy_Hit", "Execution_Status", "Result_Hash")
    ) <= set(chain_payload)
    assert chain_payload["Request_ID"] == payload["request_id"]
    assert chain_payload["Result_Hash"] == payload["result_hash"]
    assert len(chain_payload["Workflow_Steps"]) == 8
    assert chain_payload["Source_Attestations"]

    review = client.get(
        f"/api/trusted-execution/reviews/{payload['request_id']}",
        headers=auth_headers["regulator"],
    )
    assert review.status_code == 200, review.text
    review_payload = review.json()
    assert review_payload["verification_status"] == "PENDING"
    assert review_payload["automatic_status"] == "PASSED"
    assert review_payload["checks"]["checks"]["balance_formula"] is True
    assert review_payload["source_snapshot"]
    assert all(item["raw_data_exposed"] is False for item in review_payload["source_snapshot"])

    review_queue = client.get(
        "/api/trusted-execution/reviews?review_status=PENDING",
        headers=auth_headers["regulator"],
    )
    assert review_queue.status_code == 200
    queue_item = next(item for item in review_queue.json() if item["request_id"] == payload["request_id"])
    assert queue_item["target_data"] == [
        "COAL_INVENTORY",
        "POWER_THERMAL_OUTPUT",
        "GRID_LOAD",
    ]

    confirmation = client.post(
        f"/api/trusted-execution/reviews/{payload['request_id']}/confirm",
        headers=auth_headers["regulator"],
        json={"opinion": "已核对节点汇总、平衡公式和结果哈希，确认", "accept": True},
    )
    assert confirmation.status_code == 200, confirmation.text
    confirmation_payload = confirmation.json()
    assert confirmation_payload["verification_status"] == "CONFIRMED"
    assert confirmation_payload["signature"]
    assert confirmation_payload["evidence_audit"]["status"] == "QUEUED"

    confirmed = client.get(
        f"/api/trusted-execution/reviews/{payload['request_id']}",
        headers=auth_headers["admin"],
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["verification_status"] == "CONFIRMED"
