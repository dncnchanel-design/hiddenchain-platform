from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SettlementTask, utc_now
from ..security import sha256_json
from ..trust_models import BlockchainAnchor, EvidenceBatch, EvidenceBatchItem, EvidenceOutbox, TtcAttempt
from .evidence_outbox import (
    AnchorAdapter,
    EvidenceClass,
    EvidenceOutboxService,
    IdempotencyConflictError,
    LocalHashAnchorAdapter,
    MERKLE_ALGORITHM,
    canonical_leaf_hash,
    classify_evidence_type,
    merkle_root,
    verify_sealed_batch,
)
from .fisco_bcos import FiscoBcosAnchorAdapter


@dataclass(frozen=True)
class EvidenceItemInput:
    evidence_type: str
    biz_type: str
    biz_id: str
    body: Mapping[str, Any]
    metadata: Mapping[str, Any] | None = None


def latest_attempt(db: Session, task_id: str) -> TtcAttempt | None:
    return db.scalar(
        select(TtcAttempt)
        .where(TtcAttempt.task_id == task_id)
        .order_by(TtcAttempt.attempt_no.desc())
    )


def seal_evidence_batch(
    db: Session,
    *,
    task_id: str,
    attempt_id: str | None,
    batch_type: str,
    sealed_by_did: str,
    items: Sequence[EvidenceItemInput],
) -> tuple[EvidenceBatch, EvidenceOutbox]:
    """Seal evidence and enqueue its root in the caller's business transaction."""

    if not items:
        raise ValueError("evidence batch requires at least one item")

    prepared: list[dict[str, Any]] = []
    leaves: list[str] = []
    for item in items:
        evidence_class = classify_evidence_type(item.evidence_type)
        evidence_hash = sha256_json(dict(item.body))
        metadata = dict(item.metadata or {})
        leaf = canonical_leaf_hash(
            evidence_class,
            evidence_type=item.evidence_type,
            biz_type=item.biz_type,
            biz_id=item.biz_id,
            evidence_hash=evidence_hash,
            metadata=metadata,
        )
        leaves.append(leaf)
        prepared.append(
            {
                "evidence_class": evidence_class,
                "evidence_type": item.evidence_type,
                "biz_type": item.biz_type,
                "biz_id": item.biz_id,
                "evidence_hash": evidence_hash,
                "metadata": metadata,
            }
        )
    root = merkle_root(leaves)

    existing = db.scalar(
        select(EvidenceBatch).where(
            EvidenceBatch.task_id == task_id,
            EvidenceBatch.attempt_id == attempt_id,
            EvidenceBatch.batch_type == batch_type,
        )
    )
    if existing is not None:
        verified_root = verify_sealed_batch(db, existing)
        if (
            existing.merkle_algorithm != MERKLE_ALGORITHM
            or existing.leaf_count != len(prepared)
            or verified_root != root
        ):
            raise IdempotencyConflictError(
                "evidence batch key is already bound to a different item fingerprint"
            )
        payload = _batch_outbox_payload(
            batch=existing,
            task_id=task_id,
            attempt_id=attempt_id,
            prepared=prepared,
        )
        outbox = EvidenceOutboxService.enqueue(
            db,
            aggregate_type="EVIDENCE_BATCH",
            aggregate_id=existing.batch_id,
            task_id=task_id,
            batch_id=existing.batch_id,
            event_type="EVIDENCE_ROOT_READY",
            idempotency_key=f"EVIDENCE_BATCH:{task_id}:{attempt_id or 'NONE'}:{batch_type}",
            payload=payload,
        )
        return existing, outbox
    batch = EvidenceBatch(
        task_id=task_id,
        attempt_id=attempt_id,
        batch_type=batch_type,
        merkle_algorithm=MERKLE_ALGORITHM,
        merkle_root=root,
        leaf_count=len(prepared),
        status="SEALED",
        sealed_by_did=sealed_by_did,
        sealed_at=utc_now(),
    )
    db.add(batch)
    db.flush()
    for index, item in enumerate(prepared, start=1):
        db.add(
            EvidenceBatchItem(
                batch_id=batch.batch_id,
                sequence_no=index,
                evidence_class=item["evidence_class"].value,
                evidence_type=item["evidence_type"],
                biz_type=item["biz_type"],
                biz_id=item["biz_id"],
                evidence_hash=item["evidence_hash"],
                metadata_json={
                    **item["metadata"],
                    "leaf_hash": leaves[index - 1],
                    "anchor_requirement": (
                        "MANDATORY"
                        if item["evidence_class"] is EvidenceClass.A
                        else "CONDITIONAL"
                        if item["evidence_class"] is EvidenceClass.B
                        else "EVIDENCE_ROOT_ONLY"
                    ),
                },
                raw_sensitive_data_included=False,
            )
        )
    db.flush()
    verify_sealed_batch(db, batch)
    payload = _batch_outbox_payload(
        batch=batch,
        task_id=task_id,
        attempt_id=attempt_id,
        prepared=prepared,
    )
    outbox = EvidenceOutboxService.enqueue(
        db,
        aggregate_type="EVIDENCE_BATCH",
        aggregate_id=batch.batch_id,
        task_id=task_id,
        batch_id=batch.batch_id,
        event_type="EVIDENCE_ROOT_READY",
        idempotency_key=f"EVIDENCE_BATCH:{task_id}:{attempt_id or 'NONE'}:{batch_type}",
        payload=payload,
    )
    return batch, outbox


def _batch_outbox_payload(
    *,
    batch: EvidenceBatch,
    task_id: str,
    attempt_id: str | None,
    prepared: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "batch_id": batch.batch_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "batch_type": batch.batch_type,
        "merkle_algorithm": batch.merkle_algorithm,
        "merkle_root": batch.merkle_root,
        "leaf_count": len(prepared),
        "class_counts": {
            code: sum(item["evidence_class"].value == code for item in prepared)
            for code in ("A", "B", "C")
        },
        "raw_sensitive_data_included": False,
    }


def selected_anchor_adapter() -> AnchorAdapter:
    """Select the configured external anchor, otherwise the explicit demo adapter."""

    if FiscoBcosAnchorAdapter.is_configured():
        return FiscoBcosAnchorAdapter()
    return LocalHashAnchorAdapter()


def selected_anchor_adapter_status() -> dict[str, Any]:
    adapter = selected_anchor_adapter()
    if isinstance(adapter, FiscoBcosAnchorAdapter):
        return FiscoBcosAnchorAdapter.status(adapter.config)
    return LocalHashAnchorAdapter.status()


def process_local_demo_outbox(db: Session, *, limit: int = 25) -> list[dict[str, Any]]:
    """Run the retry-safe worker once using the configured anchor adapter."""

    anchor_adapter = selected_anchor_adapter()
    adapter_status = selected_anchor_adapter_status()

    results = list(EvidenceOutboxService.process_pending(
        db,
        anchor_adapter,
        limit=limit,
    ))
    for item in results:
        _reconcile_ttc_after_publication(db, item.outbox_id, item.status)
    db.flush()
    # A successful FINAL_SETTLEMENT publication creates one idempotent
    # TTC_ARCHIVE batch. Process that follow-up in the same worker cycle when
    # capacity remains, so callers do not need special-case orchestration.
    remaining = limit - len(results)
    if remaining > 0:
        follow_up = list(
            EvidenceOutboxService.process_pending(
                db,
                anchor_adapter,
                limit=remaining,
            )
        )
        for item in follow_up:
            _reconcile_ttc_after_publication(db, item.outbox_id, item.status)
        results.extend(follow_up)
    for item in results:
        record = db.get(EvidenceOutbox, item.outbox_id)
        if record is not None and record.batch_id:
            batch = db.get(EvidenceBatch, record.batch_id)
            if batch is not None:
                batch.status = (
                    "ANCHORED" if item.status == "PUBLISHED" and adapter_status["capability_label"] != "DEMO"
                    else "ANCHORED_DEMO" if item.status == "PUBLISHED" else item.status
                )
    return [
        {
            "outbox_id": item.outbox_id,
            "status": item.status,
            "attempt_count": item.attempt_count,
            "transaction_hash": item.transaction_hash,
            "error_code": item.error_code,
            "adapter_status": adapter_status,
        }
        for item in results
    ]


def _reconcile_ttc_after_publication(
    db: Session,
    outbox_id: str,
    publication_status: str,
) -> None:
    """Converge evidence publication and TTC state idempotently."""

    outbox = db.get(EvidenceOutbox, outbox_id)
    if outbox is None or not outbox.task_id or not outbox.batch_id:
        return
    batch = db.get(EvidenceBatch, outbox.batch_id)
    task = db.get(SettlementTask, outbox.task_id)
    if batch is None or task is None or batch.batch_type != "FINAL_SETTLEMENT":
        return
    anchor = db.scalar(select(BlockchainAnchor).where(BlockchainAnchor.batch_id == batch.batch_id))
    external_anchor_verified = bool(
        anchor
        and anchor.adapter_code == FiscoBcosAnchorAdapter.adapter_code
        and anchor.status in {"CONFIRMED", "FINALIZED", "PUBLISHED"}
    )
    anchor_message = (
        "FISCO BCOS transaction receipt verified; external publication recorded"
        if external_anchor_verified
        else "DEMO anchor receipt persisted; no external consensus is claimed"
    )

    # Imported lazily to keep the outbox primitive independently testable.
    from .trust_domain import TTCState, TtcStateMachine

    try:
        state = TTCState(task.ttc_state)
    except ValueError:
        return
    actor_did = "did:hiddenchain:agent:audit-risk"
    if publication_status == "PUBLISHED":
        if state in {TTCState.EVIDENCE_STAGE, TTCState.ANCHOR_RETRY}:
            TtcStateMachine.transition(
                db,
                task,
                TTCState.EVIDENCE_ANCHOR,
                actor_did,
                "EVIDENCE_ROOT_PUBLISHED",
                anchor_message,
                trace_id=f"outbox-{outbox.outbox_id}",
            )
            state = TTCState.EVIDENCE_ANCHOR
        if state == TTCState.EVIDENCE_ANCHOR:
            TtcStateMachine.transition(
                db,
                task,
                TTCState.ARCHIVED,
                actor_did,
                "TTC_ARCHIVED",
                (
                    "Business result, audit gate, evidence root and FISCO BCOS receipt are complete"
                    if external_anchor_verified
                    else "Business result, audit gate, evidence root and DEMO anchor receipt are complete"
                ),
                trace_id=f"archive-{outbox.outbox_id}",
            )
            attempt = latest_attempt(db, task.task_id)
            seal_evidence_batch(
                db,
                task_id=task.task_id,
                attempt_id=attempt.attempt_id if attempt else None,
                batch_type="TTC_ARCHIVE",
                sealed_by_did=actor_did,
                items=[
                    EvidenceItemInput(
                        evidence_type="TTC_FINAL_STATE",
                        biz_type="TTC_STATE",
                        biz_id=task.task_id,
                        body={
                            "state": task.ttc_state,
                            "state_version": task.state_version,
                            "archived_at": (
                                task.archived_at.isoformat()
                                if task.archived_at
                                else None
                            ),
                            "prior_batch_id": batch.batch_id,
                            "prior_merkle_root": batch.merkle_root,
                        },
                    )
                ],
            )
    elif publication_status == "RETRY_WAIT":
        if state == TTCState.EVIDENCE_STAGE:
            TtcStateMachine.transition(
                db,
                task,
                TTCState.ANCHOR_RETRY,
                actor_did,
                "ANCHOR_RETRY_SCHEDULED",
                "Outbox retained the evidence root for retry without rolling back the result",
                trace_id=f"retry-{outbox.outbox_id}",
            )
    elif publication_status == "DEAD_LETTER":
        if state in {
            TTCState.EVIDENCE_STAGE,
            TTCState.EVIDENCE_ANCHOR,
            TTCState.ANCHOR_RETRY,
        }:
            TtcStateMachine.transition(
                db,
                task,
                TTCState.FAILED,
                actor_did,
                "ANCHOR_DEAD_LETTER",
                (
                    "Evidence publication exhausted retries or failed integrity "
                    "validation; human disposition is required"
                ),
                trace_id=f"dead-letter-{outbox.outbox_id}",
            )
            task.status = "EXCEPTION"
            task.current_stage = "证据锚定失败待人工处置"
