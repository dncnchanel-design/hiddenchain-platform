from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AnomalyEvent,
    AuditReport,
    DataContract,
    DataSpaceAgreement,
    DataUpload,
    DidIdentity,
    Organization,
    PrivacyComputeJob,
    SettlementResult,
    SettlementRule,
    SettlementTask,
    Signature,
    TaskParticipant,
    utc_now,
)
from ..security import sha256_json
from ..trust_models import (
    AgentPermission,
    AgentTool,
    BlockchainAnchor,
    DataCapsule,
    EvidenceBatch,
    EvidenceOutbox,
    ExecutionSnapshot,
    TtcAttempt,
    TtcStateTransition,
    UsagePolicy,
    UsagePolicyVersion,
)
from .algorithm_registry import AlgorithmRegistry


class TTCState(StrEnum):
    INIT = "INIT"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    DATA_AUTHORIZED = "DATA_AUTHORIZED"
    RULE_FROZEN = "RULE_FROZEN"
    COMPUTE_EXEC = "COMPUTE_EXEC"
    RESULT_CONFIRM = "RESULT_CONFIRM"
    AUDIT_GATE = "AUDIT_GATE"
    EVIDENCE_STAGE = "EVIDENCE_STAGE"
    EVIDENCE_ANCHOR = "EVIDENCE_ANCHOR"
    ARCHIVED = "ARCHIVED"

    REJECTED = "REJECTED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    REWORK = "REWORK"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    ANCHOR_RETRY = "ANCHOR_RETRY"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TrustDomainError(ValueError):
    """Fail-closed domain error with a stable machine-readable code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class IdentityVerificationError(TrustDomainError):
    pass


class AuthorizationDenied(TrustDomainError):
    pass


class InvalidTtcTransition(TrustDomainError):
    pass


class SnapshotIntegrityError(TrustDomainError):
    pass


class ResourceExpired(TrustDomainError):
    pass


NORMAL_TTC_PATH: tuple[TTCState, ...] = (
    TTCState.INIT,
    TTCState.IDENTITY_VERIFIED,
    TTCState.DATA_AUTHORIZED,
    TTCState.RULE_FROZEN,
    TTCState.COMPUTE_EXEC,
    TTCState.RESULT_CONFIRM,
    TTCState.AUDIT_GATE,
    TTCState.EVIDENCE_STAGE,
    TTCState.EVIDENCE_ANCHOR,
    TTCState.ARCHIVED,
)


ALLOWED_TTC_TRANSITIONS: dict[TTCState, frozenset[TTCState]] = {
    TTCState.INIT: frozenset(
        {TTCState.IDENTITY_VERIFIED, TTCState.REJECTED, TTCState.CANCELLED, TTCState.EXPIRED}
    ),
    TTCState.IDENTITY_VERIFIED: frozenset(
        {
            TTCState.DATA_AUTHORIZED,
            TTCState.REJECTED,
            TTCState.FAILED,
            TTCState.CANCELLED,
            TTCState.EXPIRED,
        }
    ),
    TTCState.DATA_AUTHORIZED: frozenset(
        {
            TTCState.RULE_FROZEN,
            TTCState.REJECTED,
            TTCState.FAILED,
            TTCState.CANCELLED,
            TTCState.EXPIRED,
        }
    ),
    TTCState.RULE_FROZEN: frozenset(
        {TTCState.COMPUTE_EXEC, TTCState.FAILED, TTCState.INTERRUPTED, TTCState.CANCELLED}
    ),
    TTCState.COMPUTE_EXEC: frozenset(
        {
            TTCState.RESULT_CONFIRM,
            TTCState.FAILED,
            TTCState.INTERRUPTED,
            TTCState.HUMAN_REVIEW,
        }
    ),
    TTCState.RESULT_CONFIRM: frozenset(
        {
            TTCState.AUDIT_GATE,
            TTCState.REWORK,
            TTCState.HUMAN_REVIEW,
            TTCState.REJECTED,
        }
    ),
    TTCState.AUDIT_GATE: frozenset(
        {
            TTCState.EVIDENCE_STAGE,
            TTCState.REWORK,
            TTCState.HUMAN_REVIEW,
            TTCState.REJECTED,
            TTCState.FAILED,
        }
    ),
    TTCState.EVIDENCE_STAGE: frozenset(
        {TTCState.EVIDENCE_ANCHOR, TTCState.ANCHOR_RETRY, TTCState.FAILED}
    ),
    TTCState.EVIDENCE_ANCHOR: frozenset(
        {TTCState.ARCHIVED, TTCState.ANCHOR_RETRY, TTCState.FAILED}
    ),
    TTCState.ANCHOR_RETRY: frozenset(
        {TTCState.EVIDENCE_ANCHOR, TTCState.FAILED, TTCState.INTERRUPTED}
    ),
    TTCState.HUMAN_REVIEW: frozenset(
        {
            TTCState.RESULT_CONFIRM,
            TTCState.AUDIT_GATE,
            TTCState.REWORK,
            TTCState.REJECTED,
            TTCState.CANCELLED,
        }
    ),
    TTCState.INTERRUPTED: frozenset(
        {TTCState.COMPUTE_EXEC, TTCState.ANCHOR_RETRY, TTCState.CANCELLED, TTCState.EXPIRED}
    ),
    TTCState.FAILED: frozenset({TTCState.REWORK, TTCState.ARCHIVED}),
    TTCState.REWORK: frozenset(
        {
            TTCState.RULE_FROZEN,
            TTCState.FAILED,
            TTCState.REJECTED,
            TTCState.CANCELLED,
            TTCState.EXPIRED,
        }
    ),
    TTCState.REJECTED: frozenset({TTCState.ARCHIVED}),
    TTCState.CANCELLED: frozenset({TTCState.ARCHIVED}),
    TTCState.EXPIRED: frozenset({TTCState.ARCHIVED}),
    TTCState.ARCHIVED: frozenset(),
}


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _now(value: datetime | None = None) -> datetime:
    return _as_naive_utc(value) if value else utc_now()


def _state(value: TTCState | str | None) -> TTCState:
    try:
        return TTCState(str(value or TTCState.INIT.value))
    except ValueError as exc:
        raise InvalidTtcTransition(
            "UNKNOWN_TTC_STATE", f"Unknown TTC state: {value!r}"
        ) from exc


def verify_active_identity(db: Session, did_id: str) -> DidIdentity:
    identity = db.get(DidIdentity, did_id)
    if identity is None:
        raise IdentityVerificationError("DID_NOT_FOUND", "DID identity does not exist")
    if identity.credential_status != "VALID":
        raise IdentityVerificationError(
            "DID_CREDENTIAL_INVALID",
            f"DID credential is not valid: {identity.credential_status}",
        )
    if identity.org_id:
        organization = db.get(Organization, identity.org_id)
        if organization is None or organization.status != "ACTIVE":
            raise IdentityVerificationError(
                "DID_ORGANIZATION_INACTIVE", "DID owner organization is not active"
            )
    return identity


def _ensure_active_window(
    *,
    status: str,
    valid_from: datetime | None,
    expires_at: datetime | None,
    resource: str,
    at: datetime | None = None,
    active_statuses: frozenset[str] = frozenset({"ACTIVE"}),
) -> None:
    current = _now(at)
    if status not in active_statuses:
        raise AuthorizationDenied(
            f"{resource}_INACTIVE", f"{resource} is not active: {status}"
        )
    if valid_from is not None and _as_naive_utc(valid_from) > current:
        raise AuthorizationDenied(
            f"{resource}_NOT_YET_VALID", f"{resource} validity window has not started"
        )
    if expires_at is not None and _as_naive_utc(expires_at) <= current:
        raise ResourceExpired(f"{resource}_EXPIRED", f"{resource} has expired")


def verify_active_policy_version(
    db: Session,
    policy_version_id: str,
    *,
    at: datetime | None = None,
) -> UsagePolicyVersion:
    version = db.get(UsagePolicyVersion, policy_version_id)
    if version is None:
        raise AuthorizationDenied("POLICY_VERSION_NOT_FOUND", "Usage policy version does not exist")
    policy = db.get(UsagePolicy, version.policy_id)
    if policy is None:
        raise AuthorizationDenied("POLICY_NOT_FOUND", "Usage policy does not exist")
    _ensure_active_window(
        status=policy.status,
        valid_from=None,
        expires_at=None,
        resource="POLICY",
        at=at,
    )
    _ensure_active_window(
        status=version.status,
        valid_from=version.valid_from,
        expires_at=version.expires_at,
        resource="POLICY_VERSION",
        at=at,
    )
    return version


def verify_active_contract(
    db: Session,
    contract_id: str,
    *,
    at: datetime | None = None,
) -> DataContract:
    contract = db.get(DataContract, contract_id)
    if contract is None:
        raise AuthorizationDenied("CONTRACT_NOT_FOUND", "Data contract does not exist")
    _ensure_active_window(
        status=contract.status,
        valid_from=None,
        expires_at=getattr(contract, "expires_at", None),
        resource="CONTRACT",
        at=at,
        active_statuses=frozenset({"ACTIVE", "AGREED", "EXECUTED"}),
    )
    agreement = db.scalar(
        select(DataSpaceAgreement)
        .where(DataSpaceAgreement.contract_id == contract.contract_id)
        .order_by(DataSpaceAgreement.created_at.desc())
    )
    if agreement is not None:
        _ensure_active_window(
            status=agreement.state,
            valid_from=agreement.valid_from,
            expires_at=agreement.expires_at,
            resource="CONTRACT_AGREEMENT",
            at=at,
            active_statuses=frozenset(
                {"NEGOTIATED", "AGREED", "ACTIVE", "EXECUTED", "CONSUMED"}
            ),
        )
    return contract


def authorize_agent_tool(
    db: Session,
    agent_did: str,
    tool_code: str,
    task_id: str | None = None,
) -> AgentPermission:
    verify_active_identity(db, agent_did)
    tool = db.scalar(select(AgentTool).where(AgentTool.tool_code == tool_code))
    if tool is None or not tool.enabled:
        raise AuthorizationDenied("AGENT_TOOL_UNAVAILABLE", "Agent Tool is unavailable")
    if tool.capability_label == "BLOCKED":
        raise AuthorizationDenied("AGENT_TOOL_BLOCKED", "Agent Tool capability is blocked")

    current = utc_now()
    permissions = db.scalars(
        select(AgentPermission)
        .where(
            AgentPermission.agent_did == agent_did,
            AgentPermission.tool_id == tool.tool_id,
            AgentPermission.status == "ACTIVE",
        )
        .order_by(AgentPermission.created_at.desc())
    ).all()
    for permission in permissions:
        try:
            _ensure_active_window(
                status=permission.status,
                valid_from=permission.valid_from,
                expires_at=permission.expires_at,
                resource="AGENT_PERMISSION",
                at=current,
            )
        except TrustDomainError:
            continue
        operations = {str(item).upper() for item in permission.operations_json}
        if not ({"INVOKE", "*"} & operations):
            continue
        if task_id is not None:
            scope = permission.scope_json or {}
            task_ids = {str(item) for item in scope.get("task_ids", [])}
            if not scope.get("allow_all_tasks", False) and str(scope.get("task_id", "")) != task_id:
                if task_id not in task_ids:
                    continue
        return permission
    raise AuthorizationDenied(
        "AGENT_TOOL_PERMISSION_DENIED", "No active least-privilege permission grants this Tool call"
    )


class TtcStateMachine:
    allowed_transitions = ALLOWED_TTC_TRANSITIONS

    @classmethod
    def can_transition(cls, from_state: TTCState | str, to_state: TTCState | str) -> bool:
        source = _state(from_state)
        target = _state(to_state)
        return target in cls.allowed_transitions[source]

    @staticmethod
    def _next_attempt_no(db: Session, task_id: str) -> int:
        latest = db.scalar(
            select(func.max(TtcAttempt.attempt_no)).where(TtcAttempt.task_id == task_id)
        )
        return int(latest or 0) + 1

    @classmethod
    def _resolve_attempt(
        cls,
        db: Session,
        task: SettlementTask,
        current_state: TTCState,
        *,
        trace_id: str,
        attempt_id: str | None,
    ) -> TtcAttempt:
        attempt: TtcAttempt | None = None
        if attempt_id:
            attempt = db.get(TtcAttempt, attempt_id)
            if attempt is None or attempt.task_id != task.task_id:
                raise InvalidTtcTransition(
                    "TTC_ATTEMPT_MISMATCH", "TTC attempt does not belong to the task"
                )
            current_attempt = int(getattr(task, "current_attempt", 0) or 0)
            if current_attempt and attempt.attempt_no != current_attempt:
                raise InvalidTtcTransition(
                    "TTC_ATTEMPT_STALE", "A stale TTC attempt cannot change task state"
                )
        if attempt is None:
            current_attempt = int(getattr(task, "current_attempt", 0) or 0)
            if current_attempt:
                attempt = db.scalar(
                    select(TtcAttempt).where(
                        TtcAttempt.task_id == task.task_id,
                        TtcAttempt.attempt_no == current_attempt,
                    )
                )
        if attempt is None:
            attempt = db.scalar(
                select(TtcAttempt)
                .where(TtcAttempt.task_id == task.task_id)
                .order_by(TtcAttempt.attempt_no.desc())
            )

        needs_rework_attempt = (
            current_state == TTCState.REWORK
            and attempt is not None
            and attempt.current_state == TTCState.REWORK.value
            and attempt.status == "REWORK_REQUIRED"
        )
        if attempt is not None and attempt.current_state != current_state.value:
            raise InvalidTtcTransition(
                "TTC_ATTEMPT_STATE_MISMATCH",
                "TTC attempt state does not match the authoritative task state",
            )
        if attempt is None or needs_rework_attempt:
            attempt_no = cls._next_attempt_no(db, task.task_id)
            attempt = TtcAttempt(
                task_id=task.task_id,
                capsule_id=task.capsule_id,
                attempt_no=attempt_no,
                current_state=current_state.value,
                status="ACTIVE",
                trace_id=trace_id,
            )
            db.add(attempt)
            db.flush()
            if hasattr(task, "current_attempt"):
                task.current_attempt = attempt_no
        return attempt

    @staticmethod
    def _assert_transition_gate(
        db: Session,
        *,
        task: SettlementTask,
        attempt_id: str,
        source: TTCState,
        target: TTCState,
    ) -> None:
        task_id = task.task_id

        if target == TTCState.IDENTITY_VERIFIED:
            participants = db.scalars(
                select(TaskParticipant).where(TaskParticipant.task_id == task_id)
            ).all()
            if len(participants) < 2:
                raise InvalidTtcTransition(
                    "TTC_PARTICIPANTS_REQUIRED",
                    "At least two task participants are required before identity verification",
                )
            for participant in participants:
                identity = db.scalar(
                    select(DidIdentity)
                    .where(
                        DidIdentity.owner_type == "ORG",
                        DidIdentity.owner_id == participant.org_id,
                        DidIdentity.org_id == participant.org_id,
                        DidIdentity.credential_status == "VALID",
                    )
                    .order_by(DidIdentity.created_at.desc())
                )
                if identity is None:
                    raise InvalidTtcTransition(
                        "PARTICIPANT_DID_REQUIRED",
                        f"Task participant {participant.org_id} lacks an active organization DID",
                    )
                verify_active_identity(db, identity.did_id)

        if target == TTCState.DATA_AUTHORIZED:
            participant_org_ids = set(
                db.scalars(
                    select(TaskParticipant.org_id).where(
                        TaskParticipant.task_id == task_id
                    )
                ).all()
            )
            contracts = db.scalars(
                select(DataContract).where(DataContract.task_id == task_id)
            ).all()
            covered_org_ids = {item.provider_org_id for item in contracts}
            if not participant_org_ids or not participant_org_ids.issubset(covered_org_ids):
                raise InvalidTtcTransition(
                    "PARTICIPANT_DATA_AUTHORIZATION_REQUIRED",
                    "Every task participant must have an active data contract before authorization",
                )
            for contract in contracts:
                verify_active_contract(db, contract.contract_id)
                if not contract.data_refs_json:
                    raise InvalidTtcTransition(
                        "AUTHORIZED_DATA_REFERENCE_REQUIRED",
                        f"Contract {contract.contract_id} does not reference authorized data",
                    )
                agreement = db.scalar(
                    select(DataSpaceAgreement)
                    .where(
                        DataSpaceAgreement.task_id == task_id,
                        DataSpaceAgreement.contract_id == contract.contract_id,
                    )
                    .order_by(DataSpaceAgreement.created_at.desc())
                )
                if agreement is None or agreement.state not in {
                    "NEGOTIATED",
                    "AGREED",
                    "ACTIVE",
                    "EXECUTED",
                    "CONSUMED",
                }:
                    raise InvalidTtcTransition(
                        "DATA_SPACE_AGREEMENT_REQUIRED",
                        f"Contract {contract.contract_id} lacks an active negotiated agreement",
                    )
                verify_active_identity(db, agreement.provider_did)
                verify_active_identity(db, agreement.consumer_did)
                for data_ref in contract.data_refs_json:
                    upload = db.scalar(
                        select(DataUpload).where(
                            (DataUpload.upload_id == str(data_ref))
                            | (DataUpload.data_ref == str(data_ref))
                        )
                    )
                    if (
                        upload is None
                        or upload.owner_org_id != contract.provider_org_id
                        or upload.trade_batch_no != task.trade_batch_no
                        or upload.validation_status != "PASSED"
                        or not upload.data_hash
                        or not upload.commitment
                    ):
                        raise InvalidTtcTransition(
                            "AUTHORIZED_DATA_INVALID",
                            f"Contract {contract.contract_id} references invalid or foreign data",
                        )

        if target in {TTCState.RULE_FROZEN, TTCState.COMPUTE_EXEC}:
            snapshot = db.scalar(
                select(ExecutionSnapshot).where(
                    ExecutionSnapshot.task_id == task_id,
                    ExecutionSnapshot.attempt_id == attempt_id,
                )
            )
            if snapshot is None:
                raise InvalidTtcTransition(
                    "RULE_FREEZE_REQUIRED",
                    "A persisted immutable execution snapshot is required before this transition",
                )
            ExecutionSnapshotService.verify(snapshot)

        if target == TTCState.RESULT_CONFIRM:
            snapshot = db.get(ExecutionSnapshot, task.execution_snapshot_id)
            if (
                snapshot is None
                or snapshot.attempt_id != attempt_id
                or snapshot.snapshot_hash != task.execution_snapshot_hash
            ):
                raise InvalidTtcTransition(
                    "COMPUTE_SNAPSHOT_MISMATCH",
                    "The result must be bound to the current immutable execution snapshot",
                )
            job = db.scalar(
                select(PrivacyComputeJob)
                .where(
                    PrivacyComputeJob.task_id == task_id,
                    PrivacyComputeJob.attempt_id == attempt_id,
                    PrivacyComputeJob.execution_snapshot_id == snapshot.snapshot_id,
                    PrivacyComputeJob.status == "SUCCESS",
                )
                .order_by(PrivacyComputeJob.created_at.desc())
            )
            summary = db.scalar(
                select(SettlementResult)
                .where(
                    SettlementResult.task_id == task_id,
                    SettlementResult.attempt_id == attempt_id,
                    SettlementResult.result_scope == "SUMMARY",
                )
                .order_by(SettlementResult.created_at.desc())
            )
            participant_org_ids = set(
                db.scalars(
                    select(TaskParticipant.org_id).where(
                        TaskParticipant.task_id == task_id
                    )
                ).all()
            )
            scoped_results = db.scalars(
                select(SettlementResult).where(
                    SettlementResult.task_id == task_id,
                    SettlementResult.attempt_id == attempt_id,
                    SettlementResult.result_scope == "ORG",
                )
            ).all()
            current_scoped_results = [
                item
                for item in scoped_results
                if summary is not None
                and (item.result_json or {}).get("result_hash_ref") == summary.result_hash
            ]
            if (
                job is None
                or not job.output_hash
                or summary is None
                or summary.result_hash != job.output_hash
                or summary.result_hash != sha256_json(summary.result_json)
                or {item.org_id for item in current_scoped_results} != participant_org_ids
                or any(
                    item.result_hash != sha256_json(item.result_json)
                    for item in current_scoped_results
                )
            ):
                raise InvalidTtcTransition(
                    "COMPUTE_RESULT_REQUIRED",
                    "A successful current-attempt compute job and complete hash-bound results are required",
                )

        if target in {TTCState.AUDIT_GATE, TTCState.EVIDENCE_STAGE}:
            participants = db.scalars(
                select(TaskParticipant).where(TaskParticipant.task_id == task_id)
            ).all()
            summary = db.scalar(
                select(SettlementResult)
                .where(
                    SettlementResult.task_id == task_id,
                    SettlementResult.attempt_id == attempt_id,
                    SettlementResult.result_scope == "SUMMARY",
                )
                .order_by(SettlementResult.created_at.desc())
            )
            if summary is None:
                raise InvalidTtcTransition(
                    "CONFIRMED_RESULTS_REQUIRED",
                    "A current settlement summary is required before the audit gate",
                )
            scoped_results = db.scalars(
                select(SettlementResult).where(
                    SettlementResult.task_id == task_id,
                    SettlementResult.attempt_id == attempt_id,
                    SettlementResult.result_scope == "ORG",
                    SettlementResult.confirm_status == "CONFIRMED",
                )
            ).all()
            current_results = {
                item.org_id: item
                for item in scoped_results
                if (item.result_json or {}).get("result_hash_ref") == summary.result_hash
            }
            for participant in participants:
                result = current_results.get(participant.org_id)
                if result is None:
                    raise InvalidTtcTransition(
                        "MULTIPARTY_CONFIRMATION_REQUIRED",
                        "Every task participant must approve the current result before audit",
                    )
                signature = db.scalar(
                    select(Signature)
                    .where(
                        Signature.task_id == task_id,
                        Signature.signer_org_id == participant.org_id,
                        Signature.target_type == "RESULT_CONFIRM",
                        Signature.target_id == result.result_id,
                        Signature.target_hash == result.result_hash,
                        Signature.verify_status == "VALID",
                    )
                    .order_by(Signature.created_at.desc())
                )
                if signature is None:
                    raise InvalidTtcTransition(
                        "RESULT_SIGNATURE_REQUIRED",
                        f"Participant {participant.org_id} lacks a valid result signature",
                    )
                verify_active_identity(db, signature.signer_did)

            open_anomalies = int(
                db.scalar(
                    select(func.count(AnomalyEvent.event_id)).where(
                        AnomalyEvent.task_id == task_id,
                        AnomalyEvent.status == "OPEN",
                    )
                )
                or 0
            )
            if open_anomalies:
                raise InvalidTtcTransition(
                    "OPEN_ANOMALY_BLOCKS_AUDIT_GATE",
                    "Open anomaly events must be resolved before the audit gate",
                )
            if str(task.risk_level or "UNKNOWN").upper() != "LOW":
                report = db.scalar(
                    select(AuditReport)
                    .where(
                        AuditReport.task_id == task_id,
                        AuditReport.attempt_id == attempt_id,
                    )
                    .order_by(AuditReport.created_at.desc(), AuditReport.report_id.desc())
                )
                approval = (
                    db.scalar(
                        select(Signature)
                        .where(
                            Signature.task_id == task_id,
                            Signature.target_type == "AUDIT_REPORT_APPROVE",
                            Signature.target_id == report.report_id,
                            Signature.target_hash == report.report_hash,
                            Signature.verify_status == "VALID",
                        )
                        .order_by(Signature.created_at.desc())
                    )
                    if report is not None
                    else None
                )
                if report is None or report.status != "APPROVED" or approval is None:
                    raise InvalidTtcTransition(
                        "AUDIT_APPROVAL_REQUIRED",
                        "Medium/high-risk settlement requires an approved current audit report",
                    )
                verify_active_identity(db, approval.signer_did)

        if target == TTCState.EVIDENCE_STAGE:
            batch = db.scalar(
                select(EvidenceBatch)
                .where(
                    EvidenceBatch.task_id == task_id,
                    EvidenceBatch.attempt_id == attempt_id,
                    EvidenceBatch.batch_type == "FINAL_SETTLEMENT",
                    EvidenceBatch.status == "SEALED",
                )
                .order_by(EvidenceBatch.sealed_at.desc())
            )
            outbox = (
                db.scalar(
                    select(EvidenceOutbox).where(
                        EvidenceOutbox.batch_id == batch.batch_id,
                        EvidenceOutbox.status.in_(
                            {"PENDING", "PROCESSING", "RETRY_WAIT", "PUBLISHED"}
                        ),
                    )
                )
                if batch is not None
                else None
            )
            if batch is None or outbox is None:
                raise InvalidTtcTransition(
                    "SEALED_EVIDENCE_BATCH_REQUIRED",
                    "A sealed final-settlement batch and transactional outbox event are required",
                )
            try:
                from .evidence_outbox import verify_sealed_batch

                verify_sealed_batch(db, batch)
            except Exception as exc:
                raise InvalidTtcTransition(
                    "SEALED_EVIDENCE_BATCH_INVALID",
                    "The final-settlement evidence batch failed integrity verification",
                ) from exc

        if target == TTCState.EVIDENCE_ANCHOR or (
            target == TTCState.ARCHIVED and source == TTCState.EVIDENCE_ANCHOR
        ):
            batch = db.scalar(
                select(EvidenceBatch)
                .where(
                    EvidenceBatch.task_id == task_id,
                    EvidenceBatch.attempt_id == attempt_id,
                    EvidenceBatch.batch_type == "FINAL_SETTLEMENT",
                )
                .order_by(EvidenceBatch.sealed_at.desc())
            )
            if batch is None:
                raise InvalidTtcTransition(
                    "EVIDENCE_BATCH_REQUIRED",
                    "A sealed final-settlement evidence batch is required",
                )
            outbox = db.scalar(
                select(EvidenceOutbox).where(
                    EvidenceOutbox.batch_id == batch.batch_id,
                    EvidenceOutbox.status == "PUBLISHED",
                )
            )
            anchor = db.scalar(
                select(BlockchainAnchor).where(
                    BlockchainAnchor.batch_id == batch.batch_id
                )
            )
            try:
                from .evidence_outbox import (
                    SUCCESSFUL_ANCHOR_RECEIPT_STATUSES,
                    canonical_hash,
                    verify_sealed_batch,
                )

                verified_root = verify_sealed_batch(db, batch)
                outbox_payload_valid = (
                    outbox is not None
                    and canonical_hash(outbox.payload_json) == outbox.payload_hash
                    and outbox.payload_json.get("batch_id") == batch.batch_id
                    and outbox.payload_json.get("merkle_root") == verified_root
                )
                anchor_response_valid = (
                    anchor is not None
                    and anchor.response_json.get("batch_id") == batch.batch_id
                    and anchor.response_json.get("merkle_root") == verified_root
                    and anchor.response_json.get("payload_hash") == outbox.payload_hash
                )
            except Exception as exc:
                raise InvalidTtcTransition(
                    "EVIDENCE_ANCHOR_INTEGRITY_INVALID",
                    "The evidence batch, outbox or anchor hash chain is invalid",
                ) from exc
            if (
                outbox is None
                or outbox.status != "PUBLISHED"
                or outbox.published_at is None
                or not outbox_payload_valid
                or anchor is None
                or str(anchor.status).upper()
                not in SUCCESSFUL_ANCHOR_RECEIPT_STATUSES
                or anchor.anchored_at is None
                or not anchor.transaction_hash
                or anchor.anchor_payload_hash != outbox.payload_hash
                or not anchor_response_valid
            ):
                raise InvalidTtcTransition(
                    "EVIDENCE_ANCHOR_REQUIRED",
                    "A published outbox event and persisted anchor receipt are required",
                )

    @classmethod
    def transition(
        cls,
        db: Session,
        task: SettlementTask,
        to_state: TTCState | str,
        actor_did: str,
        trigger: str,
        reason: str,
        agent_did: str | None = None,
        trace_id: str | None = None,
        attempt_id: str | None = None,
    ) -> TtcStateTransition:
        if not trigger.strip() or not reason.strip():
            raise InvalidTtcTransition(
                "TTC_TRANSITION_CONTEXT_REQUIRED", "Transition trigger and reason are required"
            )
        verify_active_identity(db, actor_did)
        if agent_did:
            verify_active_identity(db, agent_did)

        locked_task = db.scalar(
            select(SettlementTask)
            .where(SettlementTask.task_id == task.task_id)
            .with_for_update()
        )
        if locked_task is None:
            raise InvalidTtcTransition("TTC_TASK_NOT_FOUND", "TTC task does not exist")
        task = locked_task

        source = _state(getattr(task, "ttc_state", TTCState.INIT.value))
        target = _state(to_state)
        if not cls.can_transition(source, target):
            raise InvalidTtcTransition(
                "INVALID_TTC_TRANSITION",
                f"TTC transition {source.value} -> {target.value} is not allowed",
            )

        current_trace_id = trace_id or uuid.uuid4().hex
        attempt = cls._resolve_attempt(
            db,
            task,
            source,
            trace_id=current_trace_id,
            attempt_id=attempt_id,
        )
        # SessionLocal intentionally disables autoflush.  Security gates must
        # evaluate the artifacts created in the same transaction (contracts,
        # compute results and signatures), not a stale database snapshot.
        db.flush()
        cls._assert_transition_gate(
            db,
            task=task,
            attempt_id=attempt.attempt_id,
            source=source,
            target=target,
        )
        next_sequence = int(
            db.scalar(
                select(func.max(TtcStateTransition.sequence_no)).where(
                    TtcStateTransition.attempt_id == attempt.attempt_id
                )
            )
            or 0
        ) + 1
        occurred_at = utc_now()
        transition_payload = {
            "task_id": task.task_id,
            "attempt_id": attempt.attempt_id,
            "sequence_no": next_sequence,
            "from_state": source.value,
            "to_state": target.value,
            "actor_did": actor_did,
            "agent_did": agent_did,
            "trigger": trigger,
            "reason": reason,
            "trace_id": current_trace_id,
            "occurred_at": occurred_at.isoformat(),
        }
        transition = TtcStateTransition(
            attempt_id=attempt.attempt_id,
            task_id=task.task_id,
            sequence_no=next_sequence,
            from_state=source.value,
            to_state=target.value,
            actor_did=actor_did,
            agent_did=agent_did,
            trigger_code=trigger,
            reason=reason,
            trace_id=current_trace_id,
            transition_hash=sha256_json(transition_payload),
            occurred_at=occurred_at,
        )
        db.add(transition)

        attempt.current_state = target.value
        if target == TTCState.FAILED:
            attempt.status = "FAILED"
            attempt.failure_code = trigger
            attempt.failure_detail = reason
            attempt.ended_at = occurred_at
        elif target == TTCState.REWORK:
            attempt.status = "REWORK_REQUIRED"
            attempt.ended_at = occurred_at
        elif target == TTCState.INTERRUPTED:
            attempt.status = "INTERRUPTED"
        elif target in {
            TTCState.ARCHIVED,
            TTCState.REJECTED,
            TTCState.CANCELLED,
            TTCState.EXPIRED,
        }:
            attempt.status = "CLOSED"
            attempt.ended_at = occurred_at
        else:
            attempt.status = "ACTIVE"
            if target in {TTCState.COMPUTE_EXEC, TTCState.EVIDENCE_ANCHOR}:
                attempt.ended_at = None

        if hasattr(task, "ttc_state"):
            task.ttc_state = target.value
        if hasattr(task, "state_version"):
            task.state_version = int(getattr(task, "state_version", 0) or 0) + 1
        if hasattr(task, "last_transition_at"):
            task.last_transition_at = occurred_at
        if target == TTCState.ARCHIVED and hasattr(task, "archived_at"):
            task.archived_at = occurred_at
        capsule = db.get(DataCapsule, task.capsule_id)
        if capsule is not None:
            capsule.status = target.value
        db.flush()
        return transition


def _record_ref(record: Any, *, identifier: str, fields: Iterable[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {identifier: getattr(record, identifier)}
    for field in fields:
        value = getattr(record, field, None)
        if isinstance(value, datetime):
            value = _as_naive_utc(value).isoformat()
        payload[field] = value
    return payload


class ExecutionSnapshotService:
    SNAPSHOT_SCHEMA = "hiddenchain.execution-snapshot/v1"

    @classmethod
    def _payload(
        cls,
        *,
        task: SettlementTask,
        attempt: TtcAttempt,
        rule: SettlementRule,
        contracts: list[DataContract],
        data_uploads: list[DataUpload],
        algorithm_descriptor: Mapping[str, Any],
    ) -> dict[str, Any]:
        contract_refs = sorted(
            (
                _record_ref(
                    contract,
                    identifier="contract_id",
                    fields=(
                        "task_id",
                        "provider_org_id",
                        "consumer_type",
                        "purpose",
                        "policy_hash",
                        "status",
                        "expires_at",
                    ),
                )
                for contract in contracts
            ),
            key=lambda item: item["contract_id"],
        )
        data_refs = sorted(
            (
                _record_ref(
                    upload,
                    identifier="upload_id",
                    fields=(
                        "asset_type",
                        "owner_org_id",
                        "trade_batch_no",
                        "data_hash",
                        "commitment",
                        "schema_version",
                        "validation_status",
                    ),
                )
                for upload in data_uploads
            ),
            key=lambda item: item["upload_id"],
        )
        algorithm = {
            "code": str(algorithm_descriptor["code"]),
            "version": str(algorithm_descriptor["version"]),
            "hash": str(algorithm_descriptor["hash"]),
            "adapter_code": str(algorithm_descriptor["adapter_code"]),
            "source_hash": str(algorithm_descriptor.get("source_hash", "")),
            "component_source_hashes": algorithm_descriptor.get(
                "component_source_hashes", {}
            ),
            "build_manifest": algorithm_descriptor.get("build_manifest", {}),
            "deterministic": bool(algorithm_descriptor["deterministic"]),
            "input_schema": algorithm_descriptor.get("input_schema", {}),
            "output_schema": algorithm_descriptor.get("output_schema", {}),
            "capability_label": algorithm_descriptor.get("capability_label", "LOCAL_REAL"),
            "attestation_status": algorithm_descriptor.get(
                "attestation_status", "NOT_PROVIDED"
            ),
            "boundary": algorithm_descriptor.get("boundary", ""),
        }
        return {
            "schema": cls.SNAPSHOT_SCHEMA,
            "task": {
                "task_id": task.task_id,
                "capsule_id": task.capsule_id,
                "trade_batch_no": task.trade_batch_no,
                "period_start": str(task.period_start),
                "period_end": str(task.period_end),
                "attempt_no": attempt.attempt_no,
            },
            "rule": {
                "rule_id": rule.rule_id,
                "version": rule.rule_version,
                "hash": rule.rule_hash,
                "formula_dsl": rule.formula_dsl,
                "parameters": rule.parameters_json,
                "policy_refs": sorted(str(item) for item in rule.policy_refs_json),
            },
            "policies": sorted(
                {
                    str(contract.policy_hash)
                    for contract in contracts
                    if contract.policy_hash
                }
            ),
            "contracts": contract_refs,
            "data": data_refs,
            "algorithm": algorithm,
            "parameters": {
                "rule": rule.parameters_json,
                "algorithm": algorithm_descriptor.get("parameters", {}),
            },
            "units": algorithm_descriptor.get("units", {}),
        }

    @staticmethod
    def _require_algorithm_descriptor(descriptor: Mapping[str, Any]) -> None:
        missing = [
            key
            for key in (
                "code",
                "version",
                "hash",
                "adapter_code",
                "source_hash",
                "component_source_hashes",
                "build_manifest",
                "deterministic",
            )
            if key not in descriptor
        ]
        if missing:
            raise SnapshotIntegrityError(
                "ALGORITHM_DESCRIPTOR_INCOMPLETE",
                f"Algorithm descriptor is missing: {', '.join(missing)}",
            )
        if descriptor.get("deterministic") is not True:
            raise SnapshotIntegrityError(
                "NON_DETERMINISTIC_ALGORITHM",
                "Official execution requires an explicitly deterministic algorithm",
            )
        if descriptor.get("capability_label") == "BLOCKED":
            raise SnapshotIntegrityError(
                "ALGORITHM_CAPABILITY_BLOCKED", "Blocked algorithm capability cannot be frozen"
            )
        try:
            registered = AlgorithmRegistry.execution_descriptor(str(descriptor["code"]))
        except ValueError as exc:
            raise SnapshotIntegrityError(
                "ALGORITHM_NOT_REGISTERED", "Official execution requires a registered algorithm"
            ) from exc
        if dict(descriptor) != registered:
            raise SnapshotIntegrityError(
                "ALGORITHM_DESCRIPTOR_MISMATCH",
                "Algorithm descriptor does not match the repository-owned registry",
            )

    @classmethod
    def freeze(
        cls,
        db: Session,
        task: SettlementTask,
        rule: SettlementRule,
        contracts: Iterable[DataContract],
        data_uploads: Iterable[DataUpload],
        algorithm_descriptor: Mapping[str, Any],
        actor_did: str,
        trace_id: str,
    ) -> ExecutionSnapshot:
        verify_active_identity(db, actor_did)
        current_state = _state(getattr(task, "ttc_state", TTCState.INIT.value))
        if current_state not in {
            TTCState.DATA_AUTHORIZED,
            TTCState.RULE_FROZEN,
            TTCState.REWORK,
        }:
            raise SnapshotIntegrityError(
                "RULE_FREEZE_STATE_INVALID",
                "Rule Freeze is allowed only after DATA_AUTHORIZED",
            )
        if rule.status not in {"ACTIVE", "APPROVED", "FROZEN"}:
            raise AuthorizationDenied("RULE_INACTIVE", "Settlement rule is not active")
        if rule.rule_id != task.rule_id:
            raise SnapshotIntegrityError("RULE_TASK_MISMATCH", "Task references a different rule")

        contract_records = list(contracts)
        upload_records = list(data_uploads)
        if not contract_records:
            raise AuthorizationDenied("CONTRACT_REQUIRED", "At least one active contract is required")
        if not upload_records:
            raise SnapshotIntegrityError("AUTHORIZED_DATA_REQUIRED", "No authorized input data supplied")
        participant_org_ids = set(
            db.scalars(
                select(TaskParticipant.org_id).where(
                    TaskParticipant.task_id == task.task_id
                )
            ).all()
        )
        contract_provider_ids = {item.provider_org_id for item in contract_records}
        if not participant_org_ids.issubset(contract_provider_ids):
            raise AuthorizationDenied(
                "PARTICIPANT_CONTRACT_COVERAGE_INCOMPLETE",
                "Rule Freeze requires an active contract for every task participant",
            )
        upload_owner_ids = {item.owner_org_id for item in upload_records}
        if not participant_org_ids.issubset(upload_owner_ids):
            raise AuthorizationDenied(
                "PARTICIPANT_INPUT_COVERAGE_INCOMPLETE",
                "Rule Freeze requires an authorized input from every task participant",
            )
        for contract in contract_records:
            if contract.task_id != task.task_id:
                raise AuthorizationDenied("CONTRACT_TASK_MISMATCH", "Contract belongs to another task")
            provider_allowed = contract.provider_org_id in participant_org_ids or (
                contract.provider_org_id == task.creator_org_id
                and contract.purpose == "GRID_SECURITY_CHECK"
            )
            if not provider_allowed:
                raise AuthorizationDenied(
                    "CONTRACT_PROVIDER_OUTSIDE_TASK",
                    "Contract provider is not a task participant or the controlled grid provider",
                )
            verify_active_contract(db, contract.contract_id)
        authorized_uploads: dict[str, set[str]] = {}
        for contract in contract_records:
            for upload_id in contract.data_refs_json:
                authorized_uploads.setdefault(str(upload_id), set()).add(
                    contract.provider_org_id
                )
        for upload in upload_records:
            authorized_owners = {
                *authorized_uploads.get(upload.upload_id, set()),
                *authorized_uploads.get(upload.data_ref, set()),
            }
            if upload.owner_org_id not in authorized_owners:
                raise AuthorizationDenied(
                    "DATA_NOT_AUTHORIZED_BY_CONTRACT",
                    f"Input data {upload.upload_id} is not covered by a task contract from its owner",
                )
            if upload.trade_batch_no != task.trade_batch_no:
                raise AuthorizationDenied(
                    "DATA_TASK_BATCH_MISMATCH",
                    f"Input data {upload.upload_id} belongs to another trade batch",
                )
            if upload.validation_status != "PASSED":
                raise SnapshotIntegrityError(
                    "DATA_VALIDATION_FAILED", f"Input data {upload.upload_id} did not pass validation"
                )
            if not upload.data_hash or not upload.commitment:
                raise SnapshotIntegrityError(
                    "DATA_PROVENANCE_INCOMPLETE",
                    f"Input data {upload.upload_id} lacks hash or commitment",
                )
        cls._require_algorithm_descriptor(algorithm_descriptor)

        attempt = TtcStateMachine._resolve_attempt(
            db,
            task,
            current_state,
            trace_id=trace_id,
            attempt_id=None,
        )
        payload = cls._payload(
            task=task,
            attempt=attempt,
            rule=rule,
            contracts=contract_records,
            data_uploads=upload_records,
            algorithm_descriptor=algorithm_descriptor,
        )
        snapshot_hash = sha256_json(payload)
        existing = db.scalar(
            select(ExecutionSnapshot).where(
                ExecutionSnapshot.task_id == task.task_id,
                ExecutionSnapshot.attempt_id == attempt.attempt_id,
            )
        )
        if existing is not None:
            cls.verify(existing)
            if existing.snapshot_hash != snapshot_hash:
                raise SnapshotIntegrityError(
                    "RULE_FREEZE_CONFLICT",
                    "This TTC attempt already has a different immutable snapshot",
                )
            if hasattr(task, "execution_snapshot_id"):
                task.execution_snapshot_id = existing.snapshot_id
            if hasattr(task, "execution_snapshot_hash"):
                task.execution_snapshot_hash = existing.snapshot_hash
            return existing

        latest_version = db.scalar(
            select(func.max(ExecutionSnapshot.snapshot_version)).where(
                ExecutionSnapshot.task_id == task.task_id
            )
        )
        snapshot = ExecutionSnapshot(
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            snapshot_version=int(latest_version or 0) + 1,
            rule_id=rule.rule_id,
            rule_version=rule.rule_version,
            rule_hash=rule.rule_hash,
            policy_refs_json=payload["policies"],
            contract_refs_json=payload["contracts"],
            data_refs_json=payload["data"],
            algorithm_code=str(algorithm_descriptor["code"]),
            algorithm_version=str(algorithm_descriptor["version"]),
            algorithm_hash=str(algorithm_descriptor["hash"]),
            parameters_json=payload["parameters"],
            units_json=payload["units"],
            canonical_payload_json=payload,
            snapshot_hash=snapshot_hash,
            frozen_by_did=actor_did,
            trace_id=trace_id,
        )
        db.add(snapshot)
        db.flush()
        if hasattr(task, "execution_snapshot_id"):
            task.execution_snapshot_id = snapshot.snapshot_id
        if hasattr(task, "execution_snapshot_hash"):
            task.execution_snapshot_hash = snapshot.snapshot_hash
        TtcStateMachine.transition(
            db,
            task,
            TTCState.RULE_FROZEN,
            actor_did,
            "RULE_FREEZE",
            "Immutable execution snapshot persisted",
            trace_id=trace_id,
            attempt_id=attempt.attempt_id,
        )
        return snapshot

    @staticmethod
    def verify(snapshot: ExecutionSnapshot) -> None:
        payload = snapshot.canonical_payload_json
        actual_hash = sha256_json(payload)
        if actual_hash != snapshot.snapshot_hash:
            raise SnapshotIntegrityError(
                "EXECUTION_SNAPSHOT_HASH_MISMATCH", "Execution snapshot payload hash does not match"
            )
        try:
            consistent = (
                payload["task"]["task_id"] == snapshot.task_id
                and payload["rule"]["rule_id"] == snapshot.rule_id
                and payload["rule"]["version"] == snapshot.rule_version
                and payload["rule"]["hash"] == snapshot.rule_hash
                and payload["algorithm"]["code"] == snapshot.algorithm_code
                and payload["algorithm"]["version"] == snapshot.algorithm_version
                and payload["algorithm"]["hash"] == snapshot.algorithm_hash
                and payload["parameters"] == snapshot.parameters_json
                and payload["units"] == snapshot.units_json
            )
        except (KeyError, TypeError):
            consistent = False
        if not consistent:
            raise SnapshotIntegrityError(
                "EXECUTION_SNAPSHOT_FIELDS_MISMATCH",
                "Execution snapshot denormalized fields do not match its canonical payload",
            )
        try:
            frozen_descriptor = {
                **payload["algorithm"],
                "parameters": payload["parameters"]["algorithm"],
                "units": payload["units"],
            }
            registered_descriptor = AlgorithmRegistry.execution_descriptor(
                str(payload["algorithm"]["code"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotIntegrityError(
                "EXECUTION_SNAPSHOT_ALGORITHM_INVALID",
                "Frozen algorithm descriptor is incomplete or no longer registered",
            ) from exc
        if frozen_descriptor != registered_descriptor:
            raise SnapshotIntegrityError(
                "EXECUTION_SNAPSHOT_ALGORITHM_DRIFT",
                "Frozen algorithm descriptor does not match the current execution build",
            )

    @staticmethod
    def assert_unchanged(
        snapshot: ExecutionSnapshot,
        proposed_payload: Mapping[str, Any],
    ) -> None:
        ExecutionSnapshotService.verify(snapshot)
        if sha256_json(dict(proposed_payload)) != snapshot.snapshot_hash:
            raise SnapshotIntegrityError(
                "EXECUTION_SNAPSHOT_IMMUTABLE", "Frozen execution snapshot cannot be modified"
            )
