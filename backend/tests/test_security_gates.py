from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    AnomalyEvent,
    AuditReport,
    BlockchainEvidence,
    DidIdentity,
    Organization,
    SettlementResult,
    SettlementTask,
    Signature,
)
from app.services.algorithm_registry import AlgorithmRegistry
from app.services.adapters import LocalControlledComputeAdapter
from app.services.trust_domain import ExecutionSnapshotService
from app.services.vault import LocalDomainVault


TASK_ID = "task-history-t01"


def _result_for(client, auth_headers, org_id: str) -> dict:
    results = client.get(
        f"/api/settlement/results?task_id={TASK_ID}",
        headers=auth_headers["exchange"],
    ).json()
    return next(
        item
        for item in results
        if item["result_scope"] == "ORG" and item["org_id"] == org_id
    )


def _latest_report(client, auth_headers) -> dict:
    reports = client.get(
        "/api/audit/reports", headers=auth_headers["regulator"]
    ).json()
    return next(item for item in reports if item["task_id"] == TASK_ID)


def _etag_headers(client, base_headers: dict[str, str], task_id: str = TASK_ID) -> dict[str, str]:
    response = client.get(f"/api/settlement/tasks/{task_id}", headers=base_headers)
    assert response.status_code == 200, response.text
    return {**base_headers, "If-Match": response.headers["etag"]}


def _approve_report(client, auth_headers) -> dict:
    report = _latest_report(client, auth_headers)
    response = client.post(
        f"/api/audit/reports/{report['report_id']}/decision",
        headers=auth_headers["regulator"],
        json={"decision": "APPROVE", "opinion": "审计证据与结算哈希复核通过"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _forbid_vault_reads(monkeypatch) -> list[str]:
    attempted_refs: list[str] = []

    def forbidden_read(cls, data_ref: str):
        attempted_refs.append(data_ref)
        raise AssertionError("Vault must not be read before frozen bindings pass")

    monkeypatch.setattr(LocalDomainVault, "read", classmethod(forbidden_read))
    return attempted_refs


def test_runtime_rejects_algorithm_descriptor_drift_before_vault_read(
    client, auth_headers, monkeypatch
):
    original_descriptor = AlgorithmRegistry.execution_descriptor
    descriptor_calls = 0

    def drifting_descriptor(cls, code: str) -> dict:
        nonlocal descriptor_calls
        descriptor_calls += 1
        descriptor = original_descriptor(code)
        if descriptor_calls >= 3:
            descriptor = {
                **descriptor,
                "component_source_hashes": {
                    **descriptor["component_source_hashes"],
                    "PandapowerGridAdapter": "0" * 64,
                },
            }
            descriptor["hash"] = "0" * 64
        return descriptor

    monkeypatch.setattr(
        AlgorithmRegistry,
        "execution_descriptor",
        classmethod(drifting_descriptor),
    )
    vault_reads = _forbid_vault_reads(monkeypatch)

    response = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=_etag_headers(client, auth_headers["exchange"], "task-ready-t01"),
        json={
            "compute_mode": "LOCAL_CONTROLLED",
            "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "EXECUTION_SNAPSHOT_ALGORITHM_DRIFT"
    assert descriptor_calls >= 3
    assert vault_reads == []


def test_runtime_rejects_actual_adapter_drift_before_vault_read(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(
        LocalControlledComputeAdapter,
        "code",
        "UNFROZEN_RUNTIME_ADAPTER",
    )
    vault_reads = _forbid_vault_reads(monkeypatch)

    response = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=_etag_headers(client, auth_headers["exchange"], "task-ready-t01"),
        json={
            "compute_mode": "LOCAL_CONTROLLED",
            "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "ALGORITHM_ADAPTER_RUNTIME_MISMATCH"
    assert vault_reads == []


@pytest.mark.parametrize(
    ("field_name", "tampered_value"),
    (("asset_type", "UNDECLARED_ASSET"), ("schema_version", "v999")),
)
def test_runtime_rejects_frozen_input_field_tampering_before_vault_read(
    client,
    auth_headers,
    monkeypatch,
    field_name: str,
    tampered_value: str,
):
    original_freeze = ExecutionSnapshotService.freeze

    def tampering_freeze(
        cls,
        db,
        task,
        rule,
        contracts,
        data_uploads,
        algorithm_descriptor,
        actor_did,
        trace_id,
    ):
        snapshot = original_freeze(
            db,
            task,
            rule,
            contracts,
            data_uploads,
            algorithm_descriptor,
            actor_did,
            trace_id,
        )
        setattr(data_uploads[0], field_name, tampered_value)
        return snapshot

    monkeypatch.setattr(
        ExecutionSnapshotService,
        "freeze",
        classmethod(tampering_freeze),
    )
    vault_reads = _forbid_vault_reads(monkeypatch)

    response = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=_etag_headers(client, auth_headers["exchange"], "task-ready-t01"),
        json={
            "compute_mode": "LOCAL_CONTROLLED",
            "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "FROZEN_INPUT_METADATA_MISMATCH"
    assert vault_reads == []


def test_inactive_organization_invalidates_an_existing_access_token(client, auth_headers):
    with SessionLocal() as db:
        organization = db.get(Organization, "org-generator-t01")
        assert organization is not None
        organization.status = "INACTIVE"
        db.commit()

    response = client.get("/api/auth/me", headers=auth_headers["generator"])

    assert response.status_code == 401
    assert response.json()["detail"] == "所属组织不可用"


def test_uploads_require_self_ownership_active_did_and_exchange_grid_role(
    client, auth_headers
):
    impersonation = client.post(
        "/api/data/uploads",
        headers=auth_headers["exchange"],
        json={
            "asset_type": "GENERATION_DATA",
            "trade_batch_no": "TB-SECURITY-001",
            "label": "伪造发电侧数据",
            "owner_org_id": "org-generator-t01",
            "local_payload": {"energy_mwh": 10.0},
        },
    )
    admin_grid = client.post(
        "/api/data/uploads",
        headers=auth_headers["admin"],
        json={
            "asset_type": "GRID_CONSTRAINT",
            "trade_batch_no": "TB-SECURITY-002",
            "label": "越权电网约束",
            "local_payload": {
                "n_minus_one_passed": True,
                "max_residual_imbalance_mwh": 1.0,
                "congestion_margin_pct": 10.0,
            },
        },
    )

    assert impersonation.status_code == 403
    assert admin_grid.status_code == 403

    with SessionLocal() as db:
        identity = db.get(DidIdentity, "did:hiddenchain:org:org-generator-t01")
        assert identity is not None
        identity.credential_status = "REVOKED"
        db.commit()

    create_with_revoked_did = client.post(
        "/api/data/uploads",
        headers=auth_headers["generator"],
        json={
            "asset_type": "GENERATION_DATA",
            "trade_batch_no": "TB-SECURITY-003",
            "label": "失效 DID 数据",
            "local_payload": {"energy_mwh": 10.0},
        },
    )
    sign_with_revoked_did = client.post(
        "/api/data/upload-generation-t01/sign",
        headers=auth_headers["generator"],
    )

    assert create_with_revoked_did.status_code == 403
    assert sign_with_revoked_did.status_code == 403
    assert create_with_revoked_did.json()["detail"]["code"] == "DID_CREDENTIAL_INVALID"
    assert sign_with_revoked_did.json()["detail"]["code"] == "DID_CREDENTIAL_INVALID"


def test_result_rejection_requires_opinion_and_enters_rework(client, auth_headers):
    result = _result_for(client, auth_headers, "org-generator-t01")
    blank = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"]),
        json={"decision": "REJECT", "opinion": "   "},
    )
    rejected = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"]),
        json={"decision": "REJECT", "opinion": "结算量与本地计量结果不一致"},
    )

    assert blank.status_code == 422
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["decision"] == "REJECT"
    assert rejected.json()["confirm_status"] == "REJECTED"
    assert rejected.json()["task"]["status"] == "DRAFT"
    assert rejected.json()["task"]["ttc"]["state"] == "REWORK"

    with SessionLocal() as db:
        assert db.scalar(
            select(func.count(Signature.signature_id)).where(
                Signature.target_type == "RESULT_CONFIRM",
                Signature.target_id == result["result_id"],
            )
        ) == 0
        reject_signature = db.scalar(
            select(Signature).where(
                Signature.target_type == "RESULT_REJECT",
                Signature.target_id == result["result_id"],
            )
        )
        assert reject_signature is not None
        evidence = db.scalar(
            select(BlockchainEvidence).where(
                BlockchainEvidence.biz_type == "RESULT_DECISION",
                BlockchainEvidence.biz_id == result["result_id"],
            )
        )
        assert evidence is not None
        assert evidence.payload_json["decision"] == "REJECT"
        assert evidence.payload_json["raw_opinion_included"] is False


def test_confirmation_cannot_override_an_abnormal_ttc_state(client, auth_headers):
    result = _result_for(client, auth_headers, "org-generator-t01")
    with SessionLocal() as db:
        task = db.get(SettlementTask, TASK_ID)
        assert task is not None
        task.ttc_state = "COMPUTE_EXEC"
        task.status = "PENDING_CONFIRMATION"
        db.commit()

    response = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"]),
        json={"decision": "APPROVE", "opinion": "尝试跨状态确认"},
    )

    assert response.status_code == 409
    with SessionLocal() as db:
        persisted_result = db.get(SettlementResult, result["result_id"])
        assert persisted_result is not None
        assert persisted_result.confirm_status != "CONFIRMED"
        assert db.scalar(
            select(func.count(Signature.signature_id)).where(
                Signature.target_type == "RESULT_CONFIRM",
                Signature.target_id == result["result_id"],
            )
        ) == 0


def test_audit_gate_open_anomaly_and_confirmation_replay_are_fail_closed(
    client, auth_headers
):
    generator_result = _result_for(client, auth_headers, "org-generator-t01")
    retailer_result = _result_for(client, auth_headers, "org-retailer-t01")

    first_headers = _etag_headers(client, auth_headers["generator"])
    first = client.post(
        f"/api/results/{generator_result['result_id']}/confirm",
        headers=first_headers,
        json={"decision": "APPROVE", "opinion": "发电侧同意结算结果"},
    )
    assert first.status_code == 200, first.text
    with SessionLocal() as db:
        version_after_first = db.get(SettlementTask, TASK_ID).state_version
        signature_count_after_first = db.scalar(
            select(func.count(Signature.signature_id)).where(
                Signature.target_type == "RESULT_CONFIRM",
                Signature.target_id == generator_result["result_id"],
            )
        )
    replay = client.post(
        f"/api/results/{generator_result['result_id']}/confirm",
        # Exact immutable decision replay remains safe even when this ETag is
        # stale after the first confirmation.
        headers=first_headers,
        json={"decision": "APPROVE", "opinion": "发电侧同意结算结果"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["signature"] == first.json()["signature"]
    with SessionLocal() as db:
        assert db.get(SettlementTask, TASK_ID).state_version == version_after_first
        assert db.scalar(
            select(func.count(Signature.signature_id)).where(
                Signature.target_type == "RESULT_CONFIRM",
                Signature.target_id == generator_result["result_id"],
            )
        ) == signature_count_after_first == 1

    approval_required = client.post(
        f"/api/results/{retailer_result['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"]),
        json={"decision": "APPROVE", "opinion": "售电侧同意结算结果"},
    )
    assert approval_required.status_code == 409
    assert approval_required.json()["detail"]["code"] == "AUDIT_APPROVAL_REQUIRED"

    approved_report = _approve_report(client, auth_headers)
    assert approved_report["status"] == "APPROVED"
    with SessionLocal() as db:
        anomaly = AnomalyEvent(
            task_id=TASK_ID,
            event_type="SECURITY_GATE_TEST",
            risk_level="HIGH",
            title="待处置安全异常",
            description="最终确认前必须先处置",
            evidence_json={
                "previous_task_status": "PARTIALLY_CONFIRMED",
                "previous_risk_level": "MEDIUM",
            },
            status="OPEN",
        )
        db.add(anomaly)
        db.commit()
        anomaly_id = anomaly.event_id

    anomaly_blocked = client.post(
        f"/api/results/{retailer_result['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"]),
        json={"decision": "APPROVE", "opinion": "售电侧同意结算结果"},
    )
    assert anomaly_blocked.status_code == 409
    assert anomaly_blocked.json()["detail"]["code"] == "OPEN_ANOMALY_BLOCKS_AUDIT_GATE"

    resolved = client.post(
        f"/api/anomalies/{anomaly_id}/resolve",
        headers=auth_headers["regulator"],
        json={"resolution": "已复核证据并关闭异常"},
    )
    final = client.post(
        f"/api/results/{retailer_result['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"]),
        json={"decision": "APPROVE", "opinion": "售电侧同意结算结果"},
    )

    assert resolved.status_code == 200
    assert final.status_code == 200, final.text
    assert final.json()["task"]["ttc"]["state"] == "ARCHIVED"
    with SessionLocal() as db:
        evidence = db.scalar(
            select(BlockchainEvidence).where(
                BlockchainEvidence.biz_type == "AUDIT_REPORT_DECISION",
                BlockchainEvidence.biz_id == approved_report["report_id"],
            )
        )
        assert evidence is not None
        assert evidence.payload_json["decision"] == "APPROVE"
        assert evidence.payload_json["signature_id"] == approved_report["signature_id"]


def test_audit_report_rejection_records_decision_and_enters_rework(client, auth_headers):
    report = _latest_report(client, auth_headers)
    response = client.post(
        f"/api/audit/reports/{report['report_id']}/decision",
        headers=auth_headers["regulator"],
        json={"decision": "REJECT", "opinion": "审计证据不足，退回重算"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REJECTED"
    with SessionLocal() as db:
        persisted_report = db.get(AuditReport, report["report_id"])
        task = db.get(SettlementTask, TASK_ID)
        assert persisted_report is not None and persisted_report.status == "REJECTED"
        assert task is not None and task.ttc_state == "REWORK"
        assert task.status == "DRAFT"
        signature = db.scalar(
            select(Signature).where(
                Signature.target_type == "AUDIT_REPORT_REJECT",
                Signature.target_id == report["report_id"],
            )
        )
        evidence = db.scalar(
            select(BlockchainEvidence).where(
                BlockchainEvidence.biz_type == "AUDIT_REPORT_DECISION",
                BlockchainEvidence.biz_id == report["report_id"],
            )
        )
        assert signature is not None
        assert evidence is not None and evidence.payload_json["decision"] == "REJECT"


def test_result_confirmation_requires_a_concrete_if_match(client, auth_headers):
    result = _result_for(client, auth_headers, "org-generator-t01")
    payload = {"decision": "APPROVE", "opinion": "同意结算结果"}

    missing = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers=auth_headers["generator"],
        json=payload,
    )
    wildcard = client.post(
        f"/api/results/{result['result_id']}/confirm",
        headers={**auth_headers["generator"], "If-Match": "*"},
        json=payload,
    )

    assert missing.status_code == 428
    assert missing.json()["code"] == "PRECONDITION_REQUIRED"
    assert wildcard.status_code == 412
    schema = client.get("/api/openapi.json").json()
    operations = (
        schema["paths"]["/api/settlement/tasks/{task_id}/run"]["post"],
        schema["paths"]["/api/results/{result_id}/confirm"]["post"],
    )
    for operation in operations:
        parameter = next(
            item for item in operation["parameters"] if item["name"] == "If-Match"
        )
        assert parameter["required"] is True
    with SessionLocal() as db:
        persisted = db.get(SettlementResult, result["result_id"])
        assert persisted is not None and persisted.confirm_status == "UNCONFIRMED"


def test_rework_same_hash_ignores_prior_attempt_decisions(client, auth_headers):
    old_results = client.get(
        f"/api/settlement/results?task_id={TASK_ID}",
        headers=auth_headers["exchange"],
    ).json()
    old_summary = next(item for item in old_results if item["result_scope"] == "SUMMARY")
    old_scoped = {item["org_id"]: item for item in old_results if item["result_scope"] == "ORG"}

    first_approval = client.post(
        f"/api/results/{old_scoped['org-generator-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"]),
        json={"decision": "APPROVE", "opinion": "首轮发电侧同意"},
    )
    first_rejection = client.post(
        f"/api/results/{old_scoped['org-retailer-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"]),
        json={"decision": "REJECT", "opinion": "首轮售电侧退回重算"},
    )
    assert first_approval.status_code == first_rejection.status_code == 200
    assert first_rejection.json()["task"]["ttc"]["state"] == "REWORK"

    rerun = client.post(
        f"/api/settlement/tasks/{TASK_ID}/run",
        headers={
            **_etag_headers(client, auth_headers["exchange"]),
            "Idempotency-Key": "same-hash-rework-attempt-02",
        },
        json={
            "compute_mode": "LOCAL_CONTROLLED",
            "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
        },
    )
    assert rerun.status_code == 200, rerun.text
    new_results = rerun.json()["results"]
    new_summary = next(item for item in new_results if item["result_scope"] == "SUMMARY")
    new_scoped = {item["org_id"]: item for item in new_results if item["result_scope"] == "ORG"}
    assert new_summary["result_hash"] == old_summary["result_hash"]
    assert new_summary["attempt_id"] != old_summary["attempt_id"]
    assert len(new_scoped) == 2
    assert all(item["confirm_status"] == "UNCONFIRMED" for item in new_scoped.values())

    second_approval = client.post(
        f"/api/results/{new_scoped['org-generator-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"]),
        json={"decision": "APPROVE", "opinion": "次轮发电侧同意"},
    )
    assert second_approval.status_code == 200, second_approval.text
    report = _latest_report(client, auth_headers)
    report_approval = client.post(
        f"/api/audit/reports/{report['report_id']}/decision",
        headers=auth_headers["regulator"],
        json={"decision": "APPROVE", "opinion": "次轮证据复核通过"},
    )
    assert report_approval.status_code == 200, report_approval.text
    final = client.post(
        f"/api/results/{new_scoped['org-retailer-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"]),
        json={"decision": "APPROVE", "opinion": "次轮售电侧同意"},
    )
    assert final.status_code == 200, final.text
    assert final.json()["task"]["ttc"]["state"] == "ARCHIVED"
