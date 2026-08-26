from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..trust_models import BlockchainAnchor, EvidenceBatch, EvidenceBatchItem, EvidenceOutbox


MERKLE_ALGORITHM = "SHA256_BINARY_DS_V1"

# Receipt states are adapter-facing integration values, not outbox states.  A
# worker may only promote an event to PUBLISHED when an adapter returns one of
# these explicit terminal-success values.  Every other non-empty state remains
# a failed/incomplete publication and is retried under the outbox policy.
SUCCESSFUL_ANCHOR_RECEIPT_STATUSES = frozenset(
    {"ANCHORED", "CONFIRMED", "CONFIRMED_DEMO", "FINALIZED", "PUBLISHED"}
)


class EvidenceClass(str, Enum):
    """Evidence classes defined by section 9.1 of the architecture design.

    ``A`` records a critical trust boundary and must be anchored. ``B`` records
    risk or an abnormal event and is anchored when the applicable risk,
    monetary, approval, or regulatory rule triggers. ``C`` is the complete
    replay/audit trail; it remains off-chain, carries its own hash/signature and
    EvidenceID, and is protected transitively through the anchored EvidenceRoot.
    """

    A = "A"
    B = "B"
    C = "C"

    @property
    def description(self) -> str:
        return {
            EvidenceClass.A: "关键可信边界证据；强制锚定",
            EvidenceClass.B: "风险与异常证据；链下完整保留并按规则条件锚定",
            EvidenceClass.C: "完整过程证据；链下保存并汇入由A类锚点保护的EvidenceRoot",
        }[self]


class AnchorRequirement(str, Enum):
    MANDATORY = "MANDATORY"
    CONDITIONAL = "CONDITIONAL"
    EVIDENCE_ROOT_ONLY = "EVIDENCE_ROOT_ONLY"


_A_EVIDENCE_TYPES = frozenset(
    {
        "IDENTITY_CREDENTIAL",
        "IDENTITY_VERIFICATION",
        "RULE_FREEZE",
        "RULE_FREEZE_SIGNATURE",
        "CONTRACT_AGREEMENT_SUMMARY",
        "FINAL_RESULT_HASH",
        "TTC_FINAL_STATE",
        "MAJOR_AUTHORIZATION_VIOLATION",
        "CRITICAL_HUMAN_APPROVAL",
        "CRITICAL_ANOMALY_DISPOSITION",
    }
)
_B_EVIDENCE_TYPES = frozenset(
    {
        "VERSION_CONFLICT",
        "HASH_MISMATCH",
        "MPC_NODE_FAILURE",
        "TEE_FAILURE",
        "PRIVACY_DOWNGRADE",
        "CONTRACT_RENEGOTIATION",
        "TOOL_OVER_PERMISSION_ATTEMPT",
        "RECOMPUTE",
        "HUMAN_TAKEOVER",
        "REPEATED_FAILURE",
    }
)
_C_EVIDENCE_TYPES = frozenset(
    {
        "REQUEST_PARAMETERS",
        "EXECUTION_LOG",
        "AGENT_INTERMEDIATE_STATE",
        "TOOL_LOG",
        "ENVIRONMENT_LOG",
        "SYSTEM_LOG",
        "INTERMEDIATE_VARIABLE",
        "DEBUG_INFO",
    }
)


def classify_evidence_type(evidence_type: str) -> EvidenceClass:
    """Classify the evidence types explicitly named by the architecture.

    Unknown types fail closed instead of silently becoming C-class and thereby
    evading a mandatory or conditional anchor policy.
    """

    normalized = _require_text(evidence_type, field="evidence_type").upper()
    if normalized in _A_EVIDENCE_TYPES:
        return EvidenceClass.A
    if normalized in _B_EVIDENCE_TYPES:
        return EvidenceClass.B
    if normalized in _C_EVIDENCE_TYPES:
        return EvidenceClass.C
    raise EvidenceIntegrityError("evidence type requires an explicit class assignment")


def anchor_requirement(evidence_class: EvidenceClass | str) -> AnchorRequirement:
    normalized = EvidenceClass(evidence_class)
    return {
        EvidenceClass.A: AnchorRequirement.MANDATORY,
        EvidenceClass.B: AnchorRequirement.CONDITIONAL,
        EvidenceClass.C: AnchorRequirement.EVIDENCE_ROOT_ONLY,
    }[normalized]


def should_anchor(
    evidence_class: EvidenceClass | str,
    *,
    risk_level: str | None = None,
    amount_rule_triggered: bool = False,
    approval_rule_triggered: bool = False,
    regulatory_rule_triggered: bool = False,
) -> bool:
    """Evaluate the class-level anchor policy without inventing business limits.

    Monetary thresholds and approval/regulatory rules remain inputs owned by the
    policy engine. This function only enforces the architecture's A/B/C policy.
    C-class evidence is included in a batch root but is never directly anchored.
    """

    normalized = EvidenceClass(evidence_class)
    if normalized is EvidenceClass.A:
        return True
    if normalized is EvidenceClass.C:
        return False
    return (
        str(risk_level or "").upper() in {"HIGH", "CRITICAL"}
        or amount_rule_triggered
        or approval_rule_triggered
        or regulatory_rule_triggered
    )


class EvidenceIntegrityError(ValueError):
    pass


class IdempotencyConflictError(ValueError):
    pass


class AnchorReceiptUnsuccessfulError(RuntimeError):
    """An adapter returned a well-formed but non-success publication state."""

    pass


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise EvidenceIntegrityError("non-finite numbers are not canonical JSON")
        return 0.0 if value == 0 else value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise EvidenceIntegrityError("non-finite decimals are not canonical JSON")
        normalized = value.normalize()
        return format(normalized, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise EvidenceIntegrityError("naive datetimes are not canonical evidence values")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _normalize_json(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvidenceIntegrityError("canonical evidence object keys must be strings")
            normalized[key] = _normalize_json(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    raise EvidenceIntegrityError(f"unsupported canonical evidence type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_hash(value: str, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise EvidenceIntegrityError(f"{field} must be a 64-character SHA-256 hex digest")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise EvidenceIntegrityError(f"{field} must be SHA-256 hex") from exc
    return value.lower()


def _require_transaction_hash(value: str, *, field: str) -> str:
    """Accept local SHA-256 receipts and FISCO BCOS 0x-prefixed tx hashes."""

    if not isinstance(value, str):
        raise EvidenceIntegrityError(f"{field} must be a transaction hash")
    normalized = value.strip().lower()
    digest = normalized[2:] if normalized.startswith("0x") else normalized
    if len(digest) != 64:
        raise EvidenceIntegrityError(f"{field} must be a 64-byte transaction hash")
    try:
        bytes.fromhex(digest)
    except ValueError as exc:
        raise EvidenceIntegrityError(f"{field} must be hexadecimal") from exc
    return normalized


def _require_text(value: str, *, field: str, max_length: int = 160) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceIntegrityError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise EvidenceIntegrityError(f"{field} exceeds {max_length} characters")
    return normalized


def canonical_leaf_hash(
    evidence_class: EvidenceClass | str,
    *,
    evidence_type: str,
    biz_type: str,
    biz_id: str,
    evidence_hash: str,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    """Hash a leaf with an explicit leaf-domain prefix.

    ``evidence_hash`` is a commitment to the evidence body. Raw evidence is not
    accepted by this API and therefore cannot accidentally enter an anchor.
    """

    payload = {
        "biz_id": _require_text(biz_id, field="biz_id"),
        "biz_type": _require_text(biz_type, field="biz_type"),
        "evidence_class": EvidenceClass(evidence_class).value,
        "evidence_hash": _require_hash(evidence_hash, field="evidence_hash"),
        "evidence_type": _require_text(evidence_type, field="evidence_type"),
        "metadata": dict(metadata or {}),
    }
    return hashlib.sha256(b"\x00" + canonical_json(payload).encode("utf-8")).hexdigest()


def _node_hash(left: str, right: str) -> str:
    left_bytes = bytes.fromhex(_require_hash(left, field="left child hash"))
    right_bytes = bytes.fromhex(_require_hash(right, field="right child hash"))
    return hashlib.sha256(b"\x01" + left_bytes + right_bytes).hexdigest()


def _validated_leaves(leaves: Sequence[str]) -> list[str]:
    if not leaves:
        raise EvidenceIntegrityError("a Merkle tree requires at least one leaf")
    return [_require_hash(item, field=f"leaf[{index}]") for index, item in enumerate(leaves)]


def merkle_root(leaves: Sequence[str]) -> str:
    """Build an order-sensitive binary Merkle root.

    The caller owns the stable evidence sequence (normally
    ``EvidenceBatchItem.sequence_no``). An odd node is duplicated at each level,
    making roots and proofs deterministic across supported databases.
    """

    level = _validated_leaves(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [_node_hash(level[index], level[index + 1]) for index in range(0, len(level), 2)]
    return level[0]


@dataclass(frozen=True, slots=True)
class MerkleProofStep:
    side: str
    sibling_hash: str

    def __post_init__(self) -> None:
        if self.side not in {"LEFT", "RIGHT"}:
            raise EvidenceIntegrityError("Merkle proof side must be LEFT or RIGHT")
        _require_hash(self.sibling_hash, field="sibling_hash")


def merkle_proof(leaves: Sequence[str], leaf_index: int) -> tuple[MerkleProofStep, ...]:
    level = _validated_leaves(leaves)
    if isinstance(leaf_index, bool) or not isinstance(leaf_index, int):
        raise EvidenceIntegrityError("leaf_index must be an integer")
    if leaf_index < 0 or leaf_index >= len(level):
        raise EvidenceIntegrityError("leaf_index is outside the Merkle tree")

    proof: list[MerkleProofStep] = []
    index = leaf_index
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        sibling_index = index - 1 if index % 2 else index + 1
        side = "LEFT" if sibling_index < index else "RIGHT"
        proof.append(MerkleProofStep(side=side, sibling_hash=level[sibling_index]))
        level = [_node_hash(level[offset], level[offset + 1]) for offset in range(0, len(level), 2)]
        index //= 2
    return tuple(proof)


def verify_merkle_proof(
    leaf_hash: str,
    proof: Sequence[MerkleProofStep | Mapping[str, str]],
    expected_root: str,
) -> bool:
    try:
        current = _require_hash(leaf_hash, field="leaf_hash")
        root = _require_hash(expected_root, field="expected_root")
        for raw_step in proof:
            step = (
                raw_step
                if isinstance(raw_step, MerkleProofStep)
                else MerkleProofStep(
                    side=str(raw_step["side"]),
                    sibling_hash=str(raw_step["sibling_hash"]),
                )
            )
            current = (
                _node_hash(step.sibling_hash, current)
                if step.side == "LEFT"
                else _node_hash(current, step.sibling_hash)
            )
        return current == root
    except (EvidenceIntegrityError, KeyError, TypeError):
        return False


def verify_sealed_batch(db: Session, batch: EvidenceBatch) -> str:
    """Recompute a sealed batch from its persisted ordered evidence items.

    The stored batch root is a claim, not proof.  Every publication and TTC
    anchor gate must call this verifier so item tampering, missing rows,
    sequence gaps, metadata changes, and stale roots fail closed.
    """

    _require_text(batch.batch_id, field="evidence batch_id", max_length=96)
    if batch.merkle_algorithm != MERKLE_ALGORITHM:
        raise EvidenceIntegrityError("evidence batch Merkle algorithm mismatch")
    stored_root = _require_hash(batch.merkle_root, field="evidence batch merkle_root")
    if isinstance(batch.leaf_count, bool) or not isinstance(batch.leaf_count, int):
        raise EvidenceIntegrityError("evidence batch leaf_count must be an integer")
    if batch.leaf_count < 1:
        raise EvidenceIntegrityError("evidence batch leaf_count must be positive")

    items = list(
        db.scalars(
            select(EvidenceBatchItem)
            .where(EvidenceBatchItem.batch_id == batch.batch_id)
            .order_by(EvidenceBatchItem.sequence_no, EvidenceBatchItem.item_id)
        )
    )
    if len(items) != batch.leaf_count:
        raise EvidenceIntegrityError("evidence batch leaf_count does not match its items")

    leaves: list[str] = []
    for expected_sequence, item in enumerate(items, start=1):
        if item.sequence_no != expected_sequence:
            raise EvidenceIntegrityError("evidence batch item sequence is not contiguous")
        try:
            evidence_class = EvidenceClass(item.evidence_class)
        except ValueError as exc:
            raise EvidenceIntegrityError("evidence batch item class is invalid") from exc
        if classify_evidence_type(item.evidence_type) is not evidence_class:
            raise EvidenceIntegrityError("evidence batch item class does not match its type")
        if item.raw_sensitive_data_included:
            raise EvidenceIntegrityError("sealed evidence batch contains raw sensitive data")
        if not isinstance(item.metadata_json, Mapping):
            raise EvidenceIntegrityError("evidence batch item metadata must be an object")
        metadata = dict(item.metadata_json)
        stored_leaf = _require_hash(
            metadata.pop("leaf_hash", None), field="evidence batch item leaf_hash"
        )
        stored_requirement = metadata.pop("anchor_requirement", None)
        if stored_requirement != anchor_requirement(evidence_class).value:
            raise EvidenceIntegrityError("evidence batch item anchor requirement mismatch")
        leaf = canonical_leaf_hash(
            evidence_class,
            evidence_type=item.evidence_type,
            biz_type=item.biz_type,
            biz_id=item.biz_id,
            evidence_hash=item.evidence_hash,
            metadata=metadata,
        )
        if leaf != stored_leaf:
            raise EvidenceIntegrityError("evidence batch item leaf hash mismatch")
        leaves.append(leaf)

    computed_root = merkle_root(leaves)
    if computed_root != stored_root:
        raise EvidenceIntegrityError("evidence batch Merkle root does not match its items")
    return computed_root


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    RETRY_WAIT = "RETRY_WAIT"
    PUBLISHED = "PUBLISHED"
    DEAD_LETTER = "DEAD_LETTER"


@dataclass(frozen=True, slots=True)
class AnchorRequest:
    batch_id: str
    merkle_root: str
    payload_hash: str
    idempotency_key: str
    event_type: str
    aggregate_type: str
    aggregate_id: str


@dataclass(frozen=True, slots=True)
class AnchorReceipt:
    adapter_code: str
    capability_label: str
    network_code: str
    transaction_hash: str
    status: str
    anchored_at: datetime
    block_height: int | None = None
    response: Mapping[str, Any] | None = None


class AnchorAdapter(Protocol):
    adapter_code: str
    capability_label: str
    network_code: str

    def anchor(self, request: AnchorRequest) -> AnchorReceipt: ...


class LocalHashAnchorAdapter:
    """Deterministic local commitment adapter; this is not a blockchain.

    The adapter provides a repeatable integration path and idempotent receipt
    for local testing. It has no consensus, independent node, finality, or
    external timestamp and therefore remains truthfully labelled ``DEMO``.
    """

    adapter_code = "LOCAL_HASH_ANCHOR_DEMO_V1"
    capability_label = "DEMO"
    network_code = "LOCAL_DETERMINISTIC_HASH_ONLY"

    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "adapter_code": cls.adapter_code,
            "capability_label": cls.capability_label,
            "network_code": cls.network_code,
            "consensus": False,
            "external_finality": False,
            "production_blockchain": False,
            "external_publication": False,
            "limitations": [
                "single-process deterministic hash receipt",
                "no independent timestamp or consensus",
                "not proof of publication to an external network",
            ],
        }

    def anchor(self, request: AnchorRequest) -> AnchorReceipt:
        _require_text(request.batch_id, field="batch_id")
        root = _require_hash(request.merkle_root, field="merkle_root")
        payload_hash = _require_hash(request.payload_hash, field="payload_hash")
        transaction_hash = canonical_hash(
            {
                "adapter_code": self.adapter_code,
                "aggregate_id": request.aggregate_id,
                "aggregate_type": request.aggregate_type,
                "batch_id": request.batch_id,
                "event_type": request.event_type,
                "idempotency_key": request.idempotency_key,
                "merkle_root": root,
                "payload_hash": payload_hash,
            }
        )
        return AnchorReceipt(
            adapter_code=self.adapter_code,
            capability_label=self.capability_label,
            network_code=self.network_code,
            transaction_hash=transaction_hash,
            block_height=None,
            status="CONFIRMED_DEMO",
            anchored_at=datetime.now(UTC),
            response={
                "batch_id": request.batch_id,
                "commitment_only": True,
                "consensus": False,
                "external_publication": False,
                "merkle_root": root,
                "payload_hash": payload_hash,
            },
        )


@dataclass(frozen=True, slots=True)
class OutboxProcessingResult:
    outbox_id: str
    status: str
    attempt_count: int
    transaction_hash: str | None = None
    error_code: str | None = None


def _utc_naive(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is not None:
        current = current.astimezone(UTC).replace(tzinfo=None)
    return current


class EvidenceOutboxService:
    """Transactional enqueue and retry-safe evidence publication service.

    ``enqueue`` only adds to the caller's current SQLAlchemy transaction; it
    never commits. The caller must persist the business result and returned
    outbox row in the same transaction. ``process_pending`` is then invoked by
    a separate worker/unit of work. Adapter failures are converted to retry or
    dead-letter state and are deliberately not raised, so a committed business
    result is never rolled back because anchoring is unavailable.
    """

    @staticmethod
    def enqueue(
        db: Session,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
        task_id: str | None = None,
        batch_id: str | None = None,
        now: datetime | None = None,
    ) -> EvidenceOutbox:
        aggregate_type = _require_text(aggregate_type, field="aggregate_type", max_length=64)
        aggregate_id = _require_text(aggregate_id, field="aggregate_id", max_length=96)
        event_type = _require_text(event_type, field="event_type", max_length=96)
        idempotency_key = _require_text(
            idempotency_key, field="idempotency_key", max_length=160
        )
        normalized_payload = _normalize_json(dict(payload))
        if not isinstance(normalized_payload, dict):
            raise EvidenceIntegrityError("outbox payload must be a JSON object")
        payload_hash = canonical_hash(normalized_payload)

        existing = db.scalar(
            select(EvidenceOutbox).where(EvidenceOutbox.idempotency_key == idempotency_key)
        )
        if existing is not None:
            matches = (
                existing.aggregate_type == aggregate_type
                and existing.aggregate_id == aggregate_id
                and existing.event_type == event_type
                and existing.task_id == task_id
                and existing.batch_id == batch_id
                and existing.payload_hash == payload_hash
            )
            if not matches:
                raise IdempotencyConflictError(
                    "idempotency key is already bound to a different evidence event"
                )
            return existing

        queued_at = _utc_naive(now)
        record = EvidenceOutbox(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            task_id=task_id,
            batch_id=batch_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            payload_json=normalized_payload,
            payload_hash=payload_hash,
            status=OutboxStatus.PENDING.value,
            attempt_count=0,
            next_attempt_at=queued_at,
            created_at=queued_at,
            updated_at=queued_at,
        )
        db.add(record)
        db.flush()
        return record

    @classmethod
    def process_pending(
        cls,
        db: Session,
        anchor_adapter: AnchorAdapter,
        *,
        limit: int = 25,
        max_attempts: int = 5,
        base_retry_seconds: int = 5,
        stale_after_seconds: int = 300,
        now: datetime | None = None,
    ) -> list[OutboxProcessingResult]:
        if isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if isinstance(max_attempts, bool) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if isinstance(base_retry_seconds, bool) or base_retry_seconds < 1:
            raise ValueError("base_retry_seconds must be a positive integer")
        if isinstance(stale_after_seconds, bool) or stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be a positive integer")

        process_at = _utc_naive(now)
        stale_before = process_at - timedelta(seconds=stale_after_seconds)
        due = and_(
            EvidenceOutbox.status.in_(
                [OutboxStatus.PENDING.value, OutboxStatus.RETRY_WAIT.value]
            ),
            EvidenceOutbox.next_attempt_at <= process_at,
        )
        recoverable_stale_claim = and_(
            EvidenceOutbox.status == OutboxStatus.PROCESSING.value,
            EvidenceOutbox.locked_at.is_not(None),
            EvidenceOutbox.locked_at <= stale_before,
        )
        statement = (
            select(EvidenceOutbox)
            .where(or_(due, recoverable_stale_claim))
            .order_by(
                EvidenceOutbox.next_attempt_at,
                EvidenceOutbox.created_at,
                EvidenceOutbox.outbox_id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        records = list(db.scalars(statement))
        results: list[OutboxProcessingResult] = []
        for record in records:
            results.append(
                cls._process_one(
                    db,
                    record,
                    anchor_adapter,
                    max_attempts=max_attempts,
                    base_retry_seconds=base_retry_seconds,
                    process_at=process_at,
                )
            )
        db.flush()
        return results

    @classmethod
    def _process_one(
        cls,
        db: Session,
        record: EvidenceOutbox,
        anchor_adapter: AnchorAdapter,
        *,
        max_attempts: int,
        base_retry_seconds: int,
        process_at: datetime,
    ) -> OutboxProcessingResult:
        record.status = OutboxStatus.PROCESSING.value
        record.locked_at = process_at
        record.attempt_count = int(record.attempt_count or 0) + 1
        record.updated_at = process_at
        db.flush()

        anchor: BlockchainAnchor | None = None
        try:
            request = cls._build_anchor_request(db, record)
            if record.batch_id:
                anchor = cls._get_or_create_anchor(
                    db,
                    record,
                    request,
                    anchor_adapter,
                    process_at=process_at,
                )
                anchor.status = OutboxStatus.PROCESSING.value
                anchor.attempt_count = record.attempt_count
                anchor.last_error = None
                anchor.updated_at = process_at
                db.flush()

            receipt = anchor_adapter.anchor(request)
            receipt_status = _require_text(
                receipt.status, field="anchor receipt status", max_length=24
            ).upper()
            if receipt_status not in SUCCESSFUL_ANCHOR_RECEIPT_STATUSES:
                raise AnchorReceiptUnsuccessfulError(
                    f"anchor receipt is not successful: {receipt_status}"
                )

            receipt_adapter_code = _require_text(
                receipt.adapter_code, field="anchor receipt adapter code", max_length=96
            )
            receipt_network_code = _require_text(
                receipt.network_code, field="anchor receipt network code", max_length=96
            )
            receipt_capability_label = _require_text(
                receipt.capability_label,
                field="anchor receipt capability label",
                max_length=24,
            )
            if receipt_adapter_code != anchor_adapter.adapter_code:
                raise EvidenceIntegrityError("anchor receipt adapter code mismatch")
            if receipt_network_code != anchor_adapter.network_code:
                raise EvidenceIntegrityError("anchor receipt network code mismatch")
            if receipt_capability_label != anchor_adapter.capability_label:
                raise EvidenceIntegrityError("anchor receipt capability label mismatch")
            if receipt_capability_label not in {"REAL", "LOCAL_REAL", "ADAPTER", "DEMO"}:
                raise EvidenceIntegrityError("anchor receipt has an unsupported capability label")
            transaction_hash = _require_transaction_hash(
                receipt.transaction_hash, field="anchor transaction_hash"
            )
            if (
                not isinstance(receipt.anchored_at, datetime)
                or receipt.anchored_at.tzinfo is None
                or receipt.anchored_at.utcoffset() is None
            ):
                raise EvidenceIntegrityError(
                    "anchor receipt anchored_at must be a timezone-aware datetime"
                )
            if receipt.block_height is not None and (
                isinstance(receipt.block_height, bool)
                or not isinstance(receipt.block_height, int)
                or receipt.block_height < 0
            ):
                raise EvidenceIntegrityError("anchor receipt block_height must be non-negative")
            if not isinstance(receipt.response, Mapping):
                raise EvidenceIntegrityError("anchor receipt response must be an object")
            response_json = _normalize_json(dict(receipt.response))
            response_batch_id = _require_text(
                response_json.get("batch_id"),
                field="anchor receipt batch_id",
                max_length=96,
            )
            if response_batch_id != request.batch_id:
                raise EvidenceIntegrityError("anchor receipt batch_id mismatch")
            response_root = _require_hash(
                response_json.get("merkle_root"), field="anchor receipt merkle_root"
            )
            if response_root != request.merkle_root:
                raise EvidenceIntegrityError("anchor receipt Merkle root mismatch")
            response_payload_hash = _require_hash(
                response_json.get("payload_hash"), field="anchor receipt payload_hash"
            )
            if response_payload_hash != request.payload_hash:
                raise EvidenceIntegrityError("anchor receipt payload hash mismatch")
            record.status = OutboxStatus.PUBLISHED.value
            record.published_at = _utc_naive(receipt.anchored_at)
            record.locked_at = None
            record.last_error = None
            record.updated_at = process_at
            if anchor is not None:
                anchor.adapter_code = receipt_adapter_code
                anchor.capability_label = receipt_capability_label
                anchor.network_code = receipt_network_code
                anchor.transaction_hash = transaction_hash
                anchor.block_height = receipt.block_height
                anchor.status = receipt_status
                anchor.response_json = response_json
                anchor.last_error = None
                anchor.anchored_at = _utc_naive(receipt.anchored_at)
                anchor.updated_at = process_at
            return OutboxProcessingResult(
                outbox_id=record.outbox_id,
                status=record.status,
                attempt_count=record.attempt_count,
                transaction_hash=transaction_hash,
            )
        except Exception as exc:  # The outbox boundary intentionally absorbs adapter failure.
            permanent = isinstance(exc, (EvidenceIntegrityError, IdempotencyConflictError))
            exhausted = record.attempt_count >= max_attempts
            record.status = (
                OutboxStatus.DEAD_LETTER.value
                if permanent or exhausted
                else OutboxStatus.RETRY_WAIT.value
            )
            if record.status == OutboxStatus.RETRY_WAIT.value:
                delay = min(base_retry_seconds * (2 ** (record.attempt_count - 1)), 3600)
                record.next_attempt_at = process_at + timedelta(seconds=delay)
            record.locked_at = None
            error_code = f"ANCHOR_{type(exc).__name__.upper()}"
            record.last_error = error_code
            record.updated_at = process_at
            if anchor is not None:
                anchor.status = record.status
                anchor.attempt_count = record.attempt_count
                anchor.last_error = error_code
                anchor.updated_at = process_at
            return OutboxProcessingResult(
                outbox_id=record.outbox_id,
                status=record.status,
                attempt_count=record.attempt_count,
                error_code=error_code,
            )

    @staticmethod
    def _build_anchor_request(db: Session, record: EvidenceOutbox) -> AnchorRequest:
        actual_payload_hash = canonical_hash(record.payload_json)
        if actual_payload_hash != record.payload_hash:
            raise EvidenceIntegrityError("outbox payload hash mismatch")

        batch: EvidenceBatch | None = None
        if record.batch_id:
            batch = db.get(EvidenceBatch, record.batch_id)
            if batch is None:
                raise EvidenceIntegrityError("outbox references a missing evidence batch")
            verified_root = verify_sealed_batch(db, batch)
            if (
                record.aggregate_type == "EVIDENCE_BATCH"
                and record.aggregate_id != batch.batch_id
            ):
                raise EvidenceIntegrityError("outbox aggregate_id does not match evidence batch")
            payload_batch_id = _require_text(
                record.payload_json.get("batch_id"),
                field="outbox payload batch_id",
                max_length=96,
            )
            if payload_batch_id != batch.batch_id:
                raise EvidenceIntegrityError("outbox payload batch_id mismatch")
            payload_root = _require_hash(
                record.payload_json.get("merkle_root"),
                field="outbox payload merkle_root",
            )
            if payload_root != verified_root:
                raise EvidenceIntegrityError("outbox payload Merkle root mismatch")
            merkle_root_value = verified_root
            batch_id = batch.batch_id
        else:
            merkle_root_value = record.payload_json.get("merkle_root")
            batch_id = str(record.payload_json.get("batch_id") or record.aggregate_id)
        return AnchorRequest(
            batch_id=_require_text(batch_id, field="batch_id"),
            merkle_root=_require_hash(str(merkle_root_value or ""), field="merkle_root"),
            payload_hash=_require_hash(record.payload_hash, field="payload_hash"),
            idempotency_key=record.idempotency_key,
            event_type=record.event_type,
            aggregate_type=record.aggregate_type,
            aggregate_id=record.aggregate_id,
        )

    @staticmethod
    def _get_or_create_anchor(
        db: Session,
        record: EvidenceOutbox,
        request: AnchorRequest,
        anchor_adapter: AnchorAdapter,
        *,
        process_at: datetime,
    ) -> BlockchainAnchor:
        anchor = db.scalar(
            select(BlockchainAnchor).where(BlockchainAnchor.batch_id == record.batch_id)
        )
        if anchor is not None:
            if anchor.anchor_payload_hash != request.payload_hash:
                raise EvidenceIntegrityError("batch anchor is bound to a different payload hash")
            return anchor
        anchor = BlockchainAnchor(
            batch_id=record.batch_id,
            adapter_code=anchor_adapter.adapter_code,
            capability_label=anchor_adapter.capability_label,
            network_code=anchor_adapter.network_code,
            anchor_payload_hash=request.payload_hash,
            status=OutboxStatus.PENDING.value,
            attempt_count=0,
            response_json={},
            created_at=process_at,
            updated_at=process_at,
        )
        db.add(anchor)
        db.flush()
        return anchor
