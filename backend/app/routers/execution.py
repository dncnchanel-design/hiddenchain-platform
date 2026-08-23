from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..dependencies import require_roles
from ..models import BlockchainEvidence, TrustedExecutionReview, User
from ..schemas import (
    TrustedExecutionRequest,
    TrustedExecutionReviewRequest,
    TrustedExecutionTranslationRequest,
)
from ..services.common import add_audit_log, model_dict
from ..services.llm import DeepSeekUnavailable
from ..services.query_translation import (
    QueryTranslationRejected,
    translate_query,
    translation_hash,
    validate_client_translation,
)
from ..services.trust_execution import (
    EvidenceAuditLogger,
    CallerIdentity,
    EnergyNodeRegistry,
    TrustworthyExecutionController,
    TrustedExecutionReviewService,
    trusted_execution_status,
)


router = APIRouter(prefix="/trusted-execution", tags=["trusted-execution"])
TRUSTED_ROLES = ("EXCHANGE", "REGULATOR", "ADMIN")


@router.get("/status")
def execution_status(
    user: User = Depends(require_roles(*TRUSTED_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    status = trusted_execution_status()
    identity = CallerIdentity.from_user(db, user, user.role_code)
    # Expose the authenticated subject's verified state instead of making the
    # page infer a valid credential from the availability of the controller.
    status["credential_status"] = identity.credential_status
    status["did_verified"] = identity.did_verified
    status["nodes"] = EnergyNodeRegistry(db).catalog() if settings.app_env != "production" else []
    return status


@router.get("/policy/catalog")
def policy_catalog(user: User = Depends(require_roles(*TRUSTED_ROLES))) -> dict:
    return trusted_execution_status()["policy_engine"]


@router.post("/query")
def trusted_query(
    payload: TrustedExecutionRequest,
    user: User = Depends(require_roles(*TRUSTED_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    if payload.translation is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先完成查询翻译并确认后再执行")
    try:
        validated_translation = validate_client_translation(payload.translation.model_dump(mode="json"))
    except QueryTranslationRejected as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not payload.translation_hash or payload.translation_hash != translation_hash(validated_translation.model_dump(mode="json")):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="翻译预览已变化，请重新翻译后再执行")
    if settings.app_env == "production":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="跨能源数据节点尚未配置，生产环境不执行内置测试数据",
        )
    return TrustworthyExecutionController(db).execute(payload, user)


@router.post("/translate")
def translate_trusted_query(
    payload: TrustedExecutionTranslationRequest,
    user: User = Depends(require_roles(*TRUSTED_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = translate_query(payload)
    except DeepSeekUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="DeepSeek 翻译服务暂时不可用，查询未执行") from exc
    except QueryTranslationRejected as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    add_audit_log(
        db,
        action="TRANSLATE_TRUSTED_QUERY",
        target_type="TRUSTED_QUERY_TRANSLATION",
        target_id=result["translation_hash"],
        result="READY",
        user=user,
        details={
            "question": result["question"],
            "redacted_question": result["redacted_question"],
            "translation": result["translation"],
            "translation_hash": result["translation_hash"],
            "provider": result["provider"],
            "model": result["model"],
            "request_id": result["request_id"],
            "duration_ms": result["duration_ms"],
            "offline_test": result["offline_test"],
            "raw_data_accessed": False,
        },
    )
    db.commit()
    return result


@router.get("/reviews")
def list_execution_reviews(
    review_status: str | None = None,
    user: User = Depends(require_roles(*TRUSTED_ROLES)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(TrustedExecutionReview).order_by(TrustedExecutionReview.created_at.desc())
    if review_status:
        query = query.where(TrustedExecutionReview.verification_status == review_status.upper())
    return [
        TrustedExecutionReviewService.summary(item)
        for item in db.scalars(query).all()
    ]


@router.get("/reviews/{request_id}")
def get_execution_review(
    request_id: str,
    user: User = Depends(require_roles(*TRUSTED_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    review = db.scalar(
        select(TrustedExecutionReview).where(TrustedExecutionReview.request_id == request_id)
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="可信执行核对记录不存在")
    return TrustedExecutionReviewService.summary(review, include_snapshot=True)


@router.post("/reviews/{request_id}/confirm")
def confirm_execution_review(
    request_id: str,
    payload: TrustedExecutionReviewRequest,
    user: User = Depends(require_roles("REGULATOR", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    review = db.scalar(
        select(TrustedExecutionReview).where(TrustedExecutionReview.request_id == request_id)
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="可信执行核对记录不存在")
    if review.execution_status != "SUCCEEDED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有成功交付的结果可以核对确认")
    identity = CallerIdentity.from_user(db, user, "REGULATOR")
    if not identity.did_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="审核人员 DID/VC 无效")
    was_confirmed = review.verification_status == "CONFIRMED"
    try:
        review_summary, signature_value = TrustedExecutionReviewService.confirm(
            db,
            review,
            user=user,
            reviewer_did=identity.did,
            opinion=payload.opinion,
            accept=payload.accept,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if was_confirmed:
        return {
            "request_id": request_id,
            "verification_status": review.verification_status,
            "idempotent": True,
            "review": review_summary,
            "signature": signature_value,
        }
    add_audit_log(
        db,
        action="CONFIRM_TRUSTED_EXECUTION_REVIEW" if payload.accept else "REJECT_TRUSTED_EXECUTION_REVIEW",
        target_type="TRUSTED_EXECUTION_REVIEW",
        target_id=review.review_id,
        result="SUCCESS" if payload.accept else "REJECTED",
        user=user,
        current_trace_id=review.trace_id,
        details={
            "request_id": request_id,
            "result_hash": review.result_hash,
            "opinion": payload.opinion,
            "verification_status": review.verification_status,
            "automatic_status": review.automatic_status,
        },
    )
    db.commit()
    chain_payload = {
        "Request_ID": request_id,
        "Caller_Identity": review.caller_identity_json,
        "Target_Data": review.target_data_json,
        "Policy_Hit": review.policy_hits_json,
        "Execution_Status": "REVIEW_CONFIRMED" if payload.accept else "REVIEW_REJECTED",
        "Result_Hash": review.result_hash,
        "Trace_ID": review.trace_id,
        "Review_ID": review.review_id,
        "Reviewer_Identity": identity.to_dict(),
        "Review_Opinion": payload.opinion,
        "Accuracy_Checks": review.checks_json,
        "Source_Attestations": [
            item["source_attestation"]
            for item in review.source_snapshot_json
            if item.get("source_attestation")
        ],
    }
    evidence_record = EvidenceAuditLogger.enqueue(task_id=None, payload=chain_payload)
    return {
        "request_id": request_id,
        "verification_status": review.verification_status,
        "review": TrustedExecutionReviewService.summary(review, include_snapshot=True),
        "signature": signature_value,
        "evidence_audit": evidence_record,
    }


@router.get("/audit/{request_id}")
def trusted_audit(
    request_id: str,
    user: User = Depends(require_roles(*TRUSTED_ROLES)),
    db: Session = Depends(get_db),
) -> dict:
    evidence = db.scalars(
        select(BlockchainEvidence)
        .where(
            BlockchainEvidence.biz_type == "TRUSTED_EXECUTION",
            BlockchainEvidence.biz_id == request_id,
        )
        .order_by(BlockchainEvidence.created_at.desc())
    ).all()
    review = db.scalar(
        select(TrustedExecutionReview).where(TrustedExecutionReview.request_id == request_id)
    )
    return {
        "request_id": request_id,
        "status": evidence[0].status if evidence else "PENDING",
        "items": [model_dict(item) for item in evidence],
        "accuracy_review": TrustedExecutionReviewService.summary(review) if review else None,
        "raw_data_included": False,
    }
