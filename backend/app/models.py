from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    org_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    org_name: Mapped[str] = mapped_column(String(128), nullable=False)
    credit_code: Mapped[str | None] = mapped_column(String(64))
    energy_domain: Mapped[str | None] = mapped_column(String(24), index=True)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(96), nullable=False)
    role_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    permissions_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    is_org_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class RevokedAccessToken(Base):
    __tablename__ = "revoked_access_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class DidIdentity(Base, TimestampMixin):
    __tablename__ = "did_identities"
    did_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_type: Mapped[str] = mapped_column(String(24), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    public_key_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    chain_address: Mapped[str | None] = mapped_column(String(128))
    credential_status: Mapped[str] = mapped_column(String(24), default="VALID", nullable=False)
    credential_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class DataUpload(Base, TimestampMixin):
    __tablename__ = "data_uploads"
    upload_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    owner_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    trade_batch_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    data_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(32), default="PASSED", nullable=False)
    signature_value: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ingress_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class SettlementRule(Base, TimestampMixin):
    __tablename__ = "settlement_rules"
    rule_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    formula_dsl: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    policy_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    approver_signatures_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False)


class SettlementTask(Base, TimestampMixin):
    __tablename__ = "settlement_tasks"
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    capsule_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False)
    trade_batch_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(Date, nullable=False)
    period_end: Mapped[datetime] = mapped_column(Date, nullable=False)
    rule_id: Mapped[str] = mapped_column(ForeignKey("settlement_rules.rule_id"), index=True)
    creator_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW", nullable=False)
    current_stage: Mapped[str] = mapped_column(String(64), default="任务创建", nullable=False)
    verification_profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    # Compatibility fields for the formal Trusted Transaction Capsule (TTC)
    # lifecycle.  The legacy business ``status`` remains available to the
    # existing frontend while ``ttc_state`` is the authoritative security
    # state used by the transition service.
    request_idempotency_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True
    )
    request_fingerprint: Mapped[str | None] = mapped_column(String(128))
    ttc_state: Mapped[str] = mapped_column(
        String(32), default="INIT", nullable=False, index=True
    )
    current_attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    execution_snapshot_id: Mapped[str | None] = mapped_column(String(36), index=True)
    execution_snapshot_hash: Mapped[str | None] = mapped_column(String(128))
    state_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_transition_at: Mapped[datetime | None] = mapped_column(DateTime)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)


class TaskParticipant(Base, TimestampMixin):
    __tablename__ = "task_participants"
    participant_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("settlement_tasks.task_id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    role_in_task: Mapped[str] = mapped_column(String(32), nullable=False)
    data_status: Mapped[str] = mapped_column(String(24), default="READY", nullable=False)
    confirm_status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)


class DataContract(Base, TimestampMixin):
    __tablename__ = "data_contracts"
    contract_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # Standalone data-use authorizations do not create a settlement task.  The
    # nullable FK preserves the legacy settlement relationship while allowing
    # the provider-approval workflow to persist a real contract without
    # inventing a task or linking it to an unrelated trade.
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("settlement_tasks.task_id"), index=True, nullable=True
    )
    provider_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    consumer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    data_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    external_negotiation_id: Mapped[str | None] = mapped_column(String(128), index=True)


class DataSpaceAgreement(Base, TimestampMixin):
    """Negotiated connector agreement kept separate from the legacy contract row.

    Keeping the negotiation state in its own table lets existing databases
    upgrade without changing the original data-contract schema while still
    exposing the connector lifecycle required by a data space.
    """

    __tablename__ = "data_space_agreements"
    agreement_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(ForeignKey("data_contracts.contract_id"), index=True)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("settlement_tasks.task_id"), index=True, nullable=True
    )
    provider_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    consumer_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    provider_did: Mapped[str] = mapped_column(String(160), nullable=False)
    consumer_did: Mapped[str] = mapped_column(String(160), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(32), default="HCDS-1.0", nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="OFFERED", nullable=False, index=True)
    requested_purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_code: Mapped[str] = mapped_column(String(64), nullable=False)
    data_product_ids_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    offered_policy_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    negotiated_policy_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decision_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)


class ContractNegotiationEvent(Base):
    """Append-only negotiation facts for a data contract.

    Attachments are deliberately metadata-only references.  A row never
    claims that a file was uploaded or downloaded; callers must point to an
    already registered evidence/upload reference.
    """

    __tablename__ = "contract_negotiation_events"
    __table_args__ = (
        UniqueConstraint(
            "contract_id",
            "state_version",
            name="uq_contract_negotiation_event_version",
        ),
        UniqueConstraint(
            "contract_id",
            "idempotency_key",
            name="uq_contract_negotiation_event_idempotency",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("data_contracts.contract_id"), index=True
    )
    agreement_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_space_agreements.agreement_id"), index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"), index=True)
    actor_org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.org_id"), index=True
    )
    actor_did: Mapped[str | None] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    terms_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    attachment_metadata_json: Mapped[list[Any]] = mapped_column(
        JSON, default=list, nullable=False
    )
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True)
    event_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_label: Mapped[str] = mapped_column(String(24), default="LOCAL_REAL", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class DataUsageRequest(Base, TimestampMixin):
    """Provider-governed request for a data asset outside a settlement task.

    This is intentionally a first-class request rather than a frontend-only
    record.  ``contract_id`` and ``agreement_id`` are populated only after an
    approval transaction creates the corresponding trust-domain rows.  The
    capability/signature fields describe the local controlled decision and do
    not claim an external production signature or chain anchor.
    """

    __tablename__ = "data_usage_requests"
    __table_args__ = (
        UniqueConstraint(
            "applicant_org_id",
            "idempotency_key",
            name="uq_data_usage_request_org_idempotency",
        ),
    )
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("data_assets.asset_id"), index=True)
    asset_version_id: Mapped[str] = mapped_column(
        ForeignKey("data_asset_versions.version_id"), index=True
    )
    applicant_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    applicant_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    provider_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    applicant_did: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_did: Mapped[str] = mapped_column(String(160), nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    usage_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    requested_fields_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    terms_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="SUBMITTED", nullable=False, index=True)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    reviewer_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"), index=True)
    reviewer_did: Mapped[str | None] = mapped_column(String(160))
    revoked_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"), index=True)
    revoked_by_did: Mapped[str | None] = mapped_column(String(160))
    decision_hash: Mapped[str | None] = mapped_column(String(128))
    decision_capability_label: Mapped[str | None] = mapped_column(String(32))
    decision_signature_id: Mapped[str | None] = mapped_column(String(36))
    contract_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_contracts.contract_id"), index=True
    )
    agreement_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_space_agreements.agreement_id"), index=True
    )
    state_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), index=True
    )
    request_fingerprint: Mapped[str | None] = mapped_column(String(128))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)


class PrivacyComputeJob(Base, TimestampMixin):
    __tablename__ = "privacy_compute_jobs"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    algorithm_code: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_code: Mapped[str] = mapped_column(String(64), default="LOCAL_CONTROLLED_SETTLEMENT_V1", nullable=False)
    input_hashes_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(128))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    execution_attestation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    logs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    privacy_guarantees_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    execution_snapshot_id: Mapped[str | None] = mapped_column(String(36), index=True)
    # A queued local job may be cancelled before execution starts.  The
    # action fields make a command replayable without manufacturing a second
    # job/attempt; retry stays blocked until a real requeue executor exists.
    state_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    action_code: Mapped[str | None] = mapped_column(String(32))
    action_idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True)
    action_fingerprint: Mapped[str | None] = mapped_column(String(128))
    action_response_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)


class SettlementResult(Base, TimestampMixin):
    __tablename__ = "settlement_results"
    result_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("settlement_tasks.task_id"), index=True)
    # Nullable only for compatibility with records created before formal TTC
    # attempts existed.  New trusted results must always bind to one attempt;
    # NULL rows are historical and cannot satisfy current-attempt gates.
    attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    result_scope: Mapped[str] = mapped_column(String(24), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    confirm_status: Mapped[str] = mapped_column(String(32), default="UNCONFIRMED", nullable=False)


class Signature(Base, TimestampMixin):
    __tablename__ = "signatures"
    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "target_id",
            "signer_org_id",
            "target_hash",
            name="uq_signature_business_confirmation",
        ),
    )
    signature_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    signer_org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    signer_did: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    signature_value: Mapped[str] = mapped_column(Text, nullable=False)
    verify_status: Mapped[str] = mapped_column(String(24), default="VALID", nullable=False)


class BlockchainEvidence(Base, TimestampMixin):
    __tablename__ = "blockchain_evidence"
    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    stage: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False)
    biz_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    block_height: Mapped[int] = mapped_column(Integer, nullable=False)
    chain_code: Mapped[str] = mapped_column(String(32), default="LOCAL_EVIDENCE_LEDGER_V1", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="CONFIRMED", nullable=False)


class TrustedExecutionReview(Base, TimestampMixin):
    """Human-reviewable accuracy record for a trusted execution result.

    The stored result and source snapshot contain only the values returned by
    the configured adapter. Cross-domain non-export requires external proof.
    """

    __tablename__ = "trusted_execution_reviews"
    review_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_status: Mapped[str] = mapped_column(String(24), nullable=False)
    result_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_snapshot_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    caller_identity_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    target_data_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    policy_hits_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    execution_plan_hash: Mapped[str | None] = mapped_column(String(128))
    automatic_status: Mapped[str] = mapped_column(String(24), default="NOT_RUN", nullable=False)
    checks_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    reviewer_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    reviewer_org_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reviewer_did: Mapped[str | None] = mapped_column(String(160))
    reviewer_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


class AgentEvent(Base, TimestampMixin):
    __tablename__ = "agent_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_code: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    agent_did: Mapped[str] = mapped_column(String(160), nullable=False)
    message_type: Mapped[str] = mapped_column(String(48), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(96), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    signed_call: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="SUCCESS", nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AssistantSession(Base, TimestampMixin):
    """Scoped, durable Trusted Space assistant conversation session."""

    __tablename__ = "assistant_sessions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_assistant_session_user_idempotency",
        ),
        UniqueConstraint("session_id", "org_id", name="uq_assistant_session_org_scope"),
    )

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    page_path: Mapped[str | None] = mapped_column(String(255))
    entity_type: Mapped[str | None] = mapped_column(String(64), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(96), index=True)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False, index=True)
    state_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)


class AssistantPlan(Base, TimestampMixin):
    """Deterministic assistant plan; it is not an execution engine."""

    __tablename__ = "assistant_plans"
    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_assistant_plan_idempotency"),
    )

    plan_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_sessions.session_id"), index=True
    )
    trigger_message_id: Mapped[str | None] = mapped_column(String(36), index=True)
    intent_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="READY", nullable=False, index=True)
    state_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    capability_label: Mapped[str] = mapped_column(String(32), default="LOCAL_REAL_DETERMINISTIC", nullable=False)
    source_of_truth: Mapped[str] = mapped_column(String(160), default="assistant_planner", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True)


class AssistantMessage(Base, TimestampMixin):
    """User/assistant records; content is a persisted deterministic summary."""

    __tablename__ = "assistant_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence_no", name="uq_assistant_message_sequence"),
        UniqueConstraint("session_id", "idempotency_key", name="uq_assistant_message_idempotency"),
    )

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("assistant_sessions.session_id"), index=True
    )
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("assistant_plans.plan_id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent_code: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="RECORDED", nullable=False)
    capability_label: Mapped[str] = mapped_column(String(32), default="LOCAL_REAL_DETERMINISTIC", nullable=False)
    source_of_truth: Mapped[str] = mapped_column(String(160), default="assistant_messages", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True)


class AssistantPlanStep(Base, TimestampMixin):
    """A read-only tool invocation or a pending human-review request."""

    __tablename__ = "assistant_plan_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "sequence_no", name="uq_assistant_step_sequence"),
        UniqueConstraint("plan_id", "idempotency_key", name="uq_assistant_step_idempotency"),
    )

    step_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(ForeignKey("assistant_plans.plan_id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    action_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_code: Mapped[str | None] = mapped_column(String(96), index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), index=True)
    target_id: Mapped[str | None] = mapped_column(String(96), index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="READY", nullable=False, index=True)
    state_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    invocation_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(96))
    capability_label: Mapped[str] = mapped_column(String(32), default="LOCAL_REAL_DETERMINISTIC", nullable=False)
    source_of_truth: Mapped[str] = mapped_column(String(160), default="assistant_plan_steps", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_org_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_name: Mapped[str] = mapped_column(String(96), nullable=False)
    action_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(24), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class UserNotification(Base):
    """A scoped, deduplicated notification for one authenticated user.

    Notifications are deliberately separate from audit logs: audit rows are
    immutable evidence, while this table is a user-facing read/unread inbox.
    The dedupe key is scoped to the recipient so one domain event can notify
    every eligible user without creating duplicate rows for the same user.
    """

    __tablename__ = "user_notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "dedupe_key",
            name="uq_user_notifications_user_dedupe",
        ),
    )

    notification_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    notification_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(96), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False, index=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False, index=True)


class AuditReport(Base, TimestampMixin):
    __tablename__ = "audit_reports"
    report_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    # See SettlementResult.attempt_id.  Legacy NULL reports remain readable
    # history but are never accepted as the current audit decision.
    attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    template_code: Mapped[str] = mapped_column(String(48), nullable=False)
    report_title: Mapped[str] = mapped_column(String(160), nullable=False)
    report_content: Mapped[str] = mapped_column(Text, nullable=False)
    report_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="GENERATED", nullable=False)


class AnomalyEvent(Base, TimestampMixin):
    __tablename__ = "anomaly_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text)


class PrivacyAnalysisJob(Base, TimestampMixin):
    __tablename__ = "privacy_analysis_jobs"
    analysis_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_name: Mapped[str] = mapped_column(String(128), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_ids_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    privacy_level: Mapped[str] = mapped_column(String(24), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), default="LOAD_ANALYSIS", nullable=False)
    privacy_budget: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result_hash: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", nullable=False)


class MetricRecord(Base):
    __tablename__ = "metric_records"
    metric_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    metric_unit: Mapped[str] = mapped_column(String(24), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False, index=True)
