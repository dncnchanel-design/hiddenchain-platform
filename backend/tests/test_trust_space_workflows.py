from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    AuditLog,
    DataContract,
    DataSpaceAgreement,
    DataUsageRequest,
    Organization,
    PrivacyComputeJob,
    SettlementResult,
    SettlementRule,
    SettlementTask,
    TaskParticipant,
    utc_now,
)
from app.security import sha256_json
from app.services.adapters import LocalEvidenceLedgerAdapter
from app.trust_models import ExecutionSnapshot, TtcAttempt


TASK_ID = "batch3-trust-space-task"
CONTRACT_ID = "batch3-trust-space-contract"


def _task_with_attempt(*, participants: bool = True, task_id: str = TASK_ID) -> str:
    with SessionLocal() as db:
        rule = db.scalar(select(SettlementRule).order_by(SettlementRule.created_at))
        assert rule is not None
        task = SettlementTask(
            task_id=task_id,
            capsule_id=f"{task_id}-capsule",
            task_name="Batch 3 Trusted Space task",
            trade_batch_no="BATCH3-001",
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 2),
            rule_id=rule.rule_id,
            creator_org_id="org-exchange-t01",
            status="PENDING_CONFIRMATION",
            current_stage="结果确认",
            ttc_state="HUMAN_REVIEW",
            current_attempt=1,
            state_version=4,
        )
        db.add(task)
        if participants:
            db.add_all(
                [
                    TaskParticipant(
                        task_id=task_id,
                        org_id="org-generator-t01",
                        role_in_task="GENERATOR",
                    ),
                    TaskParticipant(
                        task_id=task_id,
                        org_id="org-retailer-t01",
                        role_in_task="RETAILER",
                    ),
                ]
            )
        attempt = TtcAttempt(
            task_id=task_id,
            capsule_id=f"{task_id}-capsule",
            attempt_no=1,
            current_state="HUMAN_REVIEW",
            status="ACTIVE",
            trace_id="trace-batch3",
        )
        db.add(attempt)
        db.flush()
        snapshot = ExecutionSnapshot(
            task_id=task_id,
            attempt_id=attempt.attempt_id,
            snapshot_version=1,
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            rule_hash=rule.rule_hash,
            policy_refs_json=[],
            contract_refs_json=[],
            data_refs_json=[],
            algorithm_code="CONTROLLED_SETTLEMENT_V1",
            algorithm_version="1.0",
            algorithm_hash=sha256_json({"algorithm": "CONTROLLED_SETTLEMENT_V1"}),
            parameters_json={},
            units_json={},
            canonical_payload_json={"task_id": task_id},
            snapshot_hash=sha256_json({"task_id": task_id, "version": 1}),
            frozen_by_did="did:hiddenchain:org:org-exchange-t01",
            trace_id="trace-batch3",
        )
        db.add(snapshot)
        task.execution_snapshot_id = snapshot.snapshot_id
        task.execution_snapshot_hash = snapshot.snapshot_hash
        db.commit()
        return attempt.attempt_id


def _contract_with_agreement() -> str:
    with SessionLocal() as db:
        now = utc_now()
        contract = DataContract(
            contract_id=CONTRACT_ID,
            task_id=TASK_ID,
            provider_org_id="org-generator-t01",
            consumer_type="org-exchange-t01",
            purpose="POWER_SETTLEMENT",
            data_refs_json=["upload-generation-july-t01"],
            policy_json={"output_mode": "AGGREGATE_ONLY", "raw_data_export": False},
            policy_hash=sha256_json({"output_mode": "AGGREGATE_ONLY"}),
            status="ACTIVE",
            valid_from=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=30),
        )
        db.add(contract)
        db.add(
            DataSpaceAgreement(
                agreement_id="batch3-trust-space-agreement",
                contract_id=CONTRACT_ID,
                task_id=TASK_ID,
                provider_org_id="org-generator-t01",
                consumer_org_id="org-exchange-t01",
                provider_did="did:hiddenchain:org:org-generator-t01",
                consumer_did="did:hiddenchain:org:org-exchange-t01",
                protocol_version="HCDS-1.0",
                state="OFFERED",
                requested_purpose="POWER_SETTLEMENT",
                algorithm_code="CONTROLLED_SETTLEMENT_V1",
                data_product_ids_json=["upload-generation-july-t01"],
                offered_policy_hash=contract.policy_hash,
                negotiated_policy_hash=contract.policy_hash,
                valid_from=now - timedelta(minutes=1),
                expires_at=now + timedelta(days=30),
                max_uses=1,
                use_count=0,
                decision_json={},
                last_receipt_json={},
                trace_id="trace-batch3-contract",
            )
        )
        db.commit()
    return CONTRACT_ID


def test_contract_negotiation_persists_state_machine_scope_and_audit(
    client, auth_headers
):
    _task_with_attempt()
    contract_id = _contract_with_agreement()
    schema = client.get("/api/openapi.json").json()["paths"]
    for path in (
        "/api/trust-space/contracts",
        "/api/trust-space/contracts/{contract_id}",
        "/api/trust-space/contracts/{contract_id}/events",
        "/api/trust-space/contracts/{contract_id}/accept",
        "/api/trust-space/contracts/{contract_id}/reject",
        "/api/trust-space/contracts/{contract_id}/counter",
    ):
        assert path in schema

    detail = client.get(
        f"/api/trust-space/contracts/{contract_id}", headers=auth_headers["exchange"]
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["contract"]["provider"]["org_id"] == "org-generator-t01"
    assert detail.json()["allowed_actions"] == ["accept", "comment", "counter", "reject"]

    first = client.post(
        f"/api/trust-space/contracts/{contract_id}/events",
        headers={
            **auth_headers["generator"],
            "If-Match": '"0"',
            "Idempotency-Key": "batch3-contract-comment",
        },
        json={"event_type": "COMMENT", "message": "请确认只输出聚合结果"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["state_version"] == 1
    replay = client.post(
        f"/api/trust-space/contracts/{contract_id}/events",
        headers={
            **auth_headers["generator"],
            "If-Match": '"0"',
            "Idempotency-Key": "batch3-contract-comment",
        },
        json={"event_type": "COMMENT", "message": "请确认只输出聚合结果"},
    )
    assert replay.status_code == 201
    assert replay.json()["idempotent_replay"] is True

    invalid_attachment = client.post(
        f"/api/trust-space/contracts/{contract_id}/events",
        headers={**auth_headers["generator"], "If-Match": '"1"'},
        json={
            "event_type": "ATTACHMENT",
            "attachments": [{"name": "unregistered.pdf"}],
        },
    )
    assert invalid_attachment.status_code == 422

    counter = client.post(
        f"/api/trust-space/contracts/{contract_id}/counter",
        headers={
            **auth_headers["exchange"],
            "If-Match": '"1"',
            "Idempotency-Key": "batch3-contract-counter",
        },
        json={"message": "接受受控聚合", "terms": {"max_uses": 2}},
    )
    assert counter.status_code == 200, counter.text
    assert counter.json()["to_state"] == "NEGOTIATED"

    stale = client.post(
        f"/api/trust-space/contracts/{contract_id}/counter",
        headers={**auth_headers["exchange"], "If-Match": '"1"'},
        json={"message": "过期版本"},
    )
    assert stale.status_code == 412

    accepted = client.post(
        f"/api/trust-space/contracts/{contract_id}/accept",
        headers={**auth_headers["generator"], "If-Match": '"2"'},
        json={"message": "同意"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["to_state"] == "ACTIVE"

    closed = client.post(
        f"/api/trust-space/contracts/{contract_id}/reject",
        headers={**auth_headers["generator"], "If-Match": '"3"'},
        json={"message": "不应再拒绝"},
    )
    assert closed.status_code == 409

    outsider = client.get(
        f"/api/trust-space/contracts/{contract_id}", headers=auth_headers["retailer"]
    )
    assert outsider.status_code == 404
    with SessionLocal() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action_code == "CONTRACT_NEGOTIATION_ACCEPT",
                AuditLog.target_id == contract_id,
            )
        )
        assert audit is not None


def test_ttc_detail_cursor_transition_and_role_scope(client, auth_headers):
    attempt_id = _task_with_attempt()
    detail = client.get(f"/api/trust-space/ttc/{TASK_ID}", headers=auth_headers["exchange"])
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["task"]["task_id"] == TASK_ID
    assert body["attempts"][0]["attempt_id"] == attempt_id
    assert body["snapshots"][0]["snapshot_hash"]
    assert body["source_of_truth"].startswith("settlement_tasks")
    assert body["task"]["phase_progress_estimate"]["source"] == "TTC_STATE_PHASE_ESTIMATE_V1"
    assert "非实时执行进度" in body["task"]["phase_progress_estimate"]["label"]

    events = client.get(
        f"/api/trust-space/ttc/{TASK_ID}/events?limit=1",
        headers=auth_headers["exchange"],
    )
    assert events.status_code == 200
    assert events.json()["has_more"] is False
    assert events.json()["items"] == []

    invalid = client.post(
        f"/api/trust-space/ttc/{TASK_ID}/transitions",
        headers={**auth_headers["exchange"], "If-Match": '"4"'},
        json={"to_state": "DATA_AUTHORIZED", "trigger": "bad", "reason": "不能跳跃"},
    )
    assert invalid.status_code == 403

    transitioned = client.post(
        f"/api/trust-space/ttc/{TASK_ID}/transitions",
        headers={**auth_headers["exchange"], "If-Match": '"4"'},
        json={"to_state": "CANCELLED", "trigger": "USER_CANCEL", "reason": "人工取消"},
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["ttc_state"] == "CANCELLED"
    assert transitioned.headers["etag"] == '"5"'

    after = client.get(
        f"/api/trust-space/ttc/{TASK_ID}/events?limit=1",
        headers=auth_headers["exchange"],
    )
    assert after.status_code == 200
    assert after.json()["items"][0]["kind"] == "TTC_TRANSITION"


def test_computation_truth_labels_and_log_cursor(client, auth_headers):
    attempt_id = _task_with_attempt()
    empty_attempt_id = _task_with_attempt(participants=False, task_id="batch3-empty-compute-task")
    with SessionLocal() as db:
        job = PrivacyComputeJob(
            task_id=TASK_ID,
            algorithm_code="CONTROLLED_SETTLEMENT_V1",
            adapter_code="LOCAL_CONTROLLED_SETTLEMENT_V1",
            input_hashes_json=["input-hash"],
            output_hash="output-hash",
            result_json={"aggregate": 1},
            status="SUCCESS",
            progress=100,
            logs_json=["started", "finished"],
            privacy_guarantees_json={"raw_data_exposed": False},
            attempt_id=attempt_id,
        )
        db.add(job)
        empty_job = PrivacyComputeJob(
            task_id="batch3-empty-compute-task",
            algorithm_code="CONTROLLED_SETTLEMENT_V1",
            adapter_code="LOCAL_CONTROLLED_SETTLEMENT_V1",
            input_hashes_json=[],
            status="QUEUED",
            progress=0,
            logs_json=[],
            privacy_guarantees_json={},
            attempt_id=empty_attempt_id,
        )
        db.add(empty_job)
        db.commit()
        job_id, empty_job_id = job.job_id, empty_job.job_id

    payload = client.get(
        f"/api/trust-space/computations/{job_id}", headers=auth_headers["exchange"]
    )
    assert payload.status_code == 200, payload.text
    assert payload.json()["external_execution"]["capability_state"] == "ADAPTER"
    assert payload.json()["external_execution"]["tee_attestation"] == "NOT_CONFIGURED"
    assert payload.json()["participants"]
    assert "retry" not in payload.json()["allowed_actions"]
    assert "cancel" not in payload.json()["allowed_actions"]
    logs = client.get(
        f"/api/trust-space/computations/{job_id}/events?limit=1",
        headers=auth_headers["exchange"],
    )
    assert logs.status_code == 200
    assert logs.json()["next_cursor"] == "1"
    assert logs.json()["items"][0]["detail"] == "started"
    forbidden = client.get(
        f"/api/trust-space/computations/{job_id}", headers=auth_headers["regulator"]
    )
    assert forbidden.status_code == 200
    blocked = client.get(
        f"/api/trust-space/computations/{empty_job_id}", headers=auth_headers["exchange"]
    )
    assert blocked.status_code == 200
    assert blocked.json()["external_execution"]["capability_state"] == "BLOCKED"
    assert blocked.json()["external_execution"]["cross_domain_participants"] == []


def test_computation_controls_are_truthful_scoped_idempotent_and_audited(client, auth_headers):
    task_id = "batch3-compute-control-task"
    with SessionLocal() as db:
        rule = db.scalar(select(SettlementRule).order_by(SettlementRule.created_at))
        assert rule is not None
        task = SettlementTask(
            task_id=task_id,
            capsule_id=f"{task_id}-capsule",
            task_name="Queued compute control task",
            trade_batch_no="BATCH3-CONTROL",
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 2),
            rule_id=rule.rule_id,
            creator_org_id="org-exchange-t01",
            status="CREATED",
            current_stage="待执行",
            ttc_state="INIT",
            current_attempt=0,
            state_version=1,
        )
        db.add(task)
        job = PrivacyComputeJob(
            task_id=task_id,
            algorithm_code="CONTROLLED_SETTLEMENT_V1",
            adapter_code="LOCAL_CONTROLLED_SETTLEMENT_V1",
            input_hashes_json=[],
            status="QUEUED",
            progress=0,
            logs_json=["queued"],
            privacy_guarantees_json={},
        )
        db.add(job)
        db.commit()
        job_id = job.job_id

    paths = client.get("/api/openapi.json").json()["paths"]
    assert f"/api/trust-space/computations/{{job_id}}/cancel" in paths
    assert f"/api/trust-space/computations/{{job_id}}/retry" in paths

    detail = client.get(
        f"/api/trust-space/computations/{job_id}", headers=auth_headers["exchange"]
    )
    assert detail.status_code == 200, detail.text
    assert "cancel" in detail.json()["allowed_actions"]
    assert "retry" not in detail.json()["allowed_actions"]
    assert "retry" in detail.json()["action_reasons"]

    missing_headers = client.post(
        f"/api/trust-space/computations/{job_id}/cancel",
        headers=auth_headers["exchange"],
        json={"reason": "人工取消"},
    )
    assert missing_headers.status_code == 422
    assert missing_headers.json()["detail"]["code"] == "COMPUTE_ACTION_IDEMPOTENCY_REQUIRED"

    command_headers = {
        **auth_headers["exchange"],
        "If-Match": '"1"',
        "Idempotency-Key": "batch3-compute-cancel-1",
    }
    cancelled = client.post(
        f"/api/trust-space/computations/{job_id}/cancel",
        headers=command_headers,
        json={"reason": "人工取消"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["job"]["status"] == "CANCELLED"
    assert cancelled.json()["idempotent_replay"] is False
    assert cancelled.headers["etag"] == '"2"'
    replay = client.post(
        f"/api/trust-space/computations/{job_id}/cancel",
        headers=command_headers,
        json={"reason": "人工取消"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    conflict = client.post(
        f"/api/trust-space/computations/{job_id}/cancel",
        headers={**command_headers, "If-Match": '"2"'},
        json={"reason": "不同参数"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "COMPUTE_ACTION_IDEMPOTENCY_CONFLICT"

    blocked_retry = client.post(
        f"/api/trust-space/computations/{job_id}/retry",
        headers={**auth_headers["exchange"], "If-Match": '"2"', "Idempotency-Key": "batch3-compute-retry-1"},
        json={"reason": "重试"},
    )
    assert blocked_retry.status_code == 409
    assert blocked_retry.json()["detail"]["code"] == "COMPUTE_RETRY_BLOCKED"

    stale = client.post(
        f"/api/trust-space/computations/{job_id}/cancel",
        headers={**auth_headers["exchange"], "If-Match": '"1"', "Idempotency-Key": "batch3-compute-cancel-2"},
        json={"reason": "过期版本"},
    )
    assert stale.status_code == 412
    outsider = client.get(
        f"/api/trust-space/computations/{job_id}", headers=auth_headers["generator"]
    )
    assert outsider.status_code == 404

    with SessionLocal() as db:
        job = db.get(PrivacyComputeJob, job_id)
        assert job is not None and job.status == "CANCELLED"
        assert job.state_version == 2
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action_code == "CANCEL_PRIVACY_COMPUTE",
                AuditLog.target_id == job_id,
            )
        )
        assert audit is not None


def test_results_hash_evidence_verify_and_confirmation_scope(client, auth_headers):
    attempt_id = _task_with_attempt()
    with SessionLocal() as db:
        value = {"aggregate": 2}
        result = SettlementResult(
            task_id=TASK_ID,
            attempt_id=attempt_id,
            org_id=None,
            result_scope="SUMMARY",
            result_json=value,
            result_hash=sha256_json(value),
            confirm_status="NOT_REQUIRED",
        )
        db.add(result)
        db.flush()
        no_evidence_result = SettlementResult(
            task_id=TASK_ID,
            attempt_id=attempt_id,
            org_id=None,
            result_scope="SUMMARY_HISTORY",
            result_json={"aggregate": 3},
            result_hash=sha256_json({"aggregate": 3}),
            confirm_status="NOT_REQUIRED",
        )
        db.add(no_evidence_result)
        db.flush()
        evidence = LocalEvidenceLedgerAdapter().anchor(
            db,
            task_id=TASK_ID,
            stage="POST_COMPUTE",
            biz_type="BATCH3_RESULT",
            biz_id=result.result_id,
            payload={"result_hash": result.result_hash},
        )
        db.commit()
        result_id, no_evidence_id, evidence_id = (
            result.result_id,
            no_evidence_result.result_id,
            evidence.evidence_id,
        )

    detail = client.get(
        f"/api/trust-space/results/{result_id}", headers=auth_headers["exchange"]
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["result"]["result_hash"]
    assert detail.json()["evidence"][0]["tx_hash"]
    no_evidence = client.get(
        f"/api/trust-space/results/{no_evidence_id}", headers=auth_headers["exchange"]
    )
    assert no_evidence.status_code == 200
    assert no_evidence.json()["evidence"] == []
    verified = client.get(
        f"/api/trust-space/evidence/{evidence_id}/verify",
        headers=auth_headers["exchange"],
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["matched"] is True
    outsider = client.get(
        f"/api/trust-space/evidence/{evidence_id}/verify",
        headers=auth_headers["retailer"],
    )
    # Retailer is a real participant of this task, so the evidence is
    # intentionally visible to it; scope is based on task participation, not
    # on the result's summary organization.
    assert outsider.status_code == 200

    list_response = client.get("/api/trust-space/results", headers=auth_headers["exchange"])
    assert list_response.status_code == 200
    assert any(item["result_id"] == result_id for item in list_response.json()["items"])


def test_audit_scope_and_server_exports_are_real_and_typed(client, auth_headers):
    _task_with_attempt()
    with SessionLocal() as db:
        db.add(
            AuditLog(
                actor_user_id="user-exchange",
                actor_org_id="org-exchange-t01",
                actor_name="交易中心验证员",
                action_code="BATCH3_AUDIT_EVENT",
                target_type="SETTLEMENT_TASK",
                target_id=TASK_ID,
                result="SUCCESS",
                trace_id="trace-batch3-audit",
                details_json={"sensitive_raw_data_included": False},
            )
        )
        db.commit()

    audit = client.get("/api/trust-space/audit", headers=auth_headers["exchange"])
    assert audit.status_code == 200, audit.text
    assert any(item["action_code"] == "BATCH3_AUDIT_EVENT" for item in audit.json()["items"])
    task_audit = client.get(
        f"/api/trust-space/audit/tasks/{TASK_ID}", headers=auth_headers["exchange"]
    )
    assert task_audit.status_code == 200
    assert task_audit.json()["task"]["task_id"] == TASK_ID

    json_export = client.get(
        "/api/trust-space/audit/export?format=json", headers=auth_headers["exchange"]
    )
    assert json_export.status_code == 200
    assert json_export.headers["content-type"].startswith("application/json")
    assert "BATCH3_AUDIT_EVENT" in json_export.text
    csv_export = client.get(
        "/api/trust-space/audit/export?format=csv", headers=auth_headers["exchange"]
    )
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert "record_type,record_id" in csv_export.text
    denied = client.get("/api/trust-space/audit", headers=auth_headers["generator"])
    assert denied.status_code == 403
    with SessionLocal() as db:
        assert db.scalar(
            select(AuditLog).where(AuditLog.action_code == "EXPORT_AUDIT_RECORDS")
        ) is not None
