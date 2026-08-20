from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import BUSINESS_ROLES, require_roles
from ..models import (
    DataContract,
    DataUpload,
    DidIdentity,
    SettlementRule,
    SettlementTask,
    TaskParticipant,
    User,
)
from ..trust_models import (
    AgentTool,
    AssetQuality,
    DataAsset,
    DataAssetPassport,
    DataAssetVersion,
    ExecutionSnapshot,
    TtcAttempt,
    TtcStateTransition,
)
from ..services.trust_domain import (
    AuthorizationDenied,
    ExecutionSnapshotService,
    IdentityVerificationError,
    InvalidTtcTransition,
    ResourceExpired,
    SnapshotIntegrityError,
    TTCState,
    TrustDomainError,
    TtcStateMachine,
    verify_active_identity,
)
from ..services.algorithm_registry import AlgorithmRegistry


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TtcTransitionRequest(_StrictModel):
    to_state: TTCState
    trigger: str = Field(min_length=2, max_length=96)
    reason: str = Field(min_length=2, max_length=1000)
    agent_did: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=64)
    attempt_id: str | None = Field(default=None, max_length=36)


class AlgorithmDescriptorRequest(_StrictModel):
    code: str = Field(min_length=2, max_length=96)


class RuleFreezeRequest(_StrictModel):
    rule_id: str | None = Field(default=None, max_length=36)
    contract_ids: list[str] = Field(min_length=1, max_length=64)
    data_upload_ids: list[str] = Field(min_length=1, max_length=256)
    algorithm: AlgorithmDescriptorRequest
    trace_id: str = Field(min_length=8, max_length=64)


MANUAL_TTC_TARGETS = frozenset(
    {
        TTCState.HUMAN_REVIEW,
        TTCState.REWORK,
        TTCState.INTERRUPTED,
        TTCState.CANCELLED,
    }
)


def _raise_domain_http(exc: TrustDomainError) -> None:
    if isinstance(exc, (IdentityVerificationError, AuthorizationDenied, ResourceExpired)):
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": exc.detail},
    ) from exc


def _actor_did(db: Session, user: User) -> str:
    identity = db.scalar(
        select(DidIdentity)
        .where(
            DidIdentity.org_id == user.org_id,
            DidIdentity.owner_type == "ORG",
        )
        .order_by(DidIdentity.created_at.desc())
    )
    if identity is None:
        raise IdentityVerificationError("ACTOR_DID_NOT_FOUND", "Authenticated user has no organization DID")
    verify_active_identity(db, identity.did_id)
    return identity.did_id


def _assert_if_match(task: SettlementTask, if_match: str) -> None:
    normalized = if_match.strip()
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    normalized = normalized.strip('"')
    if not normalized.isdigit():
        raise HTTPException(status_code=400, detail="If-Match must be a TTC state version")
    if int(normalized) != int(task.state_version or 1):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="TTC state version changed; refresh before retrying",
            headers={"ETag": f'"{int(task.state_version or 1)}"'},
        )


def _require_task_visibility(db: Session, user: User, task: SettlementTask) -> None:
    """Prevent business participants from enumerating unrelated TTC records."""

    if user.role_code in {"EXCHANGE", "REGULATOR", "ADMIN"}:
        return
    participant = db.scalar(
        select(TaskParticipant.participant_id).where(
            TaskParticipant.task_id == task.task_id,
            TaskParticipant.org_id == user.org_id,
        )
    )
    if participant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TTC task not found")


def _require_asset_visibility(user: User, asset: DataAsset) -> None:
    """Keep asset passports tenant-scoped outside trusted oversight roles."""

    if user.role_code in {"EXCHANGE", "REGULATOR", "ADMIN"}:
        return
    if asset.owner_org_id != user.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data asset not found")


def _attempt_payload(attempt: TtcAttempt) -> dict[str, Any]:
    return {
        "attempt_id": attempt.attempt_id,
        "attempt_no": attempt.attempt_no,
        "current_state": attempt.current_state,
        "status": attempt.status,
        "trace_id": attempt.trace_id,
        "failure_code": attempt.failure_code,
        "started_at": attempt.started_at,
        "ended_at": attempt.ended_at,
    }


def _transition_payload(transition: TtcStateTransition) -> dict[str, Any]:
    return {
        "transition_id": transition.transition_id,
        "attempt_id": transition.attempt_id,
        "sequence_no": transition.sequence_no,
        "from_state": transition.from_state,
        "to_state": transition.to_state,
        "actor_did": transition.actor_did,
        "agent_did": transition.agent_did,
        "trigger": transition.trigger_code,
        "reason": transition.reason,
        "trace_id": transition.trace_id,
        "transition_hash": transition.transition_hash,
        "occurred_at": transition.occurred_at,
    }


def _snapshot_payload(snapshot: ExecutionSnapshot) -> dict[str, Any]:
    ExecutionSnapshotService.verify(snapshot)
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "attempt_id": snapshot.attempt_id,
        "rule": {
            "rule_id": snapshot.rule_id,
            "version": snapshot.rule_version,
            "hash": snapshot.rule_hash,
        },
        "algorithm": {
            "code": snapshot.algorithm_code,
            "version": snapshot.algorithm_version,
            "hash": snapshot.algorithm_hash,
        },
        "policy_refs": snapshot.policy_refs_json,
        "contract_refs": snapshot.contract_refs_json,
        "data_refs": snapshot.data_refs_json,
        "parameters": snapshot.parameters_json,
        "units": snapshot.units_json,
        "snapshot_hash": snapshot.snapshot_hash,
        "frozen_by_did": snapshot.frozen_by_did,
        "trace_id": snapshot.trace_id,
        "frozen_at": snapshot.frozen_at,
        "immutable": True,
    }


def build_trust_domain_router(
    *,
    db_dependency: Callable[..., Session] = get_db,
    read_user_dependency: Callable[..., User] = require_roles(*BUSINESS_ROLES),
    operate_user_dependency: Callable[..., User] = require_roles(
        "EXCHANGE", "REGULATOR", "ADMIN"
    ),
) -> APIRouter:
    """Build a mountable router without granting Agents direct database access."""

    router = APIRouter(prefix="/trust-domain", tags=["trust-domain"])

    @router.get("/capabilities")
    def capabilities(
        user: User = Depends(read_user_dependency),
    ) -> dict[str, Any]:
        return {
            "service": "HIDDENCHAIN_TRUST_DOMAIN_V1",
            "capabilities": {
                "ttc_state_machine": {
                    "label": "LOCAL_REAL",
                    "persistence": "SQLALCHEMY",
                    "states": [state.value for state in TTCState],
                },
                "rule_freeze": {
                    "label": "LOCAL_REAL",
                    "immutable_snapshot": True,
                    "hash_algorithm": "SHA-256",
                },
                "data_space_control_plane": {
                    "label": "ADAPTER",
                    "external_edc_runtime": "NOT_CONFIGURED",
                },
                "blockchain_anchor": {
                    "label": "DEMO",
                    "consensus_verified": False,
                },
                "tee": {"label": "BLOCKED", "attestation": "NOT_CONFIGURED"},
            },
        }

    @router.get("/tasks/{task_id}/ttc")
    def task_ttc(
        task_id: str,
        user: User = Depends(read_user_dependency),
        db: Session = Depends(db_dependency),
    ) -> dict[str, Any]:
        task = db.get(SettlementTask, task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TTC task not found")
        _require_task_visibility(db, user, task)
        attempts = db.scalars(
            select(TtcAttempt)
            .where(TtcAttempt.task_id == task_id)
            .order_by(TtcAttempt.attempt_no.asc())
        ).all()
        transitions = db.scalars(
            select(TtcStateTransition)
            .where(TtcStateTransition.task_id == task_id)
            .order_by(TtcStateTransition.occurred_at.asc())
        ).all()
        snapshots = db.scalars(
            select(ExecutionSnapshot)
            .where(ExecutionSnapshot.task_id == task_id)
            .order_by(ExecutionSnapshot.snapshot_version.asc())
        ).all()
        try:
            snapshot_payloads = [_snapshot_payload(item) for item in snapshots]
        except SnapshotIntegrityError as exc:
            _raise_domain_http(exc)
        return {
            "task_id": task.task_id,
            "capsule_id": task.capsule_id,
            "ttc_state": getattr(task, "ttc_state", TTCState.INIT.value),
            "current_attempt": int(getattr(task, "current_attempt", 0) or 0),
            "attempts": [_attempt_payload(item) for item in attempts],
            "transitions": [_transition_payload(item) for item in transitions],
            "execution_snapshots": snapshot_payloads,
        }

    @router.post("/tasks/{task_id}/transitions")
    def transition_task(
        task_id: str,
        payload: TtcTransitionRequest,
        response: Response,
        user: User = Depends(operate_user_dependency),
        db: Session = Depends(db_dependency),
        if_match: str = Header(alias="If-Match"),
    ) -> dict[str, Any]:
        task = db.get(SettlementTask, task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TTC task not found")
        _assert_if_match(task, if_match)
        if payload.to_state not in MANUAL_TTC_TARGETS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "TTC_SYSTEM_TRANSITION_REQUIRED",
                    "message": "Normal TTC states can only be advanced by their owning domain service",
                },
            )
        try:
            transition = TtcStateMachine.transition(
                db,
                task,
                payload.to_state,
                _actor_did(db, user),
                payload.trigger,
                payload.reason,
                agent_did=payload.agent_did,
                trace_id=payload.trace_id,
                attempt_id=payload.attempt_id,
            )
            db.commit()
        except TrustDomainError as exc:
            db.rollback()
            _raise_domain_http(exc)
        response.headers["ETag"] = f'"{int(task.state_version or 1)}"'
        return {
            "task_id": task.task_id,
            "ttc_state": getattr(task, "ttc_state", transition.to_state),
            "transition": _transition_payload(transition),
        }

    @router.post("/tasks/{task_id}/rule-freeze")
    def freeze_task_rules(
        task_id: str,
        payload: RuleFreezeRequest,
        response: Response,
        user: User = Depends(operate_user_dependency),
        db: Session = Depends(db_dependency),
        if_match: str = Header(alias="If-Match"),
    ) -> dict[str, Any]:
        task = db.get(SettlementTask, task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TTC task not found")
        _assert_if_match(task, if_match)
        rule = db.get(SettlementRule, payload.rule_id or task.rule_id)
        if rule is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Settlement rule not found")
        contracts = db.scalars(
            select(DataContract).where(DataContract.contract_id.in_(payload.contract_ids))
        ).all()
        uploads = db.scalars(
            select(DataUpload).where(DataUpload.upload_id.in_(payload.data_upload_ids))
        ).all()
        if len(contracts) != len(set(payload.contract_ids)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data contract not found")
        if len(uploads) != len(set(payload.data_upload_ids)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data upload not found")
        try:
            registered_algorithm = AlgorithmRegistry.execution_descriptor(
                payload.algorithm.code
            )
            snapshot = ExecutionSnapshotService.freeze(
                db,
                task,
                rule,
                contracts,
                uploads,
                registered_algorithm,
                _actor_did(db, user),
                payload.trace_id,
            )
            db.commit()
        except TrustDomainError as exc:
            db.rollback()
            _raise_domain_http(exc)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "ALGORITHM_NOT_REGISTERED", "message": str(exc)},
            ) from exc
        response.headers["ETag"] = f'"{int(task.state_version or 1)}"'
        return {
            "task_id": task.task_id,
            "ttc_state": getattr(task, "ttc_state", TTCState.RULE_FROZEN.value),
            "execution_snapshot": _snapshot_payload(snapshot),
        }

    @router.get("/assets/{asset_id}/passport")
    def asset_passport(
        asset_id: str,
        user: User = Depends(read_user_dependency),
        db: Session = Depends(db_dependency),
    ) -> dict[str, Any]:
        asset = db.get(DataAsset, asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data asset not found")
        _require_asset_visibility(user, asset)
        version = db.scalar(
            select(DataAssetVersion)
            .where(DataAssetVersion.asset_id == asset_id)
            .order_by(DataAssetVersion.version_no.desc())
        )
        passport = (
            db.scalar(
                select(DataAssetPassport)
                .where(DataAssetPassport.asset_version_id == version.version_id)
                .order_by(DataAssetPassport.passport_version.desc())
            )
            if version
            else None
        )
        quality = (
            db.scalar(
                select(AssetQuality)
                .where(AssetQuality.asset_version_id == version.version_id)
                .order_by(AssetQuality.evaluated_at.desc())
            )
            if version
            else None
        )
        return {
            "asset": {
                "asset_id": asset.asset_id,
                "asset_code": asset.asset_code,
                "asset_name": asset.asset_name,
                "asset_type": asset.asset_type,
                "classification": asset.classification,
                "sensitivity_level": asset.sensitivity_level,
                "status": asset.status,
            },
            "version": (
                {
                    "version_id": version.version_id,
                    "version_no": version.version_no,
                    "schema_version": version.schema_version,
                    "data_hash": version.data_hash,
                    "commitment": version.commitment,
                    "immutable_hash": version.immutable_hash,
                    "status": version.status,
                }
                if version
                else None
            ),
            "passport": (
                {
                    "passport_id": passport.passport_id,
                    "passport_version": passport.passport_version,
                    "owner_did": passport.owner_did,
                    "provenance": passport.provenance_json,
                    "classification": passport.classification_json,
                    "permitted_use": passport.permitted_use_json,
                    "policy_refs": passport.policy_refs_json,
                    "evidence_refs": passport.evidence_refs_json,
                    "passport_hash": passport.passport_hash,
                    "status": passport.status,
                }
                if passport
                else None
            ),
            "latest_quality": (
                {
                    "quality_id": quality.quality_id,
                    "profile_version": quality.profile_version,
                    "metrics": quality.metrics_json,
                    "decision": quality.decision,
                    "quality_hash": quality.quality_hash,
                    "evidence_refs": quality.evidence_refs_json,
                    "evaluated_at": quality.evaluated_at,
                }
                if quality
                else None
            ),
        }

    @router.get("/agent-tools")
    def agent_tool_catalog(
        user: User = Depends(read_user_dependency),
        db: Session = Depends(db_dependency),
    ) -> list[dict[str, Any]]:
        tools = db.scalars(
            select(AgentTool).where(AgentTool.enabled.is_(True)).order_by(AgentTool.tool_code.asc())
        ).all()
        return [
            {
                "tool_code": tool.tool_code,
                "tool_name": tool.tool_name,
                "service_code": tool.service_code,
                "description": tool.description,
                "input_schema": tool.input_schema_json,
                "output_schema": tool.output_schema_json,
                "timeout_seconds": tool.timeout_seconds,
                "capability_label": tool.capability_label,
            }
            for tool in tools
        ]

    return router


router = build_trust_domain_router()
