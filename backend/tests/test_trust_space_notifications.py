from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.database import SessionLocal, engine
from app.migrations import migration_status
from app.models import (
    DataContract,
    DataSpaceAgreement,
    UserNotification,
    utc_now,
)
from app.security import sha256_json
from app.trust_models import DataAsset, DataAssetVersion


def _asset_payload() -> dict[str, str]:
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


def _request_payload() -> dict:
    return {
        **_asset_payload(),
        "purpose": "NOTIFICATION_REGRESSION",
        "usage_mode": "MPC_AGGREGATE",
        "requested_scope": {"fields": ["energy_mwh"], "max_uses": 1},
        "requested_fields": ["energy_mwh"],
        "duration_days": 30,
        "terms": {"output_mode": "AGGREGATE_ONLY", "raw_data_export": False},
    }


def _etag(body: dict) -> dict[str, str]:
    return {"If-Match": f'"{body["state_version"]}"'}


def test_notifications_help_and_migration_contract(client, auth_headers):
    assert migration_status(engine)["current"] == "20260823_001"
    schema = client.get("/api/openapi.json").json()["paths"]
    for path in (
        "/api/trust-space/help",
        "/api/trust-space/notifications",
        "/api/trust-space/notifications/{notification_id}/read",
        "/api/trust-space/notifications/read-all",
        "/api/trust-space/ttc",
    ):
        assert path in schema

    help_body = client.get(
        "/api/trust-space/help?view=identity",
        headers=auth_headers["generator"],
    )
    assert help_body.status_code == 200
    payload = help_body.json()
    assert payload["version"] == "20260821.004"
    assert payload["view"] == "identity"
    assert payload["entries"]
    assert all("<" not in item["body"] for item in payload["entries"])

    invalid = client.get(
        "/api/trust-space/help?view=../../etc/passwd",
        headers=auth_headers["generator"],
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "HELP_VIEW_NOT_SUPPORTED"


def test_access_request_notifications_are_scoped_deduplicated_and_readable(
    client, auth_headers
):
    before = client.get(
        "/api/trust-space/notifications?type=DATA_USAGE_REQUEST",
        headers=auth_headers["generator"],
    ).json()["total"]
    created = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["exchange"], "Idempotency-Key": "notify-request-001"},
        json=_request_payload(),
    )
    assert created.status_code == 201, created.text
    request = created.json()

    inbox = client.get(
        "/api/trust-space/notifications?type=DATA_USAGE_REQUEST",
        headers=auth_headers["generator"],
    )
    assert inbox.status_code == 200
    inbox_body = inbox.json()
    assert inbox_body["total"] == before + 1
    notification = next(
        item for item in inbox_body["items"] if item["entity_id"] == request["request_id"]
    )
    assert notification["read_at"] is None
    assert inbox_body["unread_count"] >= 1

    replay = client.post(
        "/api/data/access-requests",
        headers={**auth_headers["exchange"], "Idempotency-Key": "notify-request-001"},
        json=_request_payload(),
    )
    assert replay.status_code == 200
    assert client.get(
        "/api/trust-space/notifications?type=DATA_USAGE_REQUEST",
        headers=auth_headers["generator"],
    ).json()["total"] == before + 1

    marked = client.post(
        f"/api/trust-space/notifications/{notification['notification_id']}/read",
        headers=auth_headers["generator"],
    )
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    all_read = client.post(
        "/api/trust-space/notifications/read-all",
        headers=auth_headers["generator"],
    )
    assert all_read.status_code == 200
    assert all_read.json()["unread_count"] == 0
    assert client.get(
        "/api/trust-space/notifications?unread_only=true",
        headers=auth_headers["generator"],
    ).json()["total"] == 0

    outsider = client.get(
        "/api/trust-space/notifications?type=DATA_USAGE_REQUEST",
        headers=auth_headers["retailer"],
    )
    assert outsider.status_code == 200
    assert all(item["entity_id"] != request["request_id"] for item in outsider.json()["items"])

    approved = client.post(
        f"/api/data/access-requests/{request['request_id']}/approve",
        headers={**auth_headers["generator"], **_etag(request)},
        json={"reason": "通知专项测试批准"},
    )
    assert approved.status_code == 200, approved.text
    decision_notifications = client.get(
        "/api/trust-space/notifications?type=DATA_USAGE_DECISION",
        headers=auth_headers["exchange"],
    ).json()
    assert any(
        item["entity_id"] == request["request_id"] for item in decision_notifications["items"]
    )


def test_contract_ttc_result_and_audit_events_publish_to_scoped_users(
    client, auth_headers
):
    contract_id = "notification-contract-001"
    now = utc_now()
    with SessionLocal() as db:
        contract = DataContract(
            contract_id=contract_id,
            task_id=None,
            provider_org_id="org-generator-t01",
            consumer_type="org-exchange-t01",
            purpose="NOTIFICATION_CONTRACT",
            data_refs_json=["upload-generation-t01"],
            policy_json={"output_mode": "AGGREGATE_ONLY"},
            policy_hash=sha256_json({"output_mode": "AGGREGATE_ONLY"}),
            status="ACTIVE",
            valid_from=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=30),
        )
        db.add(contract)
        db.add(
            DataSpaceAgreement(
                agreement_id="notification-agreement-001",
                contract_id=contract_id,
                task_id=None,
                provider_org_id="org-generator-t01",
                consumer_org_id="org-exchange-t01",
                provider_did="did:hiddenchain:org:org-generator-t01",
                consumer_did="did:hiddenchain:org:org-exchange-t01",
                protocol_version="HCDS-1.0",
                state="OFFERED",
                requested_purpose="NOTIFICATION_CONTRACT",
                algorithm_code="CONTROLLED_DATA_USAGE_V1",
                data_product_ids_json=["upload-generation-t01"],
                offered_policy_hash=contract.policy_hash,
                negotiated_policy_hash=contract.policy_hash,
                valid_from=now - timedelta(minutes=1),
                expires_at=now + timedelta(days=30),
                max_uses=1,
                use_count=0,
                decision_json={},
                last_receipt_json={},
                trace_id="trace-notification-contract",
            )
        )
        db.commit()

    event = client.post(
        f"/api/trust-space/contracts/{contract_id}/events",
        headers={
            **auth_headers["generator"],
            "If-Match": '"0"',
            "Idempotency-Key": "notification-contract-event-001",
        },
        json={"event_type": "COMMENT", "message": "通知事件测试"},
    )
    assert event.status_code == 201, event.text
    exchange_contract_notifications = client.get(
        "/api/trust-space/notifications?type=CONTRACT_NEGOTIATION",
        headers=auth_headers["exchange"],
    ).json()
    assert any(item["entity_id"] == contract_id for item in exchange_contract_notifications["items"])

    ttc = client.get(
        "/api/trust-space/ttc/task-ready-t01",
        headers=auth_headers["exchange"],
    )
    assert ttc.status_code == 200, ttc.text
    assert "transition:CANCELLED" in ttc.json()["allowed_actions"]
    generator_ttc = client.get(
        "/api/trust-space/ttc/task-ready-t01",
        headers=auth_headers["generator"],
    )
    assert generator_ttc.status_code == 200
    assert generator_ttc.json()["allowed_actions"] == ["view"]

    task_list = client.get(
        "/api/trust-space/ttc?page=1&page_size=1&status=READY",
        headers=auth_headers["exchange"],
    )
    assert task_list.status_code == 200
    assert task_list.json()["total"] == 1
    assert len(task_list.json()["items"]) == 1
    assert task_list.json()["items"][0]["task_id"] == "task-ready-t01"

    cancelled = client.post(
        "/api/trust-space/ttc/task-ready-t01/transitions",
        headers={**auth_headers["exchange"], "If-Match": '"1"'},
        json={"to_state": "CANCELLED", "trigger": "NOTIFICATION_TEST", "reason": "通知专项测试"},
    )
    assert cancelled.status_code == 200, cancelled.text
    generator_ttc_notifications = client.get(
        "/api/trust-space/notifications?type=TTC_STATE",
        headers=auth_headers["generator"],
    ).json()
    assert any(item["entity_id"] == "task-ready-t01" for item in generator_ttc_notifications["items"])

    result_notifications = client.get(
        "/api/trust-space/notifications?type=RESULT_CONFIRMATION",
        headers=auth_headers["generator"],
    )
    assert result_notifications.status_code == 200
    assert result_notifications.json()["total"] >= 1

    audit_notifications = client.get(
        "/api/trust-space/notifications?type=AUDIT_REPORT",
        headers=auth_headers["regulator"],
    )
    assert audit_notifications.status_code == 200
    assert audit_notifications.json()["total"] >= 1


def test_quick_action_codes_and_ttc_scope_are_stable(client, auth_headers):
    generator = client.get(
        "/api/trust-space/workbench", headers=auth_headers["generator"]
    )
    assert generator.status_code == 200
    generator_items = generator.json()["quick_action_items"]
    assert {item["code"] for item in generator_items} == {
        "VIEW_OWN_ASSETS",
        "REVIEW_INBOUND_AUTHORIZATIONS",
        "CONFIRM_OWN_RESULT",
    }
    assert all(set(("code", "label", "path", "allowed", "disabled_reason", "entity_id")).issubset(item) for item in generator_items)
    assert next(item for item in generator_items if item["code"] == "VIEW_OWN_ASSETS")["path"] == "/trusted-space/catalog"

    exchange = client.get(
        "/api/trust-space/workbench", headers=auth_headers["exchange"]
    ).json()
    exchange_actions = {item["code"]: item for item in exchange["quick_action_items"]}
    assert exchange_actions["CREATE_SETTLEMENT"]["path"] == "/settlements/new"
    assert exchange_actions["VIEW_PENDING_AUDIT"]["path"].startswith("/trusted-space/audit")

    admin = client.get(
        "/api/trust-space/workbench", headers=auth_headers["admin"]
    )
    assert admin.status_code == 403
