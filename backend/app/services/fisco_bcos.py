from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

import httpx

from ..config import settings
from .evidence_outbox import AnchorReceipt, AnchorRequest


@dataclass(frozen=True, slots=True)
class FiscoBcosConfig:
    rpc_url: str
    relay_url: str
    group_id: str
    node_id: str
    contract_address: str
    timeout_seconds: float = 10.0
    receipt_poll_attempts: int = 10
    receipt_poll_interval_seconds: float = 0.5

    @property
    def configured(self) -> bool:
        return all(
            value.strip()
            for value in (
                self.rpc_url,
                self.relay_url,
                self.group_id,
                self.node_id,
                self.contract_address,
            )
        )

    @classmethod
    def from_settings(cls) -> "FiscoBcosConfig":
        return cls(
            rpc_url=settings.fisco_bcos_rpc_url,
            relay_url=settings.fisco_bcos_relay_url,
            group_id=settings.fisco_bcos_group_id,
            node_id=settings.fisco_bcos_node_id,
            contract_address=settings.fisco_bcos_contract_address,
            timeout_seconds=max(settings.fisco_bcos_timeout_seconds, 1.0),
            receipt_poll_attempts=max(settings.fisco_bcos_receipt_poll_attempts, 1),
            receipt_poll_interval_seconds=max(settings.fisco_bcos_receipt_poll_interval_seconds, 0.0),
        )


class FiscoBcosAnchorAdapter:
    """Anchor evidence roots through an external signer and verify FISCO receipts.

    FISCO BCOS JSON-RPC requires a signed transaction payload.  The platform
    therefore calls a separately operated relay/signer, then verifies the
    resulting transaction receipt through JSON-RPC before marking the outbox
    event published.  No chain private key is accepted by this service.
    """

    adapter_code = "FISCO_BCOS_EVIDENCE_ANCHOR_V1"
    capability_label = "ADAPTER"
    network_code = "FISCO_BCOS_3_JSON_RPC"

    def __init__(
        self,
        config: FiscoBcosConfig | None = None,
        *,
        post: Callable[..., httpx.Response] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or FiscoBcosConfig.from_settings()
        self._post = post or httpx.post
        self._sleep = sleep

    @classmethod
    def is_configured(cls) -> bool:
        return FiscoBcosConfig.from_settings().configured

    @classmethod
    def status(cls, config: FiscoBcosConfig | None = None) -> dict[str, Any]:
        selected = config or FiscoBcosConfig.from_settings()
        return {
            "adapter_code": cls.adapter_code,
            "capability_label": cls.capability_label,
            "network_code": cls.network_code,
            "configured": selected.configured,
            "submission": "EXTERNAL_SIGNER_RELAY",
            "receipt_verification": "DIRECT_JSON_RPC_GET_TRANSACTION_RECEIPT",
            "private_key_in_platform_process": False,
            "ready_to_anchor": selected.configured,
            "external_publication": False,
            "external_finality": False,
            "limitations": (
                []
                if selected.configured
                else [
                    "FISCO BCOS RPC, signer relay and contract are not configured",
                    "local DEMO anchor is selected until an external receipt is verified",
                ]
            ),
        }

    def anchor(self, request: AnchorRequest) -> AnchorReceipt:
        if not self.config.configured:
            raise RuntimeError("FISCO BCOS anchor is not configured")
        relay_payload = {
            "operation": "ANCHOR_EVIDENCE_ROOT_V1",
            "batch_id": request.batch_id,
            "merkle_root": request.merkle_root,
            "payload_hash": request.payload_hash,
            "idempotency_key": request.idempotency_key,
            "event_type": request.event_type,
            "aggregate_type": request.aggregate_type,
            "aggregate_id": request.aggregate_id,
            "group_id": self.config.group_id,
            "node_id": self.config.node_id,
            "contract_address": self.config.contract_address,
        }
        relay = self._post(
            self.config.relay_url,
            json=relay_payload,
            timeout=self.config.timeout_seconds,
        )
        relay.raise_for_status()
        relay_body = self._object(relay, "FISCO signer relay returned a non-object response")
        transaction_hash = self._transaction_hash(relay_body)
        receipt = self._receipt_from_response(relay_body)
        if not self._receipt_is_committed(receipt):
            receipt = self._poll_receipt(transaction_hash)
        block_height = self._verify_receipt(receipt, transaction_hash)
        return AnchorReceipt(
            adapter_code=self.adapter_code,
            capability_label=self.capability_label,
            network_code=self.network_code,
            transaction_hash=transaction_hash,
            status="CONFIRMED",
            anchored_at=datetime.now(UTC),
            block_height=block_height,
            response={
                "batch_id": request.batch_id,
                "merkle_root": request.merkle_root,
                "payload_hash": request.payload_hash,
                "transaction_hash": transaction_hash,
                "external_publication": True,
                "receipt_verified": True,
                "network_code": self.network_code,
                "group_id": self.config.group_id,
                "node_id": self.config.node_id,
                "contract_address": self.config.contract_address,
                "fisco_receipt": dict(receipt),
            },
        )

    def _poll_receipt(self, transaction_hash: str) -> Mapping[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.config.receipt_poll_attempts):
            try:
                response = self._post(
                    self.config.rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": attempt + 1,
                        "method": "getTransactionReceipt",
                        "params": [self.config.group_id, self.config.node_id, transaction_hash, True],
                    },
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                body = self._object(response, "FISCO JSON-RPC returned a non-object response")
                if body.get("error"):
                    raise RuntimeError(f"FISCO JSON-RPC error: {body['error']}")
                receipt = body.get("result")
                if isinstance(receipt, Mapping):
                    return receipt
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                last_error = exc
            if attempt + 1 < self.config.receipt_poll_attempts:
                self._sleep(self.config.receipt_poll_interval_seconds)
        if last_error is not None:
            raise RuntimeError("FISCO transaction receipt verification failed") from last_error
        raise RuntimeError("FISCO transaction receipt is not available")

    @staticmethod
    def _object(response: httpx.Response, message: str) -> dict[str, Any]:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError(message)
        return body

    @classmethod
    def _transaction_hash(cls, body: Mapping[str, Any]) -> str:
        candidates: list[Any] = [
            body.get("transaction_hash"),
            body.get("transactionHash"),
            body.get("tx_hash"),
            body.get("txHash"),
        ]
        for nested_key in ("result", "receipt"):
            nested = body.get(nested_key)
            if isinstance(nested, Mapping):
                candidates.extend(
                    [
                        nested.get("transaction_hash"),
                        nested.get("transactionHash"),
                        nested.get("tx_hash"),
                        nested.get("txHash"),
                    ]
                )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                value = candidate.strip().lower()
                body_value = value[2:] if value.startswith("0x") else value
                if len(body_value) == 64:
                    try:
                        bytes.fromhex(body_value)
                    except ValueError:
                        continue
                    return value
        raise ValueError("FISCO signer relay did not return a valid transaction hash")

    @staticmethod
    def _receipt_from_response(body: Mapping[str, Any]) -> Mapping[str, Any] | None:
        direct = body.get("receipt")
        if isinstance(direct, Mapping):
            return direct
        result = body.get("result")
        return result if isinstance(result, Mapping) else None

    @staticmethod
    def _receipt_is_committed(receipt: Mapping[str, Any] | None) -> bool:
        if not isinstance(receipt, Mapping):
            return False
        return receipt.get("blockNumber") is not None or receipt.get("block_number") is not None

    @classmethod
    def _verify_receipt(cls, receipt: Mapping[str, Any], transaction_hash: str) -> int:
        receipt_hash = receipt.get("transactionHash") or receipt.get("transaction_hash")
        if receipt_hash is not None and str(receipt_hash).lower() != transaction_hash.lower():
            raise ValueError("FISCO receipt transaction hash does not match the submitted hash")
        status = receipt.get("status")
        normalized_status = status.lower() if isinstance(status, str) else status
        if normalized_status not in {0, "0", "0x0"}:
            raise RuntimeError(f"FISCO transaction failed with status {status!r}")
        raw_height = receipt.get("blockNumber") or receipt.get("block_number")
        if raw_height is None or isinstance(raw_height, bool):
            raise ValueError("FISCO receipt has no committed block number")
        try:
            height = int(raw_height, 0) if isinstance(raw_height, str) else int(raw_height)
        except (TypeError, ValueError) as exc:
            raise ValueError("FISCO receipt block number is invalid") from exc
        if height < 0:
            raise ValueError("FISCO receipt block number must be non-negative")
        return height
