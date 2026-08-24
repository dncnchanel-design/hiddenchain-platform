from __future__ import annotations

import hashlib
import inspect as python_inspect
import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    func,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection, Engine

from .models import Base

# Register formal tables on the shared metadata before revisions run.
from . import trust_models as _trust_models  # noqa: F401,E402


MIGRATION_METADATA = MetaData()
SCHEMA_MIGRATIONS = Table(
    "schema_migrations",
    MIGRATION_METADATA,
    Column("version", String(64), primary_key=True),
    Column("description", String(255), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("applied_at", DateTime, nullable=False),
)

POSTGRES_MIGRATION_LOCK_ID = 0x484344534D494752

LEGACY_TABLE_NAMES = frozenset(
    {
        "organizations",
        "users",
        "did_identities",
        "data_uploads",
        "settlement_rules",
        "settlement_tasks",
        "task_participants",
        "data_contracts",
        "data_space_agreements",
        "privacy_compute_jobs",
        "settlement_results",
        "signatures",
        "blockchain_evidence",
        "trusted_execution_reviews",
        "agent_events",
        "audit_logs",
        "audit_reports",
        "anomaly_events",
        "privacy_analysis_jobs",
        "metric_records",
    }
)

FORMAL_TRUST_TABLE_NAMES = frozenset(
    {
        "data_sources",
        "data_assets",
        "data_asset_versions",
        "data_asset_passports",
        "asset_quality",
        "usage_policies",
        "usage_policy_versions",
        "data_capsules",
        "ttc_attempts",
        "ttc_state_transitions",
        "execution_snapshots",
        "agent_tools",
        "agent_permissions",
        "agent_tool_calls",
        "evidence_batches",
        "evidence_batch_items",
        "evidence_outbox",
        "blockchain_anchors",
    }
)

AUTHORIZATION_TABLE_NAMES = frozenset({"data_usage_requests"})
NEGOTIATION_TABLE_NAMES = frozenset({"contract_negotiation_events"})
ASSISTANT_TABLE_NAMES = frozenset(
    {
        "assistant_sessions",
        "assistant_messages",
        "assistant_plans",
        "assistant_plan_steps",
    }
)
NOTIFICATION_TABLE_NAMES = frozenset({"user_notifications"})
REVOKED_TOKEN_TABLE_NAMES = frozenset({"revoked_access_tokens"})

COMPUTE_CONTROL_COLUMNS: dict[str, dict[str, str]] = {
    "privacy_compute_jobs": {
        "state_version": "INTEGER NOT NULL DEFAULT 1",
        "action_code": "VARCHAR(32)",
        "action_idempotency_key": "VARCHAR(160)",
        "action_fingerprint": "VARCHAR(128)",
        "action_response_json": "JSON NOT NULL DEFAULT '{}'",
        "cancelled_at": "TIMESTAMP",
    }
}

COMPUTE_CONTROL_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_privacy_compute_jobs_action_idempotency "
    "ON privacy_compute_jobs (action_idempotency_key)",
)

ENTERPRISE_ACCOUNT_COLUMNS: dict[str, dict[str, str]] = {
    "organizations": {
        "energy_domain": "VARCHAR(24)",
        "profile_json": "JSON NOT NULL DEFAULT '{}'",
    },
    "users": {
        "permissions_json": "JSON NOT NULL DEFAULT '[]'",
        "is_org_owner": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
}

ENTERPRISE_ACCOUNT_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_organizations_energy_domain "
    "ON organizations (energy_domain)",
)


def _callable_source(value: Callable[..., Any]) -> str:
    try:
        return python_inspect.getsource(value)
    except (OSError, TypeError):
        return f"{value.__module__}.{value.__qualname__}"


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    apply: Callable[[Connection], None]
    revision_schema: tuple[str, ...]
    checksum_helpers: tuple[Callable[..., Any], ...] = ()
    accepted_legacy_checksums: tuple[str, ...] = ()

    @property
    def checksum(self) -> str:
        material = [
            self.version,
            self.description,
            *self.revision_schema,
            _callable_source(self.apply),
            *(_callable_source(helper) for helper in self.checksum_helpers),
        ]
        return hashlib.sha256("\n---\n".join(material).encode("utf-8")).hexdigest()

    def accepts(self, recorded_checksum: str) -> bool:
        return recorded_checksum == self.checksum or recorded_checksum in self.accepted_legacy_checksums


def migration_lock_statement(dialect_name: str) -> str | None:
    """Return the transaction-scoped migration lock for a supported dialect."""

    if dialect_name == "postgresql":
        return "SELECT pg_advisory_xact_lock(:migration_lock_id)"
    return None


def _create_revision_tables(
    connection: Connection,
    table_names: Iterable[str],
) -> None:
    """Create only the tables explicitly owned by one revision."""

    requested = set(table_names)
    missing_metadata = requested - set(Base.metadata.tables)
    if missing_metadata:
        raise RuntimeError(
            "migration metadata is missing declared tables: "
            + ", ".join(sorted(missing_metadata))
        )
    for table in Base.metadata.sorted_tables:
        if table.name in requested:
            table.create(bind=connection, checkfirst=True)


def _add_columns(connection: Connection, table_name: str, columns: dict[str, str]) -> None:
    """Add a fixed, repository-owned set of columns to an existing table."""

    inspector = inspect(connection)
    if table_name not in set(inspector.get_table_names()):
        raise RuntimeError(f"migration target table is missing: {table_name}")
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    for column_name, definition in columns.items():
        if column_name not in existing:
            connection.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
            )


def _create_indexes(connection: Connection, statements: Iterable[str]) -> None:
    for statement in statements:
        connection.execute(text(statement))


def _make_nullable(connection: Connection, table_name: str, column_name: str) -> None:
    """Make a legacy FK column nullable without losing existing records.

    PostgreSQL supports this directly. SQLite has no DROP NOT NULL syntax; for
    the legacy tables involved in standalone approvals, rebuild the table from
    the shared metadata while copying every existing column.
    """

    allowed = {
        ("data_contracts", "task_id"),
        ("data_space_agreements", "task_id"),
    }
    if (table_name, column_name) not in allowed:
        raise RuntimeError(f"unsupported nullable migration target: {table_name}.{column_name}")
    inspector = inspect(connection)
    if table_name not in set(inspector.get_table_names()):
        raise RuntimeError(f"migration target table is missing: {table_name}")
    columns = {item["name"]: item for item in inspector.get_columns(table_name)}
    if column_name not in columns or columns[column_name].get("nullable", True):
        return

    if connection.dialect.name == "postgresql":
        connection.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN {column_name} DROP NOT NULL"))
        return
    if connection.dialect.name != "sqlite":
        raise RuntimeError(
            f"nullable migration is not implemented for dialect {connection.dialect.name}"
        )

    table = Base.metadata.tables.get(table_name)
    if table is None:
        raise RuntimeError(f"migration metadata is missing table: {table_name}")
    old_name = f"{table_name}__nullable_migration"
    if old_name in set(inspect(connection).get_table_names()):
        raise RuntimeError(f"stale nullable migration table exists: {old_name}")

    # The migration runner owns one transaction. SQLite's FK toggle is
    # effective before the first DDL statement on this connection and lets us
    # rebuild the parent table without rewriting child FK declarations.
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    # SQLite keeps index names when a table is renamed. Drop the table-owned
    # indexes first so metadata recreation does not collide with those names.
    for index in inspect(connection).get_indexes(table_name):
        connection.exec_driver_sql(f"DROP INDEX IF EXISTS {index['name']}")
    connection.exec_driver_sql(f"ALTER TABLE {table_name} RENAME TO {old_name}")
    table.create(bind=connection, checkfirst=False)
    old_columns = set(columns)
    copy_columns = [column.name for column in table.columns if column.name in old_columns]
    quoted = ", ".join(copy_columns)
    connection.exec_driver_sql(
        f"INSERT INTO {table_name} ({quoted}) SELECT {quoted} FROM {old_name}"
    )
    connection.exec_driver_sql(f"DROP TABLE {old_name}")
    connection.exec_driver_sql("PRAGMA foreign_keys=ON")


def _baseline(connection: Connection) -> None:
    # A frozen table-name set prevents future models from silently becoming
    # part of this historical baseline through repository-wide create_all.
    _create_revision_tables(connection, LEGACY_TABLE_NAMES)


FORMAL_TRUST_COLUMNS: dict[str, dict[str, str]] = {
    "data_uploads": {"ingress_json": "JSON NOT NULL DEFAULT '{}'"},
    "settlement_tasks": {
        "verification_profile_json": "JSON NOT NULL DEFAULT '{}'",
        "request_idempotency_key": "VARCHAR(128)",
        "request_fingerprint": "VARCHAR(128)",
        "ttc_state": "VARCHAR(32) NOT NULL DEFAULT 'INIT'",
        "current_attempt": "INTEGER NOT NULL DEFAULT 0",
        "execution_snapshot_id": "VARCHAR(36)",
        "execution_snapshot_hash": "VARCHAR(128)",
        "state_version": "INTEGER NOT NULL DEFAULT 1",
        "last_transition_at": "TIMESTAMP",
        "archived_at": "TIMESTAMP",
    },
    "data_contracts": {
        "valid_from": "TIMESTAMP",
        "expires_at": "TIMESTAMP",
        "external_negotiation_id": "VARCHAR(128)",
    },
    "privacy_compute_jobs": {
        "privacy_guarantees_json": "JSON NOT NULL DEFAULT '{}'",
        "attempt_id": "VARCHAR(36)",
        "execution_snapshot_id": "VARCHAR(36)",
    },
    "ttc_attempts": {"request_fingerprint": "VARCHAR(128)"},
}

FORMAL_TRUST_INDEXES: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_settlement_tasks_request_idempotency_key "
    "ON settlement_tasks (request_idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_settlement_tasks_ttc_state "
    "ON settlement_tasks (ttc_state)",
    "CREATE INDEX IF NOT EXISTS ix_settlement_tasks_execution_snapshot_id "
    "ON settlement_tasks (execution_snapshot_id)",
    "CREATE INDEX IF NOT EXISTS ix_data_contracts_expires_at "
    "ON data_contracts (expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_data_contracts_external_negotiation_id "
    "ON data_contracts (external_negotiation_id)",
    "CREATE INDEX IF NOT EXISTS ix_privacy_compute_jobs_attempt_id "
    "ON privacy_compute_jobs (attempt_id)",
    "CREATE INDEX IF NOT EXISTS ix_privacy_compute_jobs_execution_snapshot_id "
    "ON privacy_compute_jobs (execution_snapshot_id)",
    "CREATE INDEX IF NOT EXISTS ix_ttc_attempts_request_fingerprint "
    "ON ttc_attempts (request_fingerprint)",
)


def _formal_trust_domain(connection: Connection) -> None:
    _create_revision_tables(connection, FORMAL_TRUST_TABLE_NAMES)
    for table_name, columns in FORMAL_TRUST_COLUMNS.items():
        _add_columns(connection, table_name, columns)
    _create_indexes(connection, FORMAL_TRUST_INDEXES)


AUTHORIZATION_INDEXES: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_data_usage_requests_org_idempotency "
    "ON data_usage_requests (applicant_org_id, idempotency_key)",
    "CREATE INDEX IF NOT EXISTS ix_data_usage_requests_provider_status "
    "ON data_usage_requests (provider_org_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_data_usage_requests_applicant_status "
    "ON data_usage_requests (applicant_org_id, status, created_at)",
)


def _provider_authorization_workflow(connection: Connection) -> None:
    # The nullable legacy FK is required for standalone approvals. Existing
    # settlement rows remain intact and keep their task bindings.
    _make_nullable(connection, "data_contracts", "task_id")
    _make_nullable(connection, "data_space_agreements", "task_id")
    _create_revision_tables(connection, AUTHORIZATION_TABLE_NAMES)
    _create_indexes(connection, AUTHORIZATION_INDEXES)


NEGOTIATION_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_contract_negotiation_contract_created "
    "ON contract_negotiation_events (contract_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_contract_negotiation_agreement_created "
    "ON contract_negotiation_events (agreement_id, created_at)",
)


def _contract_negotiation_events(connection: Connection) -> None:
    _create_revision_tables(connection, NEGOTIATION_TABLE_NAMES)
    _create_indexes(connection, NEGOTIATION_INDEXES)


ASSISTANT_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_assistant_sessions_org_status "
    "ON assistant_sessions (org_id, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_assistant_messages_session_created "
    "ON assistant_messages (session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_assistant_plans_session_status "
    "ON assistant_plans (session_id, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_assistant_steps_plan_status "
    "ON assistant_plan_steps (plan_id, status, updated_at)",
)


def _assistant_sessions_and_plans(connection: Connection) -> None:
    _create_revision_tables(connection, ASSISTANT_TABLE_NAMES)
    _create_indexes(connection, ASSISTANT_INDEXES)


NOTIFICATION_INDEXES: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_notifications_user_dedupe "
    "ON user_notifications (user_id, dedupe_key)",
    "CREATE INDEX IF NOT EXISTS ix_user_notifications_user_read_created "
    "ON user_notifications (user_id, read_at, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_user_notifications_org_type_created "
    "ON user_notifications (org_id, notification_type, created_at)",
)


def _user_notifications(connection: Connection) -> None:
    _create_revision_tables(connection, NOTIFICATION_TABLE_NAMES)
    _create_indexes(connection, NOTIFICATION_INDEXES)


def _revoked_access_tokens(connection: Connection) -> None:
    _create_revision_tables(connection, REVOKED_TOKEN_TABLE_NAMES)


def _privacy_compute_controls(connection: Connection) -> None:
    _add_columns(connection, "privacy_compute_jobs", COMPUTE_CONTROL_COLUMNS["privacy_compute_jobs"])
    _create_indexes(connection, COMPUTE_CONTROL_INDEXES)


def _enterprise_account_scope(connection: Connection) -> None:
    for table_name, columns in ENTERPRISE_ACCOUNT_COLUMNS.items():
        _add_columns(connection, table_name, columns)
    _create_indexes(connection, ENTERPRISE_ACCOUNT_INDEXES)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _parse_legacy_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_naive_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_naive_utc(parsed)


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _revision_json_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _migration_id(kind: str, *parts: Any) -> str:
    value = ":".join(["hiddenchain", "20260820_003", kind, *(str(part) for part in parts)])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


def _assert_formal_uniqueness_is_safe(connection: Connection) -> None:
    duplicate_signature = connection.execute(
        text(
            "SELECT 1 FROM signatures "
            "GROUP BY target_type, target_id, COALESCE(signer_org_id, ''), target_hash "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_signature is not None:
        raise RuntimeError(
            "cannot add confirmation-signature idempotency index: duplicate business signatures exist"
        )

    duplicate_batch = connection.execute(
        text(
            "SELECT 1 FROM evidence_batches "
            "GROUP BY COALESCE(task_id, ''), COALESCE(attempt_id, ''), batch_type "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_batch is not None:
        raise RuntimeError(
            "cannot add evidence-batch idempotency index: duplicate batch scopes exist"
        )


LEGACY_IDEMPOTENCY_INDEXES: tuple[str, ...] = (
    # Keep a distinct name from the ORM UniqueConstraint.  PostgreSQL shares
    # the relation namespace between constraints and indexes; reusing the
    # constraint name would silently skip this NULL-safe expression index.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_signature_business_confirmation_nullsafe "
    "ON signatures (target_type, target_id, COALESCE(signer_org_id, ''), target_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_batch_scope "
    "ON evidence_batches (COALESCE(task_id, ''), COALESCE(attempt_id, ''), batch_type)",
)


def _project_legacy_records(connection: Connection) -> None:
    """Project legacy records without inventing trusted history or evidence."""

    connection.execute(
        text(
            "UPDATE settlement_tasks "
            "SET ttc_state = 'LEGACY_UNMIGRATED', current_attempt = 0, "
            "state_version = CASE WHEN state_version IS NULL OR state_version < 1 "
            "THEN 1 ELSE state_version END "
            "WHERE (ttc_state IS NULL OR ttc_state = 'INIT') "
            "AND NOT EXISTS ("
            "SELECT 1 FROM ttc_attempts "
            "WHERE ttc_attempts.task_id = settlement_tasks.task_id"
            ")"
        )
    )

    contract_table = Base.metadata.tables["data_contracts"]
    contracts = connection.execute(
        select(
            contract_table.c.contract_id,
            contract_table.c.created_at,
            contract_table.c.valid_from,
            contract_table.c.expires_at,
            contract_table.c.policy_json,
        )
    ).mappings()
    for contract in contracts:
        values: dict[str, Any] = {}
        if contract["valid_from"] is None and contract["created_at"] is not None:
            values["valid_from"] = _as_naive_utc(contract["created_at"])
        if contract["expires_at"] is None:
            policy = contract["policy_json"] if isinstance(contract["policy_json"], dict) else {}
            constraints = policy.get("constraint")
            constraints = constraints if isinstance(constraints, dict) else {}
            derived_expiry = _parse_legacy_datetime(constraints.get("expires_at"))
            if derived_expiry is not None:
                values["expires_at"] = derived_expiry
        if values:
            connection.execute(
                update(contract_table)
                .where(contract_table.c.contract_id == contract["contract_id"])
                .values(**values)
            )

    upload_table = Base.metadata.tables["data_uploads"]
    did_table = Base.metadata.tables["did_identities"]
    source_table = Base.metadata.tables["data_sources"]
    asset_table = Base.metadata.tables["data_assets"]
    version_table = Base.metadata.tables["data_asset_versions"]
    passport_table = Base.metadata.tables["data_asset_passports"]
    quality_table = Base.metadata.tables["asset_quality"]

    identities: dict[str, str] = {}
    identity_rows = connection.execute(
        select(
            did_table.c.owner_id,
            did_table.c.did_id,
            did_table.c.owner_type,
            did_table.c.credential_status,
            did_table.c.created_at,
        ).order_by(did_table.c.created_at, did_table.c.did_id)
    ).mappings()
    for identity in identity_rows:
        if identity["owner_type"] == "ORG" and identity["credential_status"] == "VALID":
            identities[str(identity["owner_id"])] = str(identity["did_id"])

    uploads = connection.execute(
        select(upload_table).order_by(upload_table.c.created_at, upload_table.c.upload_id)
    ).mappings()
    now = datetime.now(UTC).replace(tzinfo=None)
    sensitivity_by_type = {
        "GENERATION_DATA": "L4",
        "RETAIL_DATA": "L4",
        "USER_LOAD_CURVE": "L4",
        "VPP_RESOURCE": "L3",
        "RENEWABLE_FORECAST": "L3",
        "GRID_CONSTRAINT": "L4",
    }
    permitted_purposes = ["POWER_SETTLEMENT", "GRID_SECURITY_CHECK", "VPP_AGGREGATION"]
    for upload in uploads:
        owner_org_id = str(upload["owner_org_id"])
        uploaded_at = _parse_legacy_datetime(upload["created_at"]) or now
        ingress = upload["ingress_json"] if isinstance(upload["ingress_json"], dict) else {}
        summary = upload["summary_json"] if isinstance(upload["summary_json"], dict) else {}

        source_code = f"DOMAIN_SOURCE:{owner_org_id}"
        source_id = connection.execute(
            select(source_table.c.source_id).where(source_table.c.source_code == source_code)
        ).scalar_one_or_none()
        if source_id is None:
            source_id = _migration_id("data-source", owner_org_id)
            connection.execute(
                source_table.insert().values(
                    source_id=source_id,
                    source_code=source_code,
                    source_name=f"Controlled source for {owner_org_id}",
                    owner_org_id=owner_org_id,
                    source_type=str(ingress.get("source_type") or "UNSPECIFIED"),
                    connector_type=str(ingress.get("protocol") or "LOCAL_ADAPTER"),
                    endpoint_ref=None,
                    security_domain=f"org:{owner_org_id}",
                    capability_label="DEMO",
                    status="ACTIVE",
                    metadata_json={
                        "transport_encryption": ingress.get("encryption", "NOT_PROVIDED"),
                        "attestation": ingress.get("attestation", "NOT_PROVIDED"),
                        "boundary": "Legacy reference projection; no independent EDC attestation",
                    },
                    created_at=uploaded_at,
                    updated_at=uploaded_at,
                )
            )

        asset_code = f"{upload['asset_type']}:{upload['trade_batch_no']}"
        asset_id = connection.execute(
            select(asset_table.c.asset_id).where(
                asset_table.c.owner_org_id == owner_org_id,
                asset_table.c.asset_code == asset_code,
            )
        ).scalar_one_or_none()
        if asset_id is None:
            asset_id = _migration_id("data-asset", owner_org_id, asset_code)
            connection.execute(
                asset_table.insert().values(
                    asset_id=asset_id,
                    source_id=source_id,
                    owner_org_id=owner_org_id,
                    asset_code=asset_code,
                    asset_name=str(upload["label"]),
                    asset_type=str(upload["asset_type"]),
                    classification="ENERGY_BUSINESS_DATA",
                    sensitivity_level=sensitivity_by_type.get(str(upload["asset_type"]), "L3"),
                    current_version_id=None,
                    status="ACTIVE",
                    metadata_json={
                        "trade_batch_no": upload["trade_batch_no"],
                        "legacy_upload_compatibility": True,
                    },
                    created_at=uploaded_at,
                    updated_at=uploaded_at,
                )
            )

        version_id = connection.execute(
            select(version_table.c.version_id).where(
                version_table.c.asset_id == asset_id,
                version_table.c.data_hash == upload["data_hash"],
            )
        ).scalar_one_or_none()
        if version_id is None:
            version_no = int(
                connection.execute(
                    select(func.max(version_table.c.version_no)).where(
                        version_table.c.asset_id == asset_id
                    )
                ).scalar_one_or_none()
                or 0
            ) + 1
            version_id = _migration_id("data-asset-version", asset_id, upload["data_hash"])
            immutable_payload = {
                "asset_id": asset_id,
                "version_no": version_no,
                "schema_version": upload["schema_version"],
                "data_hash": upload["data_hash"],
                "commitment": upload["commitment"],
                "data_ref_hash": _revision_json_hash({"data_ref": upload["data_ref"]}),
            }
            connection.execute(
                version_table.insert().values(
                    version_id=version_id,
                    asset_id=asset_id,
                    version_no=version_no,
                    schema_version=upload["schema_version"],
                    schema_json={
                        "asset_type": upload["asset_type"],
                        "schema_version": upload["schema_version"],
                        "raw_payload_in_registry": False,
                    },
                    data_ref=upload["data_ref"],
                    data_hash=upload["data_hash"],
                    commitment=upload["commitment"],
                    record_count=_safe_int(summary.get("record_count")),
                    effective_from=None,
                    effective_until=None,
                    immutable_hash=_revision_json_hash(immutable_payload),
                    status="ACTIVE",
                    created_at=uploaded_at,
                )
            )

        connection.execute(
            update(asset_table)
            .where(asset_table.c.asset_id == asset_id)
            .values(current_version_id=version_id, updated_at=uploaded_at)
        )

        owner_did = identities.get(owner_org_id, f"did:hiddenchain:org:{owner_org_id}")
        passport_exists = connection.execute(
            select(passport_table.c.passport_id).where(
                passport_table.c.asset_version_id == version_id,
                passport_table.c.passport_version == 1,
            )
        ).scalar_one_or_none()
        if passport_exists is None:
            passport_payload = {
                "asset_version_id": version_id,
                "owner_did": owner_did,
                "classification": "ENERGY_BUSINESS_DATA",
                "sensitivity_level": sensitivity_by_type.get(str(upload["asset_type"]), "L3"),
                "data_hash": upload["data_hash"],
                "commitment": upload["commitment"],
                "permitted_purposes": permitted_purposes,
            }
            connection.execute(
                passport_table.insert().values(
                    passport_id=_migration_id("asset-passport", version_id),
                    asset_version_id=version_id,
                    passport_version=1,
                    owner_did=owner_did,
                    provenance_json={
                        "source_id": source_id,
                        "legacy_upload_id": upload["upload_id"],
                        "data_hash": upload["data_hash"],
                        "commitment": upload["commitment"],
                    },
                    classification_json={
                        "classification": "ENERGY_BUSINESS_DATA",
                        "sensitivity_level": sensitivity_by_type.get(
                            str(upload["asset_type"]), "L3"
                        ),
                    },
                    permitted_use_json={
                        "output_mode": "AGGREGATE_ONLY",
                        "raw_data_export": False,
                        "purposes": permitted_purposes,
                    },
                    policy_refs_json=[],
                    evidence_refs_json=[],
                    passport_hash=_revision_json_hash(passport_payload),
                    status="ACTIVE",
                    issued_at=uploaded_at,
                )
            )

        quality_exists = connection.execute(
            select(quality_table.c.quality_id).where(
                quality_table.c.asset_version_id == version_id
            )
        ).scalar_one_or_none()
        if quality_exists is None:
            quality_payload = {
                "asset_version_id": version_id,
                "validation_status": upload["validation_status"],
                "record_count": _safe_int(summary.get("record_count")),
                "trusted_acquisition": bool(ingress),
            }
            connection.execute(
                quality_table.insert().values(
                    quality_id=_migration_id("asset-quality", version_id),
                    asset_version_id=version_id,
                    profile_version="ASSET_QUALITY_V1",
                    metrics_json=quality_payload,
                    decision=(
                        "PASSED" if upload["validation_status"] == "PASSED" else "REJECTED"
                    ),
                    quality_hash=_revision_json_hash(quality_payload),
                    evidence_refs_json=[],
                    evaluated_by_did=owner_did,
                    evaluated_at=uploaded_at,
                )
            )

    _assert_formal_uniqueness_is_safe(connection)
    _create_indexes(connection, LEGACY_IDEMPOTENCY_INDEXES)


ATTEMPT_BOUND_OUTCOME_COLUMNS: dict[str, dict[str, str]] = {
    "settlement_results": {"attempt_id": "VARCHAR(36)"},
    "audit_reports": {"attempt_id": "VARCHAR(36)"},
}

ATTEMPT_BOUND_OUTCOME_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_settlement_results_attempt_id "
    "ON settlement_results (attempt_id)",
    "CREATE INDEX IF NOT EXISTS ix_audit_reports_attempt_id "
    "ON audit_reports (attempt_id)",
)


def _bind_outcomes_to_attempt_schema(connection: Connection) -> None:
    """Add nullable bindings without inventing an Attempt for legacy facts."""

    for table_name, columns in ATTEMPT_BOUND_OUTCOME_COLUMNS.items():
        _add_columns(connection, table_name, columns)
    _create_indexes(connection, ATTEMPT_BOUND_OUTCOME_INDEXES)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        "20260820_001",
        "record explicit legacy SQLAlchemy schema baseline",
        _baseline,
        revision_schema=tuple(f"table:{name}" for name in sorted(LEGACY_TABLE_NAMES)),
        checksum_helpers=(_create_revision_tables,),
        accepted_legacy_checksums=(
            "79ba6159a49945043885ff18b7e6537c5e5f34e328214f7510f1da127dd8da8f",
        ),
    ),
    Migration(
        "20260820_002",
        "add formal trust domain, TTC compatibility fields, and execution references",
        _formal_trust_domain,
        revision_schema=(
            *(f"table:{name}" for name in sorted(FORMAL_TRUST_TABLE_NAMES)),
            *(
                f"column:{table_name}.{column_name}:{definition}"
                for table_name, columns in sorted(FORMAL_TRUST_COLUMNS.items())
                for column_name, definition in sorted(columns.items())
            ),
            *(f"index:{statement}" for statement in FORMAL_TRUST_INDEXES),
        ),
        checksum_helpers=(_create_revision_tables, _add_columns, _create_indexes),
        accepted_legacy_checksums=(
            "c9bb9c41c1c06872c1f6a3f84a79cfa66cfebc49fc284652b42afbe72b462bda",
        ),
    ),
    Migration(
        "20260820_003",
        "truth-preserving legacy projection and formal idempotency indexes",
        _project_legacy_records,
        revision_schema=(
            "settlement_tasks:no-attempt->LEGACY_UNMIGRATED",
            "data_contracts:valid_from<-created_at",
            "data_contracts:expires_at<-policy_json.constraint.expires_at-if-ISO8601",
            "data_uploads:reference-only-asset-passport-quality-projection-v1",
            *(f"index:{statement}" for statement in LEGACY_IDEMPOTENCY_INDEXES),
        ),
        checksum_helpers=(
            _as_naive_utc,
            _parse_legacy_datetime,
            _safe_int,
            _revision_json_hash,
            _migration_id,
            _assert_formal_uniqueness_is_safe,
            _create_indexes,
        ),
    ),
    Migration(
        "20260820_004",
        "bind settlement results and audit reports to TTC attempts",
        _bind_outcomes_to_attempt_schema,
        revision_schema=(
            *(
                f"column:{table_name}.{column_name}:{definition}"
                for table_name, columns in sorted(ATTEMPT_BOUND_OUTCOME_COLUMNS.items())
                for column_name, definition in sorted(columns.items())
            ),
            *(f"index:{statement}" for statement in ATTEMPT_BOUND_OUTCOME_INDEXES),
            "legacy-outcomes:attempt_id-remains-null",
        ),
        checksum_helpers=(_add_columns, _create_indexes),
    ),
    Migration(
        "20260821_001",
        "add provider-governed data usage requests and standalone authorization bindings",
        _provider_authorization_workflow,
        revision_schema=(
            *(f"table:{name}" for name in sorted(AUTHORIZATION_TABLE_NAMES)),
            "nullable:data_contracts.task_id",
            "nullable:data_space_agreements.task_id",
            *(f"index:{statement}" for statement in AUTHORIZATION_INDEXES),
        ),
        checksum_helpers=(
            _make_nullable,
            _create_revision_tables,
            _create_indexes,
        ),
    ),
    Migration(
        "20260821_002",
        "add append-only contract negotiation events",
        _contract_negotiation_events,
        revision_schema=(
            *(f"table:{name}" for name in sorted(NEGOTIATION_TABLE_NAMES)),
            *(f"index:{statement}" for statement in NEGOTIATION_INDEXES),
        ),
        checksum_helpers=(_create_revision_tables, _create_indexes),
    ),
    Migration(
        "20260821_003",
        "add scoped Trusted Space assistant sessions and deterministic plans",
        _assistant_sessions_and_plans,
        revision_schema=(
            *(f"table:{name}" for name in sorted(ASSISTANT_TABLE_NAMES)),
            *(f"index:{statement}" for statement in ASSISTANT_INDEXES),
        ),
        checksum_helpers=(_create_revision_tables, _create_indexes),
    ),
    Migration(
        "20260821_004",
        "add scoped deduplicated user notifications",
        _user_notifications,
        revision_schema=(
            *(f"table:{name}" for name in sorted(NOTIFICATION_TABLE_NAMES)),
            *(f"index:{statement}" for statement in NOTIFICATION_INDEXES),
        ),
        checksum_helpers=(_create_revision_tables, _create_indexes),
    ),
    Migration(
        "20260821_005",
        "add truthful privacy computation cancel and idempotent action controls",
        _privacy_compute_controls,
        revision_schema=(
            *(
                f"column:{table_name}.{column_name}:{definition}"
                for table_name, columns in sorted(COMPUTE_CONTROL_COLUMNS.items())
                for column_name, definition in sorted(columns.items())
            ),
            *(f"index:{statement}" for statement in COMPUTE_CONTROL_INDEXES),
            "retry:blocked-until-real-requeue-executor",
        ),
        checksum_helpers=(_add_columns, _create_indexes),
    ),
    Migration(
        "20260823_001",
        "add enterprise energy scope and delegated account permissions",
        _enterprise_account_scope,
        revision_schema=(
            *(
                f"column:{table_name}.{column_name}:{definition}"
                for table_name, columns in sorted(ENTERPRISE_ACCOUNT_COLUMNS.items())
                for column_name, definition in sorted(columns.items())
            ),
            *(f"index:{statement}" for statement in ENTERPRISE_ACCOUNT_INDEXES),
        ),
        checksum_helpers=(_add_columns, _create_indexes),
    ),
    Migration(
        "20260824_001",
        "add immediate access token revocation records",
        _revoked_access_tokens,
        revision_schema=tuple(f"table:{name}" for name in sorted(REVOKED_TOKEN_TABLE_NAMES)),
        checksum_helpers=(_create_revision_tables,),
    ),
)


def _validate_applied_migrations(applied: dict[str, str]) -> None:
    known = {migration.version: migration for migration in MIGRATIONS}
    unknown = sorted(set(applied) - set(known))
    if unknown:
        raise RuntimeError(
            "database contains migration versions unknown to this application: "
            + ", ".join(unknown)
        )
    for version, recorded_checksum in applied.items():
        if not known[version].accepts(recorded_checksum):
            raise RuntimeError(f"applied migration checksum mismatch: {version}")


def apply_migrations(engine: Engine) -> list[str]:
    """Apply pending migrations under a database-scoped lock."""

    applied_now: list[str] = []
    with engine.begin() as connection:
        lock_statement = migration_lock_statement(connection.dialect.name)
        if lock_statement is not None:
            connection.execute(
                text(lock_statement),
                {"migration_lock_id": POSTGRES_MIGRATION_LOCK_ID},
            )
        MIGRATION_METADATA.create_all(bind=connection)
        rows = connection.execute(
            select(
                SCHEMA_MIGRATIONS.c.version,
                SCHEMA_MIGRATIONS.c.checksum,
            )
        ).all()
        applied = {row.version: row.checksum for row in rows}
        _validate_applied_migrations(applied)
        for migration in MIGRATIONS:
            if migration.version in applied:
                continue
            migration.apply(connection)
            connection.execute(
                SCHEMA_MIGRATIONS.insert().values(
                    version=migration.version,
                    description=migration.description,
                    checksum=migration.checksum,
                    applied_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            applied_now.append(migration.version)
    return applied_now


def migration_status(engine: Engine) -> dict[str, object]:
    """Return a readiness-safe view without exposing connection data."""

    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            if SCHEMA_MIGRATIONS.name not in tables:
                return {
                    "status": "NOT_APPLIED",
                    "current": None,
                    "pending": [item.version for item in MIGRATIONS],
                }
            rows = connection.execute(
                select(
                    SCHEMA_MIGRATIONS.c.version,
                    SCHEMA_MIGRATIONS.c.checksum,
                )
            ).all()
            applied = {row.version: row.checksum for row in rows}
            _validate_applied_migrations(applied)
    except RuntimeError as exc:
        message = str(exc)
        error_code = (
            "UNKNOWN_MIGRATION_VERSION"
            if "unknown to this application" in message
            else "MIGRATION_CHECKSUM_MISMATCH"
        )
        return {
            "status": "INCOMPATIBLE",
            "current": None,
            "pending": [],
            "error_code": error_code,
        }
    except Exception:
        return {
            "status": "UNAVAILABLE",
            "current": None,
            "pending": [],
            "error_code": "DATABASE_UNAVAILABLE",
        }
    pending = [item.version for item in MIGRATIONS if item.version not in applied]
    return {
        "status": "READY" if not pending else "PENDING",
        "current": max(applied) if applied else None,
        "pending": pending,
    }
