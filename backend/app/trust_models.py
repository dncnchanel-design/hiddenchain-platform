from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, TimestampMixin, new_id, utc_now


class DataSource(Base, TimestampMixin):
    """A governed source registered at the controlled data-space boundary."""

    __tablename__ = "data_sources"

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_code: Mapped[str] = mapped_column(String(96), unique=True, nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(48), default="LOCAL_ADAPTER", nullable=False)
    endpoint_ref: Mapped[str | None] = mapped_column(String(255))
    security_domain: Mapped[str] = mapped_column(String(96), nullable=False)
    capability_label: Mapped[str] = mapped_column(String(24), default="ADAPTER", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class DataAsset(Base, TimestampMixin):
    __tablename__ = "data_assets"
    __table_args__ = (
        UniqueConstraint("owner_org_id", "asset_code", name="uq_data_asset_owner_code"),
    )

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"), index=True)
    owner_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    asset_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    asset_name: Mapped[str] = mapped_column(String(160), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    sensitivity_level: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class DataAssetVersion(Base):
    __tablename__ = "data_asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_no", name="uq_data_asset_version"),
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("data_assets.asset_id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    data_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    commitment: Mapped[str | None] = mapped_column(String(128))
    record_count: Mapped[int | None] = mapped_column(Integer)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class DataAssetPassport(Base):
    __tablename__ = "data_asset_passports"
    __table_args__ = (
        UniqueConstraint("asset_version_id", "passport_version", name="uq_asset_passport_version"),
    )

    passport_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_version_id: Mapped[str] = mapped_column(
        ForeignKey("data_asset_versions.version_id"), index=True
    )
    passport_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    owner_did: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    classification_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    permitted_use_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    policy_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    evidence_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    passport_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class AssetQuality(Base):
    __tablename__ = "asset_quality"

    quality_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_version_id: Mapped[str] = mapped_column(
        ForeignKey("data_asset_versions.version_id"), index=True
    )
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    quality_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    evaluated_by_did: Mapped[str] = mapped_column(String(160), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class UsagePolicy(Base, TimestampMixin):
    __tablename__ = "usage_policies"

    policy_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    policy_code: Mapped[str] = mapped_column(String(96), unique=True, nullable=False, index=True)
    policy_name: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    policy_type: Mapped[str] = mapped_column(String(48), nullable=False)
    current_version_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False, index=True)


class UsagePolicyVersion(Base):
    __tablename__ = "usage_policy_versions"
    __table_args__ = (
        UniqueConstraint("policy_id", "version_no", name="uq_usage_policy_version"),
    )

    policy_version_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    policy_id: Mapped[str] = mapped_column(ForeignKey("usage_policies.policy_id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class DataCapsule(Base, TimestampMixin):
    __tablename__ = "data_capsules"

    capsule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("settlement_tasks.task_id"), unique=True, nullable=False, index=True
    )
    owner_org_id: Mapped[str] = mapped_column(ForeignKey("organizations.org_id"), index=True)
    purpose: Mapped[str] = mapped_column(String(96), nullable=False)
    sensitivity_level: Mapped[str] = mapped_column(String(8), nullable=False)
    asset_version_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    policy_version_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    contract_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="INIT", nullable=False, index=True)
    capsule_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)


class TtcAttempt(Base):
    __tablename__ = "ttc_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_ttc_attempt_task_no"),
    )

    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("settlement_tasks.task_id"), index=True)
    capsule_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    current_state: Mapped[str] = mapped_column(String(32), default="INIT", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False, index=True)
    request_idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(128), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    failure_code: Mapped[str | None] = mapped_column(String(96))
    failure_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)


class TtcStateTransition(Base):
    __tablename__ = "ttc_state_transitions"
    __table_args__ = (
        UniqueConstraint("attempt_id", "sequence_no", name="uq_ttc_transition_sequence"),
        Index("ix_ttc_transition_task_occurred", "task_id", "occurred_at"),
    )

    transition_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("ttc_attempts.attempt_id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("settlement_tasks.task_id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    from_state: Mapped[str] = mapped_column(String(32), nullable=False)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actor_did: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    agent_did: Mapped[str | None] = mapped_column(String(160), index=True)
    trigger_code: Mapped[str] = mapped_column(String(96), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    transition_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class ExecutionSnapshot(Base):
    """An append-only Rule Freeze record used by the deterministic execution plane."""

    __tablename__ = "execution_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "attempt_id", "snapshot_version", name="uq_execution_snapshot_version"
        ),
        Index("ix_execution_snapshot_task_frozen", "task_id", "frozen_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("settlement_tasks.task_id"), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("ttc_attempts.attempt_id"), index=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_id: Mapped[str] = mapped_column(ForeignKey("settlement_rules.rule_id"), index=True)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    contract_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    data_refs_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    algorithm_code: Mapped[str] = mapped_column(String(96), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(48), nullable=False)
    algorithm_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    units_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    canonical_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    frozen_by_did: Mapped[str] = mapped_column(String(160), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class AgentTool(Base, TimestampMixin):
    __tablename__ = "agent_tools"

    tool_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tool_code: Mapped[str] = mapped_column(String(96), unique=True, nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    service_code: Mapped[str] = mapped_column(String(96), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    input_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    capability_label: Mapped[str] = mapped_column(String(24), default="LOCAL_REAL", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class AgentPermission(Base):
    __tablename__ = "agent_permissions"

    permission_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_did: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("agent_tools.tool_id"), index=True)
    operations_json: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False, index=True)
    granted_by_did: Mapped[str] = mapped_column(String(160), nullable=False)
    grant_reason: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    call_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tool_id: Mapped[str] = mapped_column(ForeignKey("agent_tools.tool_id"), index=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("agent_permissions.permission_id"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    agent_did: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(96))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class EvidenceBatch(Base):
    __tablename__ = "evidence_batches"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "attempt_id",
            "batch_type",
            name="uq_evidence_batch_task_attempt_type",
        ),
    )

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    batch_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    merkle_algorithm: Mapped[str] = mapped_column(
        String(32), default="SHA256_BINARY_DS_V1", nullable=False
    )
    merkle_root: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    leaf_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="SEALED", nullable=False, index=True)
    sealed_by_did: Mapped[str] = mapped_column(String(160), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class EvidenceBatchItem(Base):
    __tablename__ = "evidence_batch_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "sequence_no", name="uq_evidence_batch_sequence"),
    )

    item_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("evidence_batches.batch_id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_class: Mapped[str] = mapped_column(String(1), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_type: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_id: Mapped[str] = mapped_column(String(96), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_sensitive_data_included: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class EvidenceOutbox(Base):
    __tablename__ = "evidence_outbox"

    outbox_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_batches.batch_id"), index=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class BlockchainAnchor(Base):
    __tablename__ = "blockchain_anchors"

    anchor_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_batches.batch_id"), unique=True, nullable=False, index=True
    )
    adapter_code: Mapped[str] = mapped_column(String(96), nullable=False)
    capability_label: Mapped[str] = mapped_column(String(24), default="DEMO", nullable=False)
    network_code: Mapped[str] = mapped_column(String(96), nullable=False)
    anchor_payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    transaction_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    block_height: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    anchored_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class ImmutableSnapshotError(RuntimeError):
    pass


@event.listens_for(ExecutionSnapshot, "before_update")
def _reject_execution_snapshot_update(*_: Any) -> None:
    raise ImmutableSnapshotError("EXECUTION_SNAPSHOT_IMMUTABLE")


@event.listens_for(ExecutionSnapshot, "before_delete")
def _reject_execution_snapshot_delete(*_: Any) -> None:
    raise ImmutableSnapshotError("EXECUTION_SNAPSHOT_IMMUTABLE")
