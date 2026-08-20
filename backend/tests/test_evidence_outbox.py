from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.services.evidence_outbox import (
    AnchorRequirement,
    EvidenceClass,
    EvidenceOutboxService,
    IdempotencyConflictError,
    LocalHashAnchorAdapter,
    MERKLE_ALGORITHM,
    OutboxStatus,
    anchor_requirement,
    canonical_hash,
    canonical_leaf_hash,
    classify_evidence_type,
    merkle_proof,
    merkle_root,
    should_anchor,
    verify_merkle_proof,
)
from app.services.formal_evidence import EvidenceItemInput, seal_evidence_batch
from app.trust_models import (
    BlockchainAnchor,
    EvidenceBatch,
    EvidenceBatchItem,
    EvidenceOutbox,
)


def _leaf(number: int, evidence_class: EvidenceClass = EvidenceClass.C) -> str:
    evidence_type = {
        EvidenceClass.A: "FINAL_RESULT_HASH",
        EvidenceClass.B: "RECOMPUTE",
        EvidenceClass.C: "EXECUTION_LOG",
    }[evidence_class]
    return canonical_leaf_hash(
        evidence_class,
        evidence_type=evidence_type,
        biz_type="TEST_RECORD",
        biz_id=f"record-{number}",
        evidence_hash=canonical_hash({"record": number}),
        metadata={"sequence": number},
    )


def _add_batch(db, root: str) -> EvidenceBatch:
    batch = EvidenceBatch(
        batch_type="TTC_EVIDENCE",
        merkle_algorithm=MERKLE_ALGORITHM,
        merkle_root=root,
        leaf_count=3,
        status="SEALED",
        sealed_by_did="did:hiddenchain:test-auditor",
    )
    db.add(batch)
    db.flush()
    for number in range(1, 4):
        leaf = _leaf(number)
        db.add(
            EvidenceBatchItem(
                batch_id=batch.batch_id,
                sequence_no=number,
                evidence_class=EvidenceClass.C.value,
                evidence_type="EXECUTION_LOG",
                biz_type="TEST_RECORD",
                biz_id=f"record-{number}",
                evidence_hash=canonical_hash({"record": number}),
                metadata_json={
                    "sequence": number,
                    "leaf_hash": leaf,
                    "anchor_requirement": AnchorRequirement.EVIDENCE_ROOT_ONLY.value,
                },
                raw_sensitive_data_included=False,
            )
        )
    db.flush()
    return batch


def test_evidence_class_anchor_policy_matches_architecture_section_9_1():
    assert anchor_requirement(EvidenceClass.A) is AnchorRequirement.MANDATORY
    assert anchor_requirement(EvidenceClass.B) is AnchorRequirement.CONDITIONAL
    assert anchor_requirement(EvidenceClass.C) is AnchorRequirement.EVIDENCE_ROOT_ONLY
    assert should_anchor(EvidenceClass.A)
    assert not should_anchor(EvidenceClass.B, risk_level="LOW")
    assert should_anchor(EvidenceClass.B, risk_level="HIGH")
    assert should_anchor(EvidenceClass.B, regulatory_rule_triggered=True)
    assert not should_anchor(EvidenceClass.C, risk_level="CRITICAL")
    assert classify_evidence_type("FINAL_RESULT_HASH") is EvidenceClass.A
    assert classify_evidence_type("tool_over_permission_attempt") is EvidenceClass.B
    assert classify_evidence_type("EXECUTION_LOG") is EvidenceClass.C
    with pytest.raises(ValueError, match="explicit class"):
        classify_evidence_type("NEW_UNREVIEWED_EVIDENCE")


def test_merkle_root_and_proofs_are_deterministic_and_order_sensitive():
    assert len(MERKLE_ALGORITHM) <= 32
    leaves = [_leaf(1, EvidenceClass.A), _leaf(2), _leaf(3, EvidenceClass.B)]
    root = merkle_root(leaves)

    assert root == merkle_root(list(leaves))
    assert root != merkle_root(list(reversed(leaves)))
    for index, leaf in enumerate(leaves):
        proof = merkle_proof(leaves, index)
        assert verify_merkle_proof(leaf, proof, root)

    assert not verify_merkle_proof(_leaf(99), merkle_proof(leaves, 0), root)
    assert not verify_merkle_proof(leaves[0], merkle_proof(leaves, 0), "0" * 64)


def test_outbox_enqueue_is_idempotent_and_rejects_key_rebinding():
    leaves = [_leaf(1), _leaf(2), _leaf(3)]
    with SessionLocal() as db:
        batch = _add_batch(db, merkle_root(leaves))
        first = EvidenceOutboxService.enqueue(
            db,
            aggregate_type="EVIDENCE_BATCH",
            aggregate_id=batch.batch_id,
            task_id=None,
            batch_id=batch.batch_id,
            event_type="EVIDENCE_BATCH_SEALED",
            idempotency_key=f"anchor:{batch.batch_id}",
            payload={"batch_id": batch.batch_id, "merkle_root": batch.merkle_root},
            now=datetime(2026, 8, 20, 8, 0, 0),
        )
        second = EvidenceOutboxService.enqueue(
            db,
            aggregate_type="EVIDENCE_BATCH",
            aggregate_id=batch.batch_id,
            task_id=None,
            batch_id=batch.batch_id,
            event_type="EVIDENCE_BATCH_SEALED",
            idempotency_key=f"anchor:{batch.batch_id}",
            payload={"merkle_root": batch.merkle_root, "batch_id": batch.batch_id},
            now=datetime(2026, 8, 20, 8, 0, 1),
        )

        assert first.outbox_id == second.outbox_id
        assert db.scalar(select(func.count(EvidenceOutbox.outbox_id))) == 1
        with pytest.raises(IdempotencyConflictError):
            EvidenceOutboxService.enqueue(
                db,
                aggregate_type="EVIDENCE_BATCH",
                aggregate_id=batch.batch_id,
                batch_id=batch.batch_id,
                event_type="EVIDENCE_BATCH_SEALED",
                idempotency_key=f"anchor:{batch.batch_id}",
                payload={"batch_id": batch.batch_id, "merkle_root": "0" * 64},
            )


def test_anchor_failure_is_persisted_for_retry_without_uncommitting_business_batch():
    class FailOnceAnchor(LocalHashAnchorAdapter):
        def __init__(self) -> None:
            self.calls = 0

        def anchor(self, request):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("simulated external dependency outage")
            return super().anchor(request)

    first_attempt_at = datetime(2026, 8, 20, 9, 0, 0)
    adapter = FailOnceAnchor()
    leaves = [_leaf(1), _leaf(2), _leaf(3)]

    # The business batch and outbox entry commit atomically before any adapter call.
    with SessionLocal() as db:
        batch = _add_batch(db, merkle_root(leaves))
        batch_id = batch.batch_id
        EvidenceOutboxService.enqueue(
            db,
            aggregate_type="EVIDENCE_BATCH",
            aggregate_id=batch_id,
            batch_id=batch_id,
            event_type="EVIDENCE_BATCH_SEALED",
            idempotency_key=f"anchor:{batch_id}",
            payload={"batch_id": batch_id, "merkle_root": batch.merkle_root},
            now=first_attempt_at,
        )
        db.commit()

    # Processing happens in another transaction and absorbs the adapter outage.
    with SessionLocal() as db:
        failed = EvidenceOutboxService.process_pending(
            db,
            adapter,
            now=first_attempt_at,
            base_retry_seconds=2,
            max_attempts=3,
        )
        assert len(failed) == 1
        assert failed[0].status == OutboxStatus.RETRY_WAIT.value
        db.commit()

    with SessionLocal() as db:
        assert db.get(EvidenceBatch, batch_id).status == "SEALED"
        outbox = db.scalar(select(EvidenceOutbox))
        assert outbox.status == OutboxStatus.RETRY_WAIT.value
        assert outbox.attempt_count == 1
        assert outbox.next_attempt_at == first_attempt_at + timedelta(seconds=2)
        anchor = db.scalar(select(BlockchainAnchor))
        assert anchor.status == OutboxStatus.RETRY_WAIT.value
        assert anchor.transaction_hash is None

    with SessionLocal() as db:
        succeeded = EvidenceOutboxService.process_pending(
            db,
            adapter,
            now=first_attempt_at + timedelta(seconds=2),
            base_retry_seconds=2,
            max_attempts=3,
        )
        assert len(succeeded) == 1
        assert succeeded[0].status == OutboxStatus.PUBLISHED.value
        assert succeeded[0].transaction_hash
        db.commit()

    # Published events are never delivered twice, even if the worker polls again.
    with SessionLocal() as db:
        assert EvidenceOutboxService.process_pending(
            db,
            adapter,
            now=first_attempt_at + timedelta(hours=1),
        ) == []
        assert db.scalar(select(func.count(BlockchainAnchor.anchor_id))) == 1
        assert db.scalar(select(EvidenceOutbox)).status == OutboxStatus.PUBLISHED.value
    assert adapter.calls == 2
    assert LocalHashAnchorAdapter.status()["capability_label"] == "DEMO"
    assert LocalHashAnchorAdapter.status()["consensus"] is False


def test_payload_tampering_dead_letters_without_calling_anchor():
    class CountingAnchor(LocalHashAnchorAdapter):
        def __init__(self) -> None:
            self.calls = 0

        def anchor(self, request):
            self.calls += 1
            return super().anchor(request)

    process_at = datetime(2026, 8, 20, 10, 0, 0)
    adapter = CountingAnchor()
    with SessionLocal() as db:
        batch = _add_batch(db, merkle_root([_leaf(1), _leaf(2), _leaf(3)]))
        record = EvidenceOutboxService.enqueue(
            db,
            aggregate_type="EVIDENCE_BATCH",
            aggregate_id=batch.batch_id,
            batch_id=batch.batch_id,
            event_type="EVIDENCE_BATCH_SEALED",
            idempotency_key=f"anchor:{batch.batch_id}",
            payload={"batch_id": batch.batch_id, "merkle_root": batch.merkle_root},
            now=process_at,
        )
        record.payload_json = {**record.payload_json, "tampered": True}
        db.flush()

        result = EvidenceOutboxService.process_pending(db, adapter, now=process_at)
        assert result[0].status == OutboxStatus.DEAD_LETTER.value
        assert result[0].error_code == "ANCHOR_EVIDENCEINTEGRITYERROR"
        assert adapter.calls == 0


def test_unsuccessful_anchor_receipt_retries_then_dead_letters_without_publication():
    class FailedReceiptAnchor(LocalHashAnchorAdapter):
        def anchor(self, request):
            return replace(super().anchor(request), status="FAILED")

    first_attempt_at = datetime(2026, 8, 20, 11, 0, 0)
    adapter = FailedReceiptAnchor()
    with SessionLocal() as db:
        batch = _add_batch(db, merkle_root([_leaf(1), _leaf(2), _leaf(3)]))
        EvidenceOutboxService.enqueue(
            db,
            aggregate_type="EVIDENCE_BATCH",
            aggregate_id=batch.batch_id,
            batch_id=batch.batch_id,
            event_type="EVIDENCE_BATCH_SEALED",
            idempotency_key=f"anchor:{batch.batch_id}",
            payload={"batch_id": batch.batch_id, "merkle_root": batch.merkle_root},
            now=first_attempt_at,
        )

        first = EvidenceOutboxService.process_pending(
            db,
            adapter,
            now=first_attempt_at,
            base_retry_seconds=1,
            max_attempts=2,
        )
        assert first[0].status == OutboxStatus.RETRY_WAIT.value
        assert first[0].transaction_hash is None
        assert first[0].error_code == "ANCHOR_ANCHORRECEIPTUNSUCCESSFULERROR"
        outbox = db.scalar(select(EvidenceOutbox))
        anchor = db.scalar(select(BlockchainAnchor))
        assert outbox.published_at is None
        assert anchor.transaction_hash is None
        assert anchor.status == OutboxStatus.RETRY_WAIT.value

        second = EvidenceOutboxService.process_pending(
            db,
            adapter,
            now=first_attempt_at + timedelta(seconds=1),
            base_retry_seconds=1,
            max_attempts=2,
        )
        assert second[0].status == OutboxStatus.DEAD_LETTER.value
        assert db.scalar(select(EvidenceOutbox)).published_at is None
        assert db.scalar(select(BlockchainAnchor)).transaction_hash is None


def test_success_receipt_must_bind_the_persisted_batch_root_and_payload():
    class MismatchedReceiptAnchor(LocalHashAnchorAdapter):
        def anchor(self, request):
            receipt = super().anchor(request)
            return replace(
                receipt,
                response={**dict(receipt.response or {}), "merkle_root": "0" * 64},
            )

    process_at = datetime(2026, 8, 20, 12, 0, 0)
    with SessionLocal() as db:
        batch = _add_batch(db, merkle_root([_leaf(1), _leaf(2), _leaf(3)]))
        EvidenceOutboxService.enqueue(
            db,
            aggregate_type="EVIDENCE_BATCH",
            aggregate_id=batch.batch_id,
            batch_id=batch.batch_id,
            event_type="EVIDENCE_BATCH_SEALED",
            idempotency_key=f"anchor:{batch.batch_id}",
            payload={"batch_id": batch.batch_id, "merkle_root": batch.merkle_root},
            now=process_at,
        )

        result = EvidenceOutboxService.process_pending(
            db, MismatchedReceiptAnchor(), now=process_at
        )
        assert result[0].status == OutboxStatus.DEAD_LETTER.value
        assert result[0].error_code == "ANCHOR_EVIDENCEINTEGRITYERROR"
        assert db.scalar(select(EvidenceOutbox)).published_at is None
        assert db.scalar(select(BlockchainAnchor)).transaction_hash is None


def test_item_tampering_dead_letters_before_calling_anchor():
    class CountingAnchor(LocalHashAnchorAdapter):
        def __init__(self) -> None:
            self.calls = 0

        def anchor(self, request):
            self.calls += 1
            return super().anchor(request)

    process_at = datetime(2026, 8, 20, 13, 0, 0)
    adapter = CountingAnchor()
    with SessionLocal() as db:
        batch = _add_batch(db, merkle_root([_leaf(1), _leaf(2), _leaf(3)]))
        EvidenceOutboxService.enqueue(
            db,
            aggregate_type="EVIDENCE_BATCH",
            aggregate_id=batch.batch_id,
            batch_id=batch.batch_id,
            event_type="EVIDENCE_BATCH_SEALED",
            idempotency_key=f"anchor:{batch.batch_id}",
            payload={"batch_id": batch.batch_id, "merkle_root": batch.merkle_root},
            now=process_at,
        )
        first_item = db.scalar(
            select(EvidenceBatchItem).where(EvidenceBatchItem.batch_id == batch.batch_id)
        )
        first_item.evidence_hash = "0" * 64
        db.flush()

        result = EvidenceOutboxService.process_pending(db, adapter, now=process_at)
        assert result[0].status == OutboxStatus.DEAD_LETTER.value
        assert result[0].error_code == "ANCHOR_EVIDENCEINTEGRITYERROR"
        assert adapter.calls == 0


def test_batch_replay_requires_the_same_item_fingerprint():
    with SessionLocal() as db:
        first, first_outbox = seal_evidence_batch(
            db,
            task_id="task-evidence-replay",
            attempt_id=None,
            batch_type="TTC_EVIDENCE",
            sealed_by_did="did:hiddenchain:test-auditor",
            items=[
                EvidenceItemInput(
                    evidence_type="EXECUTION_LOG",
                    biz_type="TEST_RECORD",
                    biz_id="record-replay",
                    body={"value": 1},
                )
            ],
        )
        replay, replay_outbox = seal_evidence_batch(
            db,
            task_id="task-evidence-replay",
            attempt_id=None,
            batch_type="TTC_EVIDENCE",
            sealed_by_did="did:hiddenchain:test-auditor",
            items=[
                EvidenceItemInput(
                    evidence_type="EXECUTION_LOG",
                    biz_type="TEST_RECORD",
                    biz_id="record-replay",
                    body={"value": 1},
                )
            ],
        )
        assert replay.batch_id == first.batch_id
        assert replay_outbox.outbox_id == first_outbox.outbox_id

        with pytest.raises(IdempotencyConflictError, match="different item fingerprint"):
            seal_evidence_batch(
                db,
                task_id="task-evidence-replay",
                attempt_id=None,
                batch_type="TTC_EVIDENCE",
                sealed_by_did="did:hiddenchain:test-auditor",
                items=[
                    EvidenceItemInput(
                        evidence_type="EXECUTION_LOG",
                        biz_type="TEST_RECORD",
                        biz_id="record-replay",
                        body={"value": 2},
                    )
                ],
            )
