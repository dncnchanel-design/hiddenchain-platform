from __future__ import annotations

import httpx
import pytest

from app.services.evidence_outbox import AnchorRequest
from app.services.fisco_bcos import FiscoBcosAnchorAdapter, FiscoBcosConfig
from app.services.formal_evidence import selected_anchor_adapter_status
from app.services.privacy_attestation import PrivacyAttestationError, verify_signed_connector_non_export
from app.security import sha256_json


def _request_payload() -> dict[str, object]:
    return {
        "task_id": "TASK-PRIVACY-001",
        "authorization_id": "AUTH-PRIVACY-001",
        "request_item_id": "ITEM-PRIVACY-001",
        "provider_org_id": "org-generator-t01",
        "rule_version": "RULE-1",
        "resource": "generation",
        "function": "average",
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "region": None,
        "hour": None,
        "threshold": None,
        "group_by": None,
        "decimals": 2,
    }


def _signed_connector_result(request_payload: dict[str, object]) -> dict[str, object]:
    request_hash = sha256_json(request_payload)
    return {
        "result": 12.5,
        "unit": "MWh",
        "record_count": 4,
        "raw_records_returned": False,
        "privacy": {
            "raw_records_returned": False,
            "raw_data_exported": False,
            "non_export_attestation": {
                "status": "SIGNED",
                "issuer": "node-org-generator-t01",
                "boundary": "CONNECTOR_LOCAL_DATA",
                "request_hash": request_hash,
                "result_scope": "AGGREGATE_ONLY",
                "raw_data_exported": False,
            },
        },
        "privacy_verification": {
            "mode": "SIGNED_CONNECTOR_NON_EXPORT",
            "request_hash": request_hash,
            "raw_data_exported": False,
            "result_scope": "AGGREGATE_ONLY",
        },
    }


def test_connector_non_export_attestation_is_bound_to_exact_request():
    request_payload = _request_payload()
    proof = verify_signed_connector_non_export(
        _signed_connector_result(request_payload),
        request_payload,
    )

    assert proof["status"] == "VERIFIED"
    assert proof["boundary"] == "CONNECTOR_LOCAL_DATA"
    assert proof["raw_data_exported"] is False

    changed_request = {**request_payload, "region": "东部片区"}
    with pytest.raises(PrivacyAttestationError, match="bound to another request"):
        verify_signed_connector_non_export(
            _signed_connector_result(request_payload),
            changed_request,
        )


def test_connector_non_export_attestation_rejects_raw_fields():
    request_payload = _request_payload()
    result = {**_signed_connector_result(request_payload), "raw_records": [{"value": 1}]}

    with pytest.raises(PrivacyAttestationError, match="raw-data field"):
        verify_signed_connector_non_export(result, request_payload)


def test_fisco_adapter_verifies_external_receipt_before_publishing():
    transaction_hash = "0x" + "ab" * 32
    calls: list[tuple[str, dict[str, object]]] = []

    def post(url: str, *, json: dict[str, object], timeout: float) -> httpx.Response:
        calls.append((url, json))
        return httpx.Response(
            200,
            json={
                "transaction_hash": transaction_hash,
                "receipt": {
                    "transactionHash": transaction_hash,
                    "status": "0x0",
                    "blockNumber": "0x2a",
                },
            },
            request=httpx.Request("POST", url),
        )

    config = FiscoBcosConfig(
        rpc_url="https://fisco.example/rpc",
        relay_url="https://signer.example/anchor",
        group_id="group0",
        node_id="node0",
        contract_address="0x" + "11" * 20,
    )
    adapter = FiscoBcosAnchorAdapter(config, post=post)
    request = AnchorRequest(
        batch_id="BATCH-001",
        merkle_root="11" * 32,
        payload_hash="22" * 32,
        idempotency_key="anchor:BATCH-001",
        event_type="EVIDENCE_ROOT_READY",
        aggregate_type="EVIDENCE_BATCH",
        aggregate_id="BATCH-001",
    )

    receipt = adapter.anchor(request)

    assert receipt.status == "CONFIRMED"
    assert receipt.capability_label == "ADAPTER"
    assert receipt.transaction_hash == transaction_hash
    assert receipt.block_height == 42
    assert receipt.response["receipt_verified"] is True
    assert calls[0][0] == "https://signer.example/anchor"
    assert calls[0][1]["operation"] == "ANCHOR_EVIDENCE_ROOT_V1"


def test_fisco_adapter_polls_json_rpc_when_relay_only_returns_hash():
    transaction_hash = "0x" + "cd" * 32
    calls: list[str] = []

    def post(url: str, *, json: dict[str, object], timeout: float) -> httpx.Response:
        calls.append(url)
        if url.endswith("/anchor"):
            body = {"tx_hash": transaction_hash}
        else:
            body = {
                "jsonrpc": "2.0",
                "id": json["id"],
                "result": {
                    "transactionHash": transaction_hash,
                    "status": 0,
                    "blockNumber": "43",
                },
            }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    config = FiscoBcosConfig(
        rpc_url="https://fisco.example/rpc",
        relay_url="https://signer.example/anchor",
        group_id="group0",
        node_id="node0",
        contract_address="0x" + "22" * 20,
        receipt_poll_attempts=1,
    )
    adapter = FiscoBcosAnchorAdapter(config, post=post)
    request = AnchorRequest(
        batch_id="BATCH-002",
        merkle_root="33" * 32,
        payload_hash="44" * 32,
        idempotency_key="anchor:BATCH-002",
        event_type="EVIDENCE_ROOT_READY",
        aggregate_type="EVIDENCE_BATCH",
        aggregate_id="BATCH-002",
    )

    receipt = adapter.anchor(request)

    assert receipt.block_height == 43
    assert calls == ["https://signer.example/anchor", "https://fisco.example/rpc"]


def test_unconfigured_environment_uses_explicit_local_demo_anchor():
    status = selected_anchor_adapter_status()

    assert status["adapter_code"] == "LOCAL_HASH_ANCHOR_DEMO_V1"
    assert status["capability_label"] == "DEMO"
    assert status["external_publication"] is False
