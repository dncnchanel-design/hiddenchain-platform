from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import SettlementTask, TaskParticipant, utc_now
from app.services.evidence_outbox import LocalHashAnchorAdapter
from app.services.formal_evidence import process_local_demo_outbox
from app.trust_models import EvidenceBatch, EvidenceOutbox


def _etag_headers(client, base_headers: dict[str, str], task_id: str) -> dict[str, str]:
    response = client.get(f"/api/settlement/tasks/{task_id}", headers=base_headers)
    assert response.status_code == 200, response.text
    return {**base_headers, "If-Match": response.headers["etag"]}


def _new_task_payload(name: str = "幂等可信结算任务") -> dict:
    return {
        "task_name": name,
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


def test_task_creation_idempotency_key_replays_and_rejects_rebinding(client, auth_headers):
    headers = {**auth_headers["exchange"], "Idempotency-Key": "task-create-formal-001"}
    first = client.post("/api/settlement/tasks", headers=headers, json=_new_task_payload())
    replay = client.post("/api/settlement/tasks", headers=headers, json=_new_task_payload())
    conflict = client.post(
        "/api/settlement/tasks",
        headers=headers,
        json=_new_task_payload("另一项不同任务"),
    )

    assert first.status_code == replay.status_code == 201
    assert first.json()["task_id"] == replay.json()["task_id"]
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.headers["ETag"] == first.headers["ETag"]
    assert conflict.status_code == 409


def test_ttc_run_replays_by_key_and_rejects_stale_version(client, auth_headers):
    run_payload = {
        "compute_mode": "LOCAL_CONTROLLED",
        "algorithm_code": "CONTROLLED_SETTLEMENT_V1",
    }
    missing = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=auth_headers["exchange"],
        json=run_payload,
    )
    wildcard = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers={**auth_headers["exchange"], "If-Match": "*"},
        json=run_payload,
    )
    stale = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers={**auth_headers["exchange"], "If-Match": '"999"'},
        json=run_payload,
    )
    assert missing.status_code == 428
    assert wildcard.status_code == stale.status_code == 412

    headers = {
        **_etag_headers(client, auth_headers["exchange"], "task-ready-t01"),
        "Idempotency-Key": "ttc-run-formal-001",
    }
    first = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=headers,
        json=run_payload,
    )
    replay = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers=headers,
        json=run_payload,
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["task"]["ttc"]["state"] == "RESULT_CONFIRM"
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["task"]["task_id"] == first.json()["task"]["task_id"]


def test_final_confirmation_writes_merkle_outbox_and_archives_ttc(client, auth_headers):
    results = client.get(
        "/api/settlement/results?task_id=task-history-t01",
        headers=auth_headers["exchange"],
    ).json()
    scoped = {item["org_id"]: item for item in results if item["result_scope"] == "ORG"}
    generator_result = scoped["org-generator-t01"]
    retailer_result = scoped["org-retailer-t01"]

    first = client.post(
        f"/api/results/{generator_result['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"], "task-history-t01"),
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )
    reports = client.get("/api/audit/reports", headers=auth_headers["regulator"]).json()
    report = next(item for item in reports if item["task_id"] == "task-history-t01")
    audit_approval = client.post(
        f"/api/audit/reports/{report['report_id']}/decision",
        headers=auth_headers["regulator"],
        json={"decision": "APPROVE", "opinion": "审计证据和结算哈希复核通过"},
    )
    final = client.post(
        f"/api/results/{retailer_result['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"], "task-history-t01"),
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )

    assert first.status_code == 200
    assert audit_approval.status_code == 200, audit_approval.text
    assert final.status_code == 200, final.text
    assert final.json()["formal_evidence"]["status"] == "PUBLISHED_DEMO"
    assert final.json()["formal_evidence"]["consensus_verified"] is False
    assert final.json()["task"]["ttc"]["state"] == "ARCHIVED"

    batches = client.get(
        "/api/evidence/batches?task_id=task-history-t01",
        headers=auth_headers["regulator"],
    )
    assert batches.status_code == 200
    payload = batches.json()
    assert {item["batch_type"] for item in payload} == {"FINAL_SETTLEMENT", "TTC_ARCHIVE"}
    assert all(item["anchor"]["capability_label"] == "DEMO" for item in payload)
    assert all(item["anchor"]["consensus_verified"] is False for item in payload)
    assert all(not child["raw_sensitive_data_included"] for item in payload for child in item["items"])

    outbox = client.get(
        "/api/evidence/outbox?task_id=task-history-t01",
        headers=auth_headers["regulator"],
    )
    assert outbox.status_code == 200
    assert len(outbox.json()) == 2
    assert {item["status"] for item in outbox.json()} == {"PUBLISHED"}


def test_failed_anchor_receipt_never_archives_ttc(
    client, auth_headers, monkeypatch
):
    results = client.get(
        "/api/settlement/results?task_id=task-history-t01",
        headers=auth_headers["exchange"],
    ).json()
    scoped = {item["org_id"]: item for item in results if item["result_scope"] == "ORG"}
    first = client.post(
        f"/api/results/{scoped['org-generator-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["generator"], "task-history-t01"),
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )
    reports = client.get("/api/audit/reports", headers=auth_headers["regulator"]).json()
    report = next(item for item in reports if item["task_id"] == "task-history-t01")
    audit_approval = client.post(
        f"/api/audit/reports/{report['report_id']}/decision",
        headers=auth_headers["regulator"],
        json={"decision": "APPROVE", "opinion": "审计证据和结算哈希复核通过"},
    )
    original_anchor = LocalHashAnchorAdapter.anchor

    def failed_anchor(self, request):
        return replace(original_anchor(self, request), status="REJECTED")

    monkeypatch.setattr(LocalHashAnchorAdapter, "anchor", failed_anchor)
    final = client.post(
        f"/api/results/{scoped['org-retailer-t01']['result_id']}/confirm",
        headers=_etag_headers(client, auth_headers["retailer"], "task-history-t01"),
        json={"decision": "APPROVE", "opinion": "同意结算结果"},
    )

    assert first.status_code == 200
    assert audit_approval.status_code == 200, audit_approval.text
    assert final.status_code == 200, final.text
    assert final.json()["formal_evidence"]["status"] == "RETRY_WAIT"
    assert final.json()["task"]["ttc"]["state"] == "ANCHOR_RETRY"

    batches = client.get(
        "/api/evidence/batches?task_id=task-history-t01",
        headers=auth_headers["regulator"],
    ).json()
    assert [item["batch_type"] for item in batches] == ["FINAL_SETTLEMENT"]
    assert batches[0]["status"] == "RETRY_WAIT"
    outbox = client.get(
        "/api/evidence/outbox?task_id=task-history-t01",
        headers=auth_headers["regulator"],
    ).json()
    assert [item["status"] for item in outbox] == ["RETRY_WAIT"]

    # Exhaust the same durable event.  A terminal receipt failure must close
    # the attempt as FAILED and must never create the TTC_ARCHIVE batch.
    with SessionLocal() as db:
        record = db.scalar(
            select(EvidenceOutbox).where(
                EvidenceOutbox.task_id == "task-history-t01"
            )
        )
        record.attempt_count = 4
        record.next_attempt_at = utc_now() - timedelta(seconds=1)
        db.commit()
    with SessionLocal() as db:
        exhausted = process_local_demo_outbox(db, limit=25)
        db.commit()
        task = db.get(SettlementTask, "task-history-t01")
        batches = list(
            db.scalars(
                select(EvidenceBatch).where(
                    EvidenceBatch.task_id == "task-history-t01"
                )
            )
        )
        assert exhausted[0]["status"] == "DEAD_LETTER"
        assert task.ttc_state == "FAILED"
        assert task.status == "EXCEPTION"
        assert [item.batch_type for item in batches] == ["FINAL_SETTLEMENT"]


def test_version_readiness_asset_passport_and_mpc_truth_labels(client, auth_headers):
    version = client.get("/api/version")
    readiness = client.get("/api/health/ready")
    uploads = client.get(
        "/api/data/uploads?asset_type=GENERATION_DATA",
        headers=auth_headers["generator"],
    )
    mpc = client.get("/api/privacy/mpc/status", headers=auth_headers["regulator"])

    assert version.status_code == readiness.status_code == uploads.status_code == mpc.status_code == 200
    assert readiness.json()["status"] == "READY"
    assert readiness.json()["checks"]["database_migrations"]["pending"] == []
    assert version.json()["service_version"] == "0.2.0"
    assert uploads.json()[0]["formal_asset"]["raw_payload_exposed"] is False
    asset_id = uploads.json()[0]["formal_asset"]["asset_id"]
    passport = client.get(
        f"/api/trust-domain/assets/{asset_id}/passport",
        headers=auth_headers["generator"],
    )
    assert passport.status_code == 200
    assert passport.json()["passport"]["passport_hash"]
    assert passport.json()["version"]["data_hash"]
    assert mpc.json()["capability_status"] == "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST"
    assert mpc.json()["cross_domain_production_privacy"] is False


def test_trust_domain_reads_are_tenant_scoped(client, auth_headers):
    uploads = client.get(
        "/api/data/uploads?asset_type=GENERATION_DATA",
        headers=auth_headers["generator"],
    )
    asset_id = uploads.json()[0]["formal_asset"]["asset_id"]

    unrelated_asset = client.get(
        f"/api/trust-domain/assets/{asset_id}/passport",
        headers=auth_headers["retailer"],
    )
    oversight_asset = client.get(
        f"/api/trust-domain/assets/{asset_id}/passport",
        headers=auth_headers["regulator"],
    )
    assert unrelated_asset.status_code == 404
    assert oversight_asset.status_code == 200

    with SessionLocal() as db:
        db.execute(
            delete(TaskParticipant).where(
                TaskParticipant.task_id == "task-ready-t01",
                TaskParticipant.org_id == "org-generator-t01",
            )
        )
        db.commit()

    unrelated_ttc = client.get(
        "/api/trust-domain/tasks/task-ready-t01/ttc",
        headers=auth_headers["generator"],
    )
    participant_ttc = client.get(
        "/api/trust-domain/tasks/task-ready-t01/ttc",
        headers=auth_headers["retailer"],
    )
    oversight_ttc = client.get(
        "/api/trust-domain/tasks/task-ready-t01/ttc",
        headers=auth_headers["regulator"],
    )
    assert unrelated_ttc.status_code == 404
    assert participant_ttc.status_code == 200
    assert oversight_ttc.status_code == 200
