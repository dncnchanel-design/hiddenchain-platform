from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import importlib
import json
import sqlite3
import sys
import time
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


def _raw_private(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode()


def _raw_public(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


@pytest.fixture
def connector(monkeypatch, tmp_path):
    connector_key = Ed25519PrivateKey.generate()
    platform_key = Ed25519PrivateKey.generate()
    database_path = tmp_path / "coal-ingest.db"
    monkeypatch.setenv("ENERGY_DOMAIN", "coal")
    monkeypatch.setenv("CONNECTOR_ID", "connector-coal-t01")
    monkeypatch.setenv("CONNECTOR_NAME", "煤炭企业连接器")
    monkeypatch.setenv("ORGANIZATION_ID", "org-coal-t01")
    monkeypatch.setenv("CONNECTOR_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CONNECTOR_SIGNING_PRIVATE_KEY", _raw_private(connector_key))
    monkeypatch.setenv("PLATFORM_SIGNING_PUBLIC_KEY", _raw_public(platform_key))
    monkeypatch.setenv("CONNECTOR_INGEST_MAX_BYTES", "2048")
    monkeypatch.setenv("CONNECTOR_SEED_SYNTHETIC_DATA", "false")
    monkeypatch.delenv("ALLOW_DEMO_KEY_REGISTRATION", raising=False)
    monkeypatch.delenv("CONNECTOR_CORS_ORIGINS", raising=False)
    sys.modules.pop("connector.app.main", None)
    module = importlib.import_module("connector.app.main")
    try:
        with TestClient(module.app) as client:
            yield {
                "client": client,
                "module": module,
                "connector_key": connector_key,
                "platform_key": platform_key,
                "database_path": database_path,
            }
    finally:
        sys.modules.pop("connector.app.main", None)


def _claims(*, jti: str, now: int | None = None, **changes) -> dict[str, object]:
    issued_at = int(time.time()) if now is None else now
    claims: dict[str, object] = {
        "iss": "hiddenchain-platform",
        "jti": jti,
        "subject_user_id": "user-coal-t01",
        "organization_id": "org-coal-t01",
        "connector_id": "connector-coal-t01",
        "energy_domain": "coal",
        "resource_id": "inventory",
        "resource_name": "煤炭库存",
        "classification": "L3",
        "schema_version": "connector-csv-v1",
        "file_format": "csv",
        "max_bytes": 2048,
        "purpose": "LOCAL_DATASET_INGEST",
        "issued_at": issued_at,
        "expires_at": issued_at + 300,
    }
    claims.update(changes)
    return claims


def _ticket(key: Ed25519PrivateKey, claims: dict[str, object]) -> dict[str, object]:
    return {
        "claims": claims,
        "signature": base64.b64encode(key.sign(_canonical(claims))).decode(),
        "public_key": _raw_public(key),
        "algorithm": "Ed25519",
    }


def _csv(values=(10, 20, 30), *, secret: bool = False) -> bytes:
    rows = ["record_date,value,hour,region,organization,unit"]
    for index, value in enumerate(values):
        organization = "secret-enterprise-row" if secret else "煤炭企业"
        region = f"片区-{index}"
        rows.append(f"2026-08-01,{value},,{region},{organization},吨")
    return ("\n".join(rows) + "\n").encode()


def _post_ingest(
    client: TestClient,
    key: Ed25519PrivateKey,
    claims: dict[str, object],
    content: bytes | None = None,
):
    return client.post(
        "/ingest",
        data={"ticket": json.dumps(_ticket(key, claims), ensure_ascii=False)},
        files={"file": ("dataset.csv", content or _csv(), "text/csv")},
    )


def _verify_signed_response(key: Ed25519PrivateKey, response: dict[str, object]) -> None:
    payload = {
        name: value
        for name, value in response.items()
        if name not in {"signature", "public_key", "signature_algorithm", "signature_valid"}
    }
    key.public_key().verify(base64.b64decode(str(response["signature"])), _canonical(payload))


def _signed_headers(module, key: Ed25519PrivateKey, payload: dict[str, object], nonce: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    message = {"timestamp": timestamp, "nonce": nonce, "payload": payload}
    return {
        "X-Request-Timestamp": timestamp,
        "X-Request-Nonce": nonce,
        "X-Request-Signature": base64.b64encode(key.sign(module._canonical(message))).decode(),
    }


def test_ingest_happy_path_returns_signed_receipt_without_raw_rows_and_updates_catalog(connector):
    client = connector["client"]
    claims = _claims(jti="ticket-happy-0001")
    response = _post_ingest(client, connector["platform_key"], claims, _csv(secret=True))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ticket_id"] == claims["jti"]
    assert body["connector_id"] == "connector-coal-t01"
    assert body["organization_id"] == "org-coal-t01"
    assert body["energy_domain"] == "coal"
    assert body["resource_id"] == "inventory"
    assert body["resource_name"] == "煤炭库存"
    assert body["version"] == 1
    assert body["schema_version"] == "connector-csv-v1"
    assert len(body["schema_hash"]) == len(body["content_hash"]) == 64
    assert body["record_count"] == 3
    assert body["byte_size"] == len(_csv(secret=True))
    assert body["local_ref"] == "connector://connector-coal-t01/inventory/versions/1"
    assert body["audit_sequence"] == 1
    assert len(body["audit_hash"]) == 64
    assert datetime.fromisoformat(body["issued_at"]).tzinfo is not None
    assert body["signature_algorithm"] == "Ed25519"
    assert body["signature_valid"] is True
    _verify_signed_response(connector["connector_key"], body)
    assert "secret-enterprise-row" not in response.text
    assert "records" not in body and "rows" not in body

    catalog = client.get("/catalog").json()
    assert catalog["connector_id"] == "connector-coal-t01"
    inventory = next(item for item in catalog["resources"] if item["resource_id"] == "inventory")
    assert inventory["latest_version"] == 1
    assert inventory["record_count"] == 3
    assert inventory["upload_capability"]["enabled"] is True

    preflight = client.options(
        "/ingest",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_ingest_ticket_replay_and_concurrent_use_allow_only_one_success(connector):
    client = connector["client"]
    platform_key = connector["platform_key"]
    replay_claims = _claims(jti="ticket-replay-0001")
    assert _post_ingest(client, platform_key, replay_claims).status_code == 201
    assert _post_ingest(client, platform_key, replay_claims).status_code == 409

    concurrent_claims = _claims(jti="ticket-concurrent-0001")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: _post_ingest(client, platform_key, concurrent_claims),
                range(2),
            )
        )
    assert sorted(response.status_code for response in responses) == [201, 409]

    with sqlite3.connect(connector["database_path"]) as database:
        assert database.execute(
            "SELECT COUNT(*) FROM ingest_tickets WHERE ticket_id = ?",
            ("ticket-concurrent-0001",),
        ).fetchone()[0] == 1


def test_platform_key_first_registration_is_demo_only_and_pinned(connector, monkeypatch):
    client = connector["client"]
    platform_key = connector["platform_key"]
    claims = _claims(jti="ticket-demo-key-0001")
    monkeypatch.delenv("PLATFORM_SIGNING_PUBLIC_KEY", raising=False)

    assert _post_ingest(client, platform_key, claims).status_code == 503
    monkeypatch.setenv("ALLOW_DEMO_KEY_REGISTRATION", "true")
    assert _post_ingest(
        client,
        platform_key,
        claims,
        b"record_date,amount\n2026-08-01,1\n",
    ).status_code == 422
    with sqlite3.connect(connector["database_path"]) as database:
        assert database.execute(
            "SELECT COUNT(*) FROM connector_config WHERE config_key = 'platform_public_key'"
        ).fetchone()[0] == 0
    assert _post_ingest(client, platform_key, claims).status_code == 201

    attacker_key = Ed25519PrivateKey.generate()
    attacker_claims = _claims(jti="ticket-demo-key-attacker")
    assert _post_ingest(client, attacker_key, attacker_claims).status_code == 401
    with sqlite3.connect(connector["database_path"]) as database:
        registered = database.execute(
            "SELECT config_value FROM connector_config WHERE config_key = 'platform_public_key'"
        ).fetchone()[0]
    assert registered == _raw_public(platform_key)


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"organization_id": "org-other"}, 403),
        ({"energy_domain": "oil"}, 403),
        ({"connector_id": "connector-other"}, 403),
        ({"resource_id": "not-coal", "resource_name": "其他"}, 422),
        ({"expires_at": 1}, 401),
    ],
)
def test_ingest_rejects_wrong_identity_domain_connector_resource_and_expiry(connector, changes, status):
    claims = _claims(jti=f"ticket-invalid-{status}-{hash(frozenset(changes.items()))}", **changes)
    response = _post_ingest(connector["client"], connector["platform_key"], claims)
    assert response.status_code == status, response.text


def test_ingest_rejects_oversize_bad_schema_nan_and_rolls_back_on_signing_failure(connector, monkeypatch):
    client = connector["client"]
    key = connector["platform_key"]

    oversize = _claims(jti="ticket-size-0001", max_bytes=32)
    assert _post_ingest(client, key, oversize).status_code == 413
    server_oversize = _claims(jti="ticket-server-size-0001", max_bytes=4096)
    assert _post_ingest(client, key, server_oversize, b"x" * 2049).status_code == 413
    bad_schema = _claims(jti="ticket-schema-0001")
    assert _post_ingest(client, key, bad_schema, b"record_date,amount\n2026-08-01,1\n").status_code == 422
    nan_claims = _claims(jti="ticket-nan-0001")
    assert _post_ingest(client, key, nan_claims, b"record_date,value\n2026-08-01,NaN\n").status_code == 422

    rollback_claims = _claims(jti="ticket-rollback-0001")
    original = connector["module"]._signed_response

    def fail_signing(_payload):
        raise RuntimeError("signing unavailable")

    monkeypatch.setattr(connector["module"], "_signed_response", fail_signing)
    with pytest.raises(RuntimeError, match="signing unavailable"):
        _post_ingest(client, key, rollback_claims)
    monkeypatch.setattr(connector["module"], "_signed_response", original)

    with sqlite3.connect(connector["database_path"]) as database:
        for ticket_id in (
            "ticket-size-0001",
            "ticket-server-size-0001",
            "ticket-schema-0001",
            "ticket-nan-0001",
            "ticket-rollback-0001",
        ):
            assert database.execute(
                "SELECT COUNT(*) FROM ingest_tickets WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()[0] == 0
    assert _post_ingest(client, key, rollback_claims).status_code == 201


def test_consumed_ticket_receipt_can_be_looked_up_for_seven_days_after_expiry(connector, monkeypatch):
    client = connector["client"]
    key = connector["platform_key"]
    now = int(time.time())
    claims = _claims(jti="ticket-lookup-0001", now=now, expires_at=now + 2)
    ticket = _ticket(key, claims)
    created = _post_ingest(client, key, claims)
    assert created.status_code == 201

    monkeypatch.setattr(connector["module"], "_now_epoch", lambda: now + 3)
    lookup = client.post("/ingest/receipts/lookup", json=ticket)
    assert lookup.status_code == 200, lookup.text
    assert lookup.json() == created.json()

    unknown_claims = _claims(jti="ticket-never-consumed", now=now, expires_at=now + 2)
    unknown = client.post("/ingest/receipts/lookup", json=_ticket(key, unknown_claims))
    assert unknown.status_code == 404

    monkeypatch.setattr(connector["module"], "_now_epoch", lambda: now + 7 * 24 * 60 * 60 + 3)
    too_late = client.post("/ingest/receipts/lookup", json=ticket)
    assert too_late.status_code == 410


def test_compute_uses_authorized_version_while_dashboard_uses_latest(connector):
    client = connector["client"]
    key = connector["platform_key"]
    version_1 = _post_ingest(
        client, key, _claims(jti="ticket-version-0001"), _csv((10, 20, 30))
    )
    version_2 = _post_ingest(
        client, key, _claims(jti="ticket-version-0002"), _csv((100, 200, 300))
    )
    assert version_1.status_code == version_2.status_code == 201
    version_1_body = version_1.json()

    compute_payload = {
        "task_id": "TASK-INGEST-0001",
        "authorization_id": "AUTH-INGEST-0001",
        "request_item_id": "ITEM-INGEST-0001",
        "provider_org_id": "org-coal-t01",
        "dataset_version": version_1_body["version"],
        "dataset_local_ref": version_1_body["local_ref"],
        "dataset_content_hash": version_1_body["content_hash"],
        "resource": "inventory",
        "function": "average",
        "start_date": "2026-08-01",
        "end_date": "2026-08-01",
        "region": None,
        "hour": None,
        "threshold": None,
        "group_by": None,
        "decimals": 2,
    }
    compute = client.post(
        "/compute",
        json=compute_payload,
        headers=_signed_headers(connector["module"], key, compute_payload, "ingest-compute-nonce-0001"),
    )
    assert compute.status_code == 200, compute.text
    assert compute.json()["result"] == 20
    assert compute.json()["record_count"] == 3
    assert compute.json()["dataset_version"] == 1
    assert compute.json()["dataset_local_ref"] == version_1_body["local_ref"]
    assert compute.json()["dataset_content_hash"] == version_1_body["content_hash"]
    assert compute.json()["audit_sequence"] >= 1
    assert len(compute.json()["previous_audit_hash"]) == 64
    assert len(compute.json()["audit_hash"]) == 64
    assert compute.json()["audit_event"]["action"] == "LOCAL_CONTROLLED_RESULT_ISSUED"
    assert compute.json()["audit_hash"] == hashlib.sha256(
        (
            compute.json()["previous_audit_hash"]
            + _canonical(compute.json()["audit_event"]).decode()
        ).encode()
    ).hexdigest()

    replay = client.post(
        "/compute",
        json=compute_payload,
        headers=_signed_headers(connector["module"], key, compute_payload, "ingest-compute-nonce-0002"),
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == compute.json()

    mismatched_payload = {
        **compute_payload,
        "task_id": "TASK-INGEST-0002",
        "request_item_id": "ITEM-INGEST-0002",
        "dataset_content_hash": "f" * 64,
    }
    mismatched = client.post(
        "/compute",
        json=mismatched_payload,
        headers=_signed_headers(
            connector["module"], key, mismatched_payload, "ingest-compute-nonce-0003"
        ),
    )
    assert mismatched.status_code == 409

    dashboard_payload = {
        "request_id": "dashboard-ingest-0001",
        "provider_org_id": "org-coal-t01",
        "resource": "inventory",
        "aggregation": "average",
        "start_date": "2026-08-01",
        "end_date": "2026-08-01",
        "decimals": 2,
    }
    dashboard = client.post(
        "/dashboard",
        json=dashboard_payload,
        headers=_signed_headers(connector["module"], key, dashboard_payload, "ingest-dashboard-nonce-0001"),
    )
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["latest"]["value"] == 200
    assert dashboard.json()["record_count"] == 3
    assert dashboard.json()["dataset_version"] == 2
    assert dashboard.json()["audit_sequence"] > compute.json()["audit_sequence"]
    assert len(dashboard.json()["previous_audit_hash"]) == 64
    assert len(dashboard.json()["audit_hash"]) == 64
    assert dashboard.json()["audit_event"]["action"] == "DASHBOARD_AGGREGATE_ISSUED"
    assert dashboard.json()["audit_event"]["raw_records_returned"] is False
    assert dashboard.json()["audit_event"]["raw_data_exported"] is False

    with sqlite3.connect(connector["database_path"]) as database:
        database.row_factory = sqlite3.Row
        audit_rows = database.execute(
            "SELECT audit_sequence, previous_hash, audit_hash, event_json "
            "FROM ingest_audit_chain ORDER BY audit_sequence"
        ).fetchall()
    actions = [json.loads(row["event_json"])["action"] for row in audit_rows]
    assert actions == [
        "LOCAL_DATASET_INGESTED",
        "LOCAL_DATASET_INGESTED",
        "PLATFORM_COMPUTE_REQUEST_AUTHENTICATED",
        "PRIVACY_QUERY_BUDGET_CONSUMED",
        "LOCAL_CONTROLLED_RESULT_ISSUED",
        "PLATFORM_COMPUTE_REQUEST_AUTHENTICATED",
        "LOCAL_CONTROLLED_RESULT_REPLAYED",
        "PLATFORM_COMPUTE_REQUEST_AUTHENTICATED",
        "PLATFORM_DASHBOARD_REQUEST_AUTHENTICATED",
        "DASHBOARD_AGGREGATE_ISSUED",
    ]
    assert audit_rows[compute.json()["audit_sequence"] - 1]["audit_hash"] == compute.json()["audit_hash"]
    assert audit_rows[dashboard.json()["audit_sequence"] - 1]["audit_hash"] == dashboard.json()["audit_hash"]
    for index, row in enumerate(audit_rows):
        expected_previous = "0" * 64 if index == 0 else audit_rows[index - 1]["audit_hash"]
        assert row["previous_hash"] == expected_previous
        assert row["audit_hash"] == hashlib.sha256(
            (row["previous_hash"] + row["event_json"]).encode()
        ).hexdigest()


def test_ingest_audit_chain_is_append_only_and_hash_linked(connector):
    client = connector["client"]
    key = connector["platform_key"]
    assert _post_ingest(client, key, _claims(jti="ticket-audit-0001")).status_code == 201
    assert _post_ingest(client, key, _claims(jti="ticket-audit-0002")).status_code == 201

    with sqlite3.connect(connector["database_path"]) as database:
        database.row_factory = sqlite3.Row
        rows = database.execute(
            "SELECT audit_sequence, previous_hash, audit_hash, event_json FROM ingest_audit_chain ORDER BY audit_sequence"
        ).fetchall()
    assert [row["audit_sequence"] for row in rows] == [1, 2]
    assert rows[0]["previous_hash"] == "0" * 64
    assert rows[1]["previous_hash"] == rows[0]["audit_hash"]
    for row in rows:
        expected = hashlib.sha256(
            (row["previous_hash"] + row["event_json"]).encode()
        ).hexdigest()
        assert row["audit_hash"] == expected
    with sqlite3.connect(connector["database_path"]) as database:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            database.execute(
                "UPDATE ingest_audit_chain SET event_json = '{}' WHERE audit_sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            database.execute("DELETE FROM ingest_audit_chain WHERE audit_sequence = 1")
