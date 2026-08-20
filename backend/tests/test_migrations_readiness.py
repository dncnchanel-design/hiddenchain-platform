from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

import app.main as main_module
from app.config import settings
from app.database import SessionLocal
from app.migrations import (
    FORMAL_TRUST_TABLE_NAMES,
    LEGACY_TABLE_NAMES,
    MIGRATIONS,
    SCHEMA_MIGRATIONS,
    Migration,
    apply_migrations,
    migration_lock_statement,
    migration_status,
)
from app.models import DidIdentity
from app.services.tool_catalog import agent_tool_catalog_readiness
from app.trust_models import (
    AssetQuality,
    DataAsset,
    DataAssetPassport,
    DataAssetVersion,
    DataSource,
    TtcAttempt,
)


def _sqlite_engine(tmp_path, name: str):
    return create_engine(
        f"sqlite:///{(tmp_path / name).as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )


def test_fresh_sqlite_migrations_are_complete_idempotent_and_enforce_foreign_keys(
    tmp_path,
) -> None:
    isolated = _sqlite_engine(tmp_path, "fresh.db")
    try:
        assert apply_migrations(isolated) == [item.version for item in MIGRATIONS]
        assert apply_migrations(isolated) == []
        assert migration_status(isolated)["status"] == "READY"
        tables = set(inspect(isolated).get_table_names())
        assert LEGACY_TABLE_NAMES | FORMAL_TRUST_TABLE_NAMES | {"schema_migrations"} <= tables
        with isolated.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            signature_indexes = {
                row[1] for row in connection.execute(text("PRAGMA index_list('signatures')"))
            }
            batch_indexes = {
                row[1] for row in connection.execute(text("PRAGMA index_list('evidence_batches')"))
            }
        assert "uq_signature_business_confirmation_nullsafe" in signature_indexes
        assert "uq_evidence_batch_scope" in batch_indexes

        with pytest.raises(IntegrityError), isolated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO signatures "
                    "(signature_id, signer_org_id, signer_did, target_type, target_id, "
                    "target_hash, signature_value, verify_status, created_at, updated_at) "
                    "VALUES ('sig-a', NULL, 'did:test', 'RESULT', 'r-1', 'hash-1', "
                    "'signed', 'VALID', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "('sig-b', NULL, 'did:test', 'RESULT', 'r-1', 'hash-1', "
                    "'signed', 'VALID', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        with pytest.raises(IntegrityError), isolated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO evidence_batches "
                    "(batch_id, task_id, attempt_id, batch_type, merkle_algorithm, "
                    "merkle_root, leaf_count, status, sealed_by_did, sealed_at) "
                    "VALUES ('batch-a', NULL, NULL, 'FINAL', 'SHA256', 'root-a', 1, "
                    "'SEALED', 'did:test', CURRENT_TIMESTAMP), "
                    "('batch-b', NULL, NULL, 'FINAL', 'SHA256', 'root-b', 1, "
                    "'SEALED', 'did:test', CURRENT_TIMESTAMP)"
                )
            )
    finally:
        isolated.dispose()


def test_legacy_sqlite_upgrade_marks_truth_boundary_projects_assets_and_backfills_contract(
    tmp_path,
) -> None:
    isolated = _sqlite_engine(tmp_path, "legacy.db")
    with isolated.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE organizations (
                org_id VARCHAR(36) PRIMARY KEY,
                org_type VARCHAR(32) NOT NULL,
                org_name VARCHAR(128) NOT NULL,
                credit_code VARCHAR(64),
                status VARCHAR(24) NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE data_uploads (
                upload_id VARCHAR(36) PRIMARY KEY,
                asset_type VARCHAR(40) NOT NULL,
                owner_org_id VARCHAR(36) NOT NULL,
                trade_batch_no VARCHAR(64) NOT NULL,
                task_id VARCHAR(36),
                label VARCHAR(128) NOT NULL,
                data_ref VARCHAR(255) NOT NULL,
                data_hash VARCHAR(128) NOT NULL,
                commitment VARCHAR(128) NOT NULL,
                schema_version VARCHAR(32) NOT NULL,
                validation_status VARCHAR(32) NOT NULL,
                signature_value TEXT,
                summary_json JSON NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE settlement_tasks (
                task_id VARCHAR(36) PRIMARY KEY,
                capsule_id VARCHAR(64) NOT NULL UNIQUE,
                task_name VARCHAR(128) NOT NULL,
                trade_batch_no VARCHAR(64) NOT NULL,
                period_start DATE NOT NULL,
                period_end DATE NOT NULL,
                rule_id VARCHAR(36) NOT NULL,
                creator_org_id VARCHAR(36) NOT NULL,
                status VARCHAR(32) NOT NULL,
                risk_level VARCHAR(16) NOT NULL,
                current_stage VARCHAR(64) NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE data_contracts (
                contract_id VARCHAR(36) PRIMARY KEY,
                task_id VARCHAR(36) NOT NULL,
                provider_org_id VARCHAR(36) NOT NULL,
                consumer_type VARCHAR(32) NOT NULL,
                purpose VARCHAR(64) NOT NULL,
                data_refs_json JSON NOT NULL,
                policy_json JSON NOT NULL,
                policy_hash VARCHAR(128) NOT NULL,
                status VARCHAR(24) NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE settlement_results (
                result_id VARCHAR(36) PRIMARY KEY,
                task_id VARCHAR(36) NOT NULL,
                org_id VARCHAR(36),
                result_scope VARCHAR(24) NOT NULL,
                result_json JSON NOT NULL,
                result_hash VARCHAR(128) NOT NULL,
                confirm_status VARCHAR(32) NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE audit_reports (
                report_id VARCHAR(36) PRIMARY KEY,
                task_id VARCHAR(36) NOT NULL,
                template_code VARCHAR(48) NOT NULL,
                report_title VARCHAR(160) NOT NULL,
                report_content TEXT NOT NULL,
                report_hash VARCHAR(128) NOT NULL,
                risk_level VARCHAR(16) NOT NULL,
                evidence_refs_json JSON NOT NULL,
                status VARCHAR(24) NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        now = "2026-01-01 00:00:00"
        connection.execute(
            text(
                "INSERT INTO organizations VALUES "
                "('legacy-org', 'GENERATOR', 'Legacy Org', 'legacy-credit', 'ACTIVE', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO data_uploads VALUES ("
                "'legacy-upload', 'GENERATION_DATA', 'legacy-org', 'TB-LEGACY-001', NULL, "
                "'Legacy generation', 'vault://legacy-org/legacy-upload', 'data-hash', "
                "'commitment', 'v1.0', 'PASSED', 'signature', :summary, :now, :now)"
            ),
            {"summary": '{"record_count":2}', "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO settlement_tasks VALUES ("
                "'legacy-task', 'legacy-capsule', 'Legacy task', 'TB-LEGACY-001', "
                "'2026-01-01', '2026-01-31', 'legacy-rule', 'legacy-org', "
                "'AUDITED', 'LOW', 'done', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO data_contracts VALUES ("
                "'legacy-contract', 'legacy-task', 'legacy-org', 'legacy-consumer', "
                "'POWER_SETTLEMENT', :refs, :policy, 'policy-hash', 'ACTIVE', :now, :now)"
            ),
            {
                "refs": '["vault://legacy-org/legacy-upload"]',
                "policy": '{"constraint":{"expires_at":"2026-02-01T00:00:00Z"}}',
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO settlement_results VALUES ("
                "'legacy-result', 'legacy-task', NULL, 'SUMMARY', '{}', "
                "'legacy-result-hash', 'NOT_REQUIRED', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO audit_reports VALUES ("
                "'legacy-report', 'legacy-task', 'LEGACY', 'Legacy report', "
                "'legacy content', 'legacy-report-hash', 'LOW', '[]', "
                "'APPROVED', :now, :now)"
            ),
            {"now": now},
        )

    try:
        assert apply_migrations(isolated) == [item.version for item in MIGRATIONS]
        with isolated.connect() as connection:
            state = connection.execute(
                text("SELECT ttc_state FROM settlement_tasks WHERE task_id='legacy-task'")
            ).scalar_one()
            assert state == "LEGACY_UNMIGRATED"
            assert connection.execute(select(func.count(TtcAttempt.attempt_id))).scalar_one() == 0
            assert connection.execute(select(func.count(DataSource.source_id))).scalar_one() == 1
            assert connection.execute(select(func.count(DataAsset.asset_id))).scalar_one() == 1
            assert connection.execute(select(func.count(DataAssetVersion.version_id))).scalar_one() == 1
            assert connection.execute(select(func.count(DataAssetPassport.passport_id))).scalar_one() == 1
            assert connection.execute(select(func.count(AssetQuality.quality_id))).scalar_one() == 1
            contract = connection.execute(
                text(
                    "SELECT valid_from, expires_at FROM data_contracts "
                    "WHERE contract_id='legacy-contract'"
                )
            ).one()
            assert str(contract.valid_from).startswith("2026-01-01")
            assert str(contract.expires_at).startswith("2026-02-01")
            legacy_outcome_bindings = connection.execute(
                text(
                    "SELECT "
                    "(SELECT attempt_id FROM settlement_results WHERE result_id='legacy-result'), "
                    "(SELECT attempt_id FROM audit_reports WHERE report_id='legacy-report')"
                )
            ).one()
            assert legacy_outcome_bindings == (None, None)
        assert apply_migrations(isolated) == []
    finally:
        isolated.dispose()


def test_unknown_and_mismatched_migration_ledgers_fail_closed(tmp_path) -> None:
    isolated = _sqlite_engine(tmp_path, "unknown.db")
    try:
        apply_migrations(isolated)
        with isolated.begin() as connection:
            connection.execute(
                SCHEMA_MIGRATIONS.insert().values(
                    version="20990101_999",
                    description="future revision",
                    checksum="f" * 64,
                    applied_at=datetime(2099, 1, 1),
                )
            )
        with pytest.raises(RuntimeError, match="unknown to this application"):
            apply_migrations(isolated)
        status_payload = migration_status(isolated)
        assert status_payload["status"] == "INCOMPATIBLE"
        assert status_payload["error_code"] == "UNKNOWN_MIGRATION_VERSION"

        with isolated.begin() as connection:
            connection.execute(
                SCHEMA_MIGRATIONS.delete().where(
                    SCHEMA_MIGRATIONS.c.version == "20990101_999"
                )
            )
            connection.execute(
                update(SCHEMA_MIGRATIONS)
                .where(SCHEMA_MIGRATIONS.c.version == MIGRATIONS[-1].version)
                .values(checksum="0" * 64)
            )
        with pytest.raises(RuntimeError, match="checksum mismatch"):
            apply_migrations(isolated)
        assert migration_status(isolated)["error_code"] == "MIGRATION_CHECKSUM_MISMATCH"
    finally:
        isolated.dispose()


def test_revision_schema_and_helpers_participate_in_checksum() -> None:
    def no_op(_connection) -> None:
        return None

    def helper_one() -> str:
        return "one"

    def helper_two() -> str:
        return "two"

    first = Migration("v1", "test", no_op, ("schema:a",), (helper_one,))
    changed_schema = Migration("v1", "test", no_op, ("schema:b",), (helper_one,))
    changed_helper = Migration("v1", "test", no_op, ("schema:a",), (helper_two,))
    assert len({first.checksum, changed_schema.checksum, changed_helper.checksum}) == 3
    assert migration_lock_statement("postgresql") == (
        "SELECT pg_advisory_xact_lock(:migration_lock_id)"
    )
    assert migration_lock_statement("sqlite") is None


def test_agent_catalog_readiness_fails_closed_on_revoked_agent() -> None:
    with SessionLocal() as db:
        assert agent_tool_catalog_readiness(db)["status"] == "READY"
        identity = db.get(DidIdentity, "did:hiddenchain:agent:orchestrator")
        assert identity is not None
        identity.credential_status = "REVOKED"
        db.flush()
        payload = agent_tool_catalog_readiness(db)
        assert payload["status"] == "NOT_READY"
        assert "AGENT_DID_INVALID:ORCHESTRATOR" in payload["issues"]


def test_production_policy_readiness_probes_remote_and_fails_closed(monkeypatch) -> None:
    production = replace(
        settings,
        app_env="production",
        opa_url="https://opa.example.invalid",
        opa_local_fallback=False,
    )

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(main_module.httpx, "get", unavailable)
    blocked = main_module.policy_decision_point_readiness(production)
    assert blocked["status"] == "NOT_READY"
    assert blocked["remote_status"] == "UNAVAILABLE"
    assert blocked["error_code"] == "OPA_UNAVAILABLE"

    class HealthyResponse:
        @staticmethod
        def raise_for_status() -> None:
            return None

    monkeypatch.setattr(main_module.httpx, "get", lambda *_args, **_kwargs: HealthyResponse())
    ready = main_module.policy_decision_point_readiness(production)
    assert ready["status"] == "READY"
    assert ready["mode"] == "REMOTE_OPA"


def test_nonproduction_policy_readiness_labels_local_fallback() -> None:
    development = replace(
        settings,
        app_env="development",
        opa_url="",
        opa_local_fallback=True,
    )
    payload = main_module.policy_decision_point_readiness(development)
    assert payload["status"] == "READY"
    assert payload["mode"] == "LOCAL_FALLBACK"
    assert payload["remote_status"] == "NOT_CONFIGURED"
