from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import TaskParticipant, User
from ..services.formal_evidence import process_local_demo_outbox, selected_anchor_adapter_status
from ..services.mpc import AdditiveSecretSharingMPC
from ..trust_models import BlockchainAnchor, EvidenceBatch, EvidenceBatchItem, EvidenceOutbox


router = APIRouter(tags=["formal-evidence"])


@router.get("/evidence/batches")
def list_evidence_batches(
    task_id: str | None = None,
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(EvidenceBatch).order_by(EvidenceBatch.sealed_at.desc())
    if user.role_code in {"GENERATOR", "RETAILER"}:
        scoped_task_ids = list(
            db.scalars(
                select(TaskParticipant.task_id).where(
                    TaskParticipant.org_id == user.org_id
                )
            ).all()
        )
        query = query.where(EvidenceBatch.task_id.in_(scoped_task_ids or ["__none__"]))
    if task_id:
        query = query.where(EvidenceBatch.task_id == task_id)
    batches = db.scalars(query).all()
    result = []
    for batch in batches:
        items = db.scalars(
            select(EvidenceBatchItem)
            .where(EvidenceBatchItem.batch_id == batch.batch_id)
            .order_by(EvidenceBatchItem.sequence_no)
        ).all()
        anchor = db.scalar(
            select(BlockchainAnchor).where(BlockchainAnchor.batch_id == batch.batch_id)
        )
        result.append(
            {
                "batch_id": batch.batch_id,
                "task_id": batch.task_id,
                "attempt_id": batch.attempt_id,
                "batch_type": batch.batch_type,
                "merkle_algorithm": batch.merkle_algorithm,
                "merkle_root": batch.merkle_root,
                "leaf_count": batch.leaf_count,
                "status": batch.status,
                "sealed_at": batch.sealed_at,
                "items": [
                    {
                        "sequence_no": item.sequence_no,
                        "evidence_class": item.evidence_class,
                        "evidence_type": item.evidence_type,
                        "biz_type": item.biz_type,
                        "biz_id": item.biz_id,
                        "evidence_hash": item.evidence_hash,
                        "metadata": item.metadata_json,
                        "raw_sensitive_data_included": item.raw_sensitive_data_included,
                    }
                    for item in items
                ],
                "anchor": (
                    {
                        "adapter_code": anchor.adapter_code,
                        "capability_label": anchor.capability_label,
                        "network_code": anchor.network_code,
                        "transaction_hash": anchor.transaction_hash,
                        "block_height": anchor.block_height,
                        "status": anchor.status,
                        "consensus_verified": False,
                        "external_receipt_verified": (
                            anchor.capability_label != "DEMO"
                            and anchor.status in {"CONFIRMED", "FINALIZED", "PUBLISHED"}
                        ),
                        "external_publication": bool(
                            (anchor.response_json or {}).get("external_publication")
                        ),
                    }
                    if anchor
                    else None
                ),
            }
        )
    return result


@router.get("/evidence/outbox")
def list_evidence_outbox(
    task_id: str | None = None,
    user: User = Depends(require_roles("REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(EvidenceOutbox).order_by(EvidenceOutbox.created_at.desc())
    if task_id:
        query = query.where(EvidenceOutbox.task_id == task_id)
    return [
        {
            "outbox_id": item.outbox_id,
            "task_id": item.task_id,
            "batch_id": item.batch_id,
            "event_type": item.event_type,
            "payload_hash": item.payload_hash,
            "status": item.status,
            "attempt_count": item.attempt_count,
            "next_attempt_at": item.next_attempt_at,
            "last_error": item.last_error,
            "published_at": item.published_at,
        }
        for item in db.scalars(query).all()
    ]


@router.post("/evidence/outbox/process")
def process_evidence_outbox(
    limit: int = Query(default=25, ge=1, le=100),
    user: User = Depends(require_roles("REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    results = process_local_demo_outbox(db, limit=limit)
    db.commit()
    return {
        "processed": len(results),
        "results": results,
        "worker_mode": (
            "ON_DEMAND_FISCO_BCOS"
            if selected_anchor_adapter_status().get("capability_label") != "DEMO"
            else "ON_DEMAND_LOCAL_DEMO"
        ),
        "anchor_adapter": selected_anchor_adapter_status(),
    }


@router.get("/privacy/mpc/status")
def mpc_status(
    user: User = Depends(require_roles(*BUSINESS_ROLES)),
) -> dict:
    return AdditiveSecretSharingMPC.status()
