from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, select

from app.database import SessionLocal
from app.migrations import (
    MIGRATION_METADATA,
    MIGRATIONS,
    SCHEMA_MIGRATIONS,
    apply_migrations,
    migration_status,
)
from app.models import PrivacyComputeJob, SettlementRule, SettlementTask, TaskParticipant
from app.trust_models import DataAsset, DataAssetVersion


def _asset_reference() -> dict[str, str]:
    with SessionLocal() as db:
        asset = db.scalar(
            select(DataAsset)
            .where(DataAsset.owner_org_id == "org-generator-t01")
            .order_by(DataAsset.created_at)
        )
        assert asset is not None
        version = db.scalar(
            select(DataAssetVersion)
            .where(DataAssetVersion.asset_id == asset.asset_id)
            .order_by(DataAssetVersion.version_no.desc())
        )
        assert version is not None
        return {"asset_id": asset.asset_id, "asset_version_id": version.version_id}


def _create_queued_job(*, task_id: str, participants: bool = True) -> str:
    with SessionLocal() as db:
        rule = db.scalar(select(SettlementRule).order_by(SettlementRule.created_at))
        assert rule is not None
        task = SettlementTask(
            task_id=task_id,
            capsule_id=f"{task_id}-capsule",
            task_name="Trusted Space golden control task",
            trade_batch_no=f"GOLDEN-{task_id}",
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
        if participants:
            db.add_all(
                [
                    TaskParticipant(task_id=task_id, org_id="org-generator-t01", role_in_task="GENERATOR"),
                    TaskParticipant(task_id=task_id, org_id="org-retailer-t01", role_in_task="RETAILER"),
                ]
            )
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
        return job.job_id


def test_migration_upgrade_from_003_to_latest_is_idempotent(tmp_path):
    isolated = create_engine(
        f"sqlite:///{(tmp_path / 'from-003.db').as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    try:
        # Build an honest database whose ledger stops after 20260821_003.
        # The normal runner must then apply only 004 and 005.
        with isolated.begin() as connection:
            MIGRATION_METADATA.create_all(bind=connection)
            for migration in MIGRATIONS[:7]:
                migration.apply(connection)
                connection.execute(
                    SCHEMA_MIGRATIONS.insert().values(
                        version=migration.version,
                        description=migration.description,
                        checksum=migration.checksum,
                        applied_at=datetime.now(UTC).replace(tzinfo=None),
                    )
                )

        assert migration_status(isolated)["current"] == "20260821_003"
        assert apply_migrations(isolated) == ["20260821_004", "20260821_005", "20260823_001", "20260824_001"]
        assert apply_migrations(isolated) == []
        status = migration_status(isolated)
        assert status["status"] == "READY"
        assert status["current"] == "20260824_001"
        columns = {item["name"] for item in inspect(isolated).get_columns("privacy_compute_jobs")}
        assert {"state_version", "action_code", "action_idempotency_key", "action_response_json", "cancelled_at"} <= columns
        index_names = {item["name"] for item in inspect(isolated).get_indexes("privacy_compute_jobs")}
        assert "ix_privacy_compute_jobs_action_idempotency" in index_names
    finally:
        isolated.dispose()


def test_trusted_space_golden_path_multi_role(client, auth_headers):
    schema = client.get("/api/openapi.json").json()
    paths = schema["paths"]
    operation_ids = [
        operation.get("operationId")
        for path_item in paths.values()
        for operation in path_item.values()
        if isinstance(operation, dict) and operation.get("operationId")
    ]
    assert len(operation_ids) == len(set(operation_ids))
    for path in (
        "/api/auth/logout",
        "/api/trust-space/context",
        "/api/trust-space/catalog",
        "/api/trust-space/assets/{asset_id}",
        "/api/data/access-requests",
        "/api/trust-space/contracts",
        "/api/trust-space/ttc",
        "/api/trust-space/computations",
        "/api/trust-space/results",
        "/api/trust-space/audit/export",
        "/api/trust-space/notifications",
        "/api/trust-space/assistant/sessions",
    ):
        assert path in paths

    frontend_client = Path(__file__).resolve().parents[2] / "frontend/src/features/trusted-energy/trusted-space-api.ts"
    frontend_source = frontend_client.read_text(encoding="utf-8")
    frontend_to_openapi = {
        "/trust-space/context": "/api/trust-space/context",
        "/trust-space/catalog": "/api/trust-space/catalog",
        "/data/access-requests": "/api/data/access-requests",
        "/trust-space/contracts": "/api/trust-space/contracts",
        "/trust-space/ttc": "/api/trust-space/ttc",
        "/trust-space/computations": "/api/trust-space/computations",
        "/trust-space/results": "/api/trust-space/results",
        "/trust-space/notifications": "/api/trust-space/notifications",
        "/trust-space/assistant": "/api/trust-space/assistant/sessions",
    }
    for path, openapi_path in frontend_to_openapi.items():
        assert path in frontend_source
        assert openapi_path in paths
    shell_source = (Path(__file__).resolve().parents[2] / "frontend/src/features/trusted-energy/layout/TrustedSpaceShell.tsx").read_text(encoding="utf-8")
    assert "trusted-navigation-sheet" in shell_source
    assert "trusted-user-menu-panel" in shell_source
    assert "/auth/logout" in (Path(__file__).resolve().parents[2] / "frontend/src/auth.tsx").read_text(encoding="utf-8")

    contexts = {
        role: client.get("/api/trust-space/context", headers=auth_headers[role])
        for role in ("generator", "retailer", "exchange", "admin")
    }
    assert all(contexts[role].status_code == 200 for role in ("generator", "retailer", "exchange"))
    assert contexts["admin"].status_code == 403
    assert contexts["generator"].json()["actor"]["role_code"] == "GENERATOR"
    assert contexts["retailer"].json()["current_subject"]["org_id"] == "org-retailer-t01"
    assert contexts["exchange"].json()["actor"]["role_code"] == "EXCHANGE"

    catalog = client.get(
        "/api/trust-space/catalog?page=1&page_size=100",
        headers=auth_headers["exchange"],
    )
    assert catalog.status_code == 200, catalog.text
    generator_item = next(
        item for item in catalog.json()["items"] if item["provider"]["org_id"] == "org-generator-t01"
    )
    heat_catalog = client.get(
        "/api/trust-space/catalog?page=1&page_size=100",
        headers=auth_headers["heat"],
    )
    assert heat_catalog.status_code == 200, heat_catalog.text
    assert not any(
        item["provider"]["org_id"] == "org-generator-t01"
        for item in heat_catalog.json()["items"]
    )
    regulator_catalog = client.get(
        "/api/trust-space/catalog?page=1&page_size=100",
        headers=auth_headers["regulator"],
    )
    assert regulator_catalog.status_code == 200, regulator_catalog.text
    assert any(
        item["provider"]["org_id"] == "org-generator-t01"
        for item in regulator_catalog.json()["items"]
    )
    reference = {
        "asset_id": generator_item["asset_id"],
        "asset_version_id": generator_item["latest_version"]["version_id"],
    }
    detail = client.get(
        f"/api/trust-space/assets/{reference['asset_id']}",
        headers=auth_headers["exchange"],
    )
    assert detail.status_code == 200
    assert detail.json()["asset"]["asset_id"] == reference["asset_id"]
    retailer_asset = next(
        item for item in catalog.json()["items"] if item["provider"]["org_id"] == "org-retailer-t01"
    )
    cross_scope = client.get(
        f"/api/trust-space/assets/{retailer_asset['asset_id']}",
        headers=auth_headers["generator"],
    )
    assert cross_scope.status_code == 200
    assert cross_scope.json()["asset"]["provider"]["org_id"] == "org-retailer-t01"

    request_payload = {
        **reference,
        "purpose": "GOLDEN_PATH_AUDIT",
        "usage_mode": "MPC_AGGREGATE",
        "requested_scope": {"fields": ["energy_mwh", "period"], "max_uses": 1},
        "requested_fields": ["energy_mwh", "period"],
        "duration_days": 30,
        "terms": {"output_mode": "AGGREGATE_ONLY", "raw_data_export": False},
    }
    create_headers = {**auth_headers["exchange"], "Idempotency-Key": "golden-usage-001"}
    created = client.post("/api/data/access-requests", headers=create_headers, json=request_payload)
    assert created.status_code == 201, created.text
    request = created.json()
    replay = client.post("/api/data/access-requests", headers=create_headers, json=request_payload)
    assert replay.status_code == 200
    assert replay.json()["request_id"] == request["request_id"]
    assert replay.json()["idempotent_replay"] is True
    conflict = client.post(
        "/api/data/access-requests",
        headers=create_headers,
        json={**request_payload, "purpose": "GOLDEN_PATH_CONFLICT"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_REBINDING"

    inbox = client.get(
        "/api/data/access-requests?inbox=true&page=1&page_size=20",
        headers=auth_headers["generator"],
    )
    assert inbox.status_code == 200
    assert any(item["request_id"] == request["request_id"] for item in inbox.json()["items"])
    outsider_request = client.get(
        f"/api/data/access-requests/{request['request_id']}",
        headers=auth_headers["retailer"],
    )
    assert outsider_request.status_code == 403

    reviewed = client.post(
        f"/api/data/access-requests/{request['request_id']}/review",
        headers={**auth_headers["generator"], "If-Match": '"1"'},
        json={"note": "提供方核对资产护照"},
    )
    assert reviewed.status_code == 200
    approved = client.post(
        f"/api/data/access-requests/{request['request_id']}/approve",
        headers={**auth_headers["generator"], "If-Match": f'"{reviewed.json()["state_version"]}"'},
        json={"reason": "批准受控聚合使用"},
    )
    assert approved.status_code == 200, approved.text
    approved_body = approved.json()
    assert approved_body["status"] == "APPROVED"
    assert approved_body["contract_id"] and approved_body["agreement_id"]
    assert approved_body["capability"]["external_anchor"] == "BLOCKED"
    wrong_approver = client.post(
        f"/api/data/access-requests/{request['request_id']}/approve",
        headers={**auth_headers["retailer"], "If-Match": f'"{approved_body["state_version"]}"'},
        json={"reason": "越权审批"},
    )
    assert wrong_approver.status_code == 403
    illegal_request_transition = client.post(
        f"/api/data/access-requests/{request['request_id']}/reject",
        headers={**auth_headers["generator"], "If-Match": f'"{approved_body["state_version"]}"'},
        json={"reason": "已批准后不得拒绝"},
    )
    assert illegal_request_transition.status_code == 409

    contract = client.get(
        f"/api/trust-space/contracts/{approved_body['contract_id']}",
        headers=auth_headers["exchange"],
    )
    assert contract.status_code == 200
    assert contract.json()["agreement"]["agreement_id"] == approved_body["agreement_id"]
    contract_outsider = client.get(
        f"/api/trust-space/contracts/{approved_body['contract_id']}",
        headers=auth_headers["retailer"],
    )
    assert contract_outsider.status_code == 404

    control_job_id = _create_queued_job(task_id="golden-control-task")
    control_detail = client.get(
        f"/api/trust-space/computations/{control_job_id}",
        headers=auth_headers["exchange"],
    )
    assert control_detail.status_code == 200
    assert "cancel" in control_detail.json()["allowed_actions"]
    stale_cancel = client.post(
        f"/api/trust-space/computations/{control_job_id}/cancel",
        headers={
            **auth_headers["exchange"],
            "If-Match": '"99"',
            "Idempotency-Key": "golden-cancel-stale",
        },
        json={"reason": "过期版本"},
    )
    assert stale_cancel.status_code == 412
    cancelled = client.post(
        f"/api/trust-space/computations/{control_job_id}/cancel",
        headers={
            **auth_headers["exchange"],
            "If-Match": '"1"',
            "Idempotency-Key": "golden-cancel-001",
        },
        json={"reason": "黄金路径验证取消"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["job"]["status"] == "CANCELLED"
    cancel_replay = client.post(
        f"/api/trust-space/computations/{control_job_id}/cancel",
        headers={
            **auth_headers["exchange"],
            "If-Match": '"1"',
            "Idempotency-Key": "golden-cancel-001",
        },
        json={"reason": "黄金路径验证取消"},
    )
    assert cancel_replay.status_code == 200
    assert cancel_replay.json()["idempotent_replay"] is True
    retry_blocked = client.post(
        f"/api/trust-space/computations/{control_job_id}/retry",
        headers={
            **auth_headers["exchange"],
            "If-Match": '"2"',
            "Idempotency-Key": "golden-retry-001",
        },
        json={"reason": "验证无重试执行器"},
    )
    assert retry_blocked.status_code == 409
    assert retry_blocked.json()["detail"]["code"] == "COMPUTE_RETRY_BLOCKED"
    invalid_ttc = client.post(
        "/api/trust-space/ttc/golden-control-task/transitions",
        headers={**auth_headers["exchange"], "If-Match": '"2"'},
        json={"to_state": "DATA_AUTHORIZED", "trigger": "INVALID", "reason": "禁止越级"},
    )
    assert invalid_ttc.status_code == 403

    blocked_job_id = _create_queued_job(task_id="golden-blocked-task", participants=False)
    blocked_detail = client.get(
        f"/api/trust-space/computations/{blocked_job_id}",
        headers=auth_headers["exchange"],
    )
    assert blocked_detail.status_code == 200
    blocked_execution = blocked_detail.json()["external_execution"]
    assert blocked_execution["capability_state"] == "BLOCKED"
    assert blocked_execution["tee_attestation"] == "NOT_CONFIGURED"
    assert blocked_execution["cross_domain_participants"] == []

    task = client.get("/api/settlement/tasks/task-ready-t01", headers=auth_headers["exchange"])
    assert task.status_code == 200
    settled = client.post(
        "/api/settlement/tasks/task-ready-t01/run",
        headers={**auth_headers["exchange"], "If-Match": task.headers["etag"]},
        json={"compute_mode": "LOCAL_CONTROLLED", "algorithm_code": "CONTROLLED_SETTLEMENT_V1"},
    )
    assert settled.status_code == 200, settled.text
    settled_body = settled.json()
    assert settled_body["compute_job"]["status"] == "SUCCESS"
    assert settled_body["compute_job"]["privacy_guarantees"]["api_raw_records_returned"] is False

    results = client.get("/api/trust-space/results?page=1&page_size=100", headers=auth_headers["exchange"])
    assert results.status_code == 200
    assert results.json()["total"] >= len(settled_body["results"])
    result_by_org = {item["org_id"]: item for item in settled_body["results"] if item.get("org_id")}
    generator_result_id = result_by_org["org-generator-t01"]["result_id"]
    result_detail = client.get(
        f"/api/trust-space/results/{generator_result_id}",
        headers=auth_headers["exchange"],
    )
    assert result_detail.status_code == 200
    assert result_detail.json()["result"]["result_hash"]
    confirm_task = client.get("/api/settlement/tasks/task-ready-t01", headers=auth_headers["generator"])
    confirmed = client.post(
        f"/api/trust-space/results/{generator_result_id}/confirm",
        headers={**auth_headers["generator"], "If-Match": confirm_task.headers["etag"]},
        json={"decision": "APPROVE", "opinion": "黄金路径确认"},
    )
    assert confirmed.status_code == 200, confirmed.text
    exchange_confirm = client.post(
        f"/api/trust-space/results/{generator_result_id}/confirm",
        headers={**auth_headers["exchange"], "If-Match": confirm_task.headers["etag"]},
        json={"decision": "APPROVE", "opinion": "越权确认"},
    )
    assert exchange_confirm.status_code == 403

    evidence_id = settled_body["evidence"][0]["evidence_id"]
    verified = client.get(
        f"/api/trust-space/evidence/{evidence_id}/verify",
        headers=auth_headers["regulator"],
    )
    assert verified.status_code == 200
    assert verified.json()["matched"] is True
    assert verified.json()["capability_state"] in {"DEMO", "LOCAL_REAL"}

    audit = client.get("/api/trust-space/audit?page=1&page_size=20", headers=auth_headers["regulator"])
    assert audit.status_code == 200
    assert audit.json()["total"] > 0
    export_json = client.get("/api/trust-space/audit/export?format=json", headers=auth_headers["regulator"])
    export_csv = client.get("/api/trust-space/audit/export?format=csv", headers=auth_headers["regulator"])
    assert export_json.status_code == 200
    assert export_json.headers["content-type"].startswith("application/json")
    assert export_csv.status_code == 200
    assert export_csv.headers["content-type"].startswith("text/csv")
    assert client.get("/api/trust-space/audit", headers=auth_headers["generator"]).status_code == 403

    generator_notifications = client.get(
        "/api/trust-space/notifications?type=DATA_USAGE_REQUEST&page=1&page_size=20",
        headers=auth_headers["generator"],
    )
    assert generator_notifications.status_code == 200
    notice = next(
        item for item in generator_notifications.json()["items"] if item["entity_id"] == request["request_id"]
    )
    marked = client.post(
        f"/api/trust-space/notifications/{notice['notification_id']}/read",
        headers=auth_headers["generator"],
    )
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    unread = client.get(
        "/api/trust-space/notifications?unread_only=true&page=1&page_size=100",
        headers=auth_headers["generator"],
    )
    assert unread.status_code == 200
    assert all(item["notification_id"] != notice["notification_id"] for item in unread.json()["items"])

    assistant_session = client.post(
        "/api/trust-space/assistant/sessions",
        headers={**auth_headers["exchange"], "Idempotency-Key": "golden-assistant-session"},
        json={"page_path": "/trusted-space/assets", "entity_type": "data_asset", "entity_id": reference["asset_id"]},
    )
    assert assistant_session.status_code == 201
    session_id = assistant_session.json()["session_id"]
    read_plan = client.post(
        f"/api/trust-space/assistant/sessions/{session_id}/messages",
        headers={**auth_headers["exchange"], "If-Match": '"1"', "Idempotency-Key": "golden-assistant-read"},
        json={"content": "检查资产完整性"},
    )
    assert read_plan.status_code == 201
    plan = read_plan.json()["plan"]
    assert plan["capability_state"] == "LOCAL_REAL_DETERMINISTIC"
    executed = client.post(
        f"/api/trust-space/assistant/sessions/{session_id}/plans/{plan['plan_id']}/execute",
        headers={**auth_headers["exchange"], "If-Match": '"1"'},
        json={},
    )
    assert executed.status_code == 200
    assert executed.json()["plan"]["status"] == "SUCCEEDED"
    before_requests = client.get("/api/data/access-requests", headers=auth_headers["exchange"]).json()["total"]
    write_session = client.post(
        "/api/trust-space/assistant/sessions",
        headers={**auth_headers["exchange"], "Idempotency-Key": "golden-assistant-write-session"},
        json={"page_path": "/trusted-space/catalog", "entity_type": "data_asset", "entity_id": reference["asset_id"]},
    ).json()
    write_plan_response = client.post(
        f"/api/trust-space/assistant/sessions/{write_session['session_id']}/messages",
        headers={**auth_headers["exchange"], "If-Match": '"1"', "Idempotency-Key": "golden-assistant-write"},
        json={"content": "提交申请"},
    )
    assert write_plan_response.status_code == 201
    write_plan = write_plan_response.json()["plan"]
    assert write_plan["status"] == "PENDING_REVIEW"
    write_execution = client.post(
        f"/api/trust-space/assistant/sessions/{write_session['session_id']}/plans/{write_plan['plan_id']}/execute",
        headers={**auth_headers["exchange"], "If-Match": '"1"'},
        json={},
    )
    assert write_execution.status_code == 200
    assert write_execution.json()["plan"]["status"] == "PENDING_REVIEW"
    assert write_execution.json()["plan"]["steps"][0]["output"]["business_mutation"] is False
    after_requests = client.get("/api/data/access-requests", headers=auth_headers["exchange"]).json()["total"]
    assert after_requests == before_requests
