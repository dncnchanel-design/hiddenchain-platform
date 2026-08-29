from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, parse_subject_map, public_branding, validate_runtime_settings
from app import main as main_module
from app.database import SessionLocal
from app.models import (
    Base,
    DataRequestBatch,
    DataRequestItem,
    DataUsageRequest,
    DidIdentity,
    ExecutionReceipt,
    LocalSubjectNode,
    PrivacyComputeJob,
    TrustedQueryTask,
    User,
    utc_now,
)
from app.production import assert_production_database_clean
from app.security import canonical_json, sha256_json
from app.services import local_data_boundary
from app.services.privacy_attestation import (
    canonical_connector_request_payload,
    verify_signed_connector_non_export,
)
from app.services.trusted_query_results import (
    TrustedQueryProjectionError,
    build_trusted_query_public_result,
)
from app.trust_models import AgentTool, DataAsset, DataAssetVersion


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def production_settings(**changes) -> Settings:
    base = Settings(
        app_env="production",
        test_fixture_seed=False,
        demo_catalog_seed=False,
        demo_business_seed=False,
        test_compute_delay_ms=0,
        opa_local_fallback=False,
        jwt_secret="production-jwt-secret-value-00000001",
        signing_secret="production-signing-secret-value-0002",
        opa_url="https://policy.example.com",
        cors_origins=("https://settlement.example.com",),
        environment_name="",
        platform_signing_private_key=base64.b64encode(b"p" * 32).decode(),
        subject_node_endpoints_json=(
            '{"org-generator":"https://generator.example.com"}'
        ),
        subject_node_ids_json='{"org-generator":"connector-org-generator"}',
        subject_node_public_keys_json=(
            '{"org-generator":"'
            + base64.b64encode(b"c" * 32).decode()
            + '"}'
        ),
    )
    return replace(base, **changes)


@contextmanager
def production_database_with_trusted_query_record():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # The isolated fixture includes the complete authorization/asset/request
    # chain so the restart guard verifies the same bindings as online writes.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    task_id = "prod-query-task-001"
    provider_org_id = "org-provider-prod"
    applicant_org_id = "org-applicant-prod"
    applicant_user_id = "prod-user-001"
    authorization_id = "prod-authorization-001"
    request_item_id = "prod-request-item-001"
    job_id = "prod-query-job-001"
    node_code = "prod-provider-node-001"
    task_payload = {
        "authorization_id": authorization_id,
        "provider_org_id": provider_org_id,
        "function": "sum",
        "energy_domain": "electricity",
        "resource": "generation",
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "region": None,
        "hour": None,
        "threshold": None,
        "group_by": None,
        "decimals": 2,
    }
    dataset_local_ref = "connector://prod-provider-node-001/generation/versions/1"
    dataset_content_hash = "9" * 64
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode()
    signing_key_fingerprint = hashlib.sha256(
        base64.b64decode(public_key, validate=True)
    ).hexdigest()
    connector_payload = canonical_connector_request_payload(
        {
            "task_id": task_id,
            "authorization_id": authorization_id,
            "request_item_id": request_item_id,
            "provider_org_id": provider_org_id,
            "rule_version": "v1",
            "dataset_version": 1,
            "dataset_local_ref": dataset_local_ref,
            "dataset_content_hash": dataset_content_hash,
            "resource": task_payload["resource"],
            "function": task_payload["function"],
            "start_date": task_payload["start_date"],
            "end_date": task_payload["end_date"],
            "region": task_payload["region"],
            "hour": task_payload["hour"],
            "threshold": task_payload["threshold"],
            "group_by": task_payload["group_by"],
            "decimals": task_payload["decimals"],
        }
    )
    request_hash = sha256_json(connector_payload)
    occurred_at = datetime.now(UTC).isoformat()
    signed_result = {
        "task_id": task_id,
        "authorization_id": authorization_id,
        "request_item_id": request_item_id,
        "provider_org_id": provider_org_id,
        "rule_version": "v1",
        "connector_id": node_code,
        "energy_domain": "electricity",
        "generated_at": occurred_at,
        "result": 42.0,
        "unit": "MWh",
        "record_count": 2,
        "dataset_version": 1,
        "dataset_local_ref": dataset_local_ref,
        "dataset_content_hash": dataset_content_hash,
        "trend": [],
        "resource_name": "生产侧发电量",
        "function_name": "求和",
        "raw_records_returned": False,
        "privacy": {
            "raw_records_returned": False,
            "raw_data_exported": False,
            "non_export_attestation": {
                "status": "SIGNED",
                "issuer": node_code,
                "boundary": "CONNECTOR_LOCAL_DATA",
                "request_hash": request_hash,
                "result_scope": "AGGREGATE_ONLY",
                "raw_data_exported": False,
            },
        },
        "privacy_verification": {
            "mode": "SIGNED_CONNECTOR_NON_EXPORT",
            "request_hash": request_hash,
            "result_scope": "AGGREGATE_ONLY",
            "raw_data_exported": False,
        },
        "capability": "本地受控计算",
    }
    previous_hash = "0" * 64
    audit_event = {
        "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "connector_id": node_code,
        "organization_id": provider_org_id,
        "energy_domain": "electricity",
        "task_id": task_id,
        "request_item_id": request_item_id,
        "provider_org_id": provider_org_id,
        "authorization_id": authorization_id,
        "request_hash": request_hash,
        "result_payload_hash": sha256_json(signed_result),
        "record_count": 2,
        "dataset_version": 1,
        "dataset_local_ref": signed_result["dataset_local_ref"],
        "dataset_content_hash": signed_result["dataset_content_hash"],
        "raw_records_returned": False,
        "raw_data_exported": False,
        "occurred_at": occurred_at,
    }
    audit_hash = hashlib.sha256(
        (previous_hash + canonical_json(audit_event)).encode()
    ).hexdigest()
    signed_result.update(
        {
            "audit_sequence": 1,
            "previous_audit_hash": previous_hash,
            "audit_hash": audit_hash,
            "audit_event": audit_event,
        }
    )
    result_hash = sha256_json(signed_result)
    node_signature = base64.b64encode(
        private_key.sign(canonical_json(signed_result).encode())
    ).decode()
    connector_audit = {
        "status": "VERIFIED",
        "action": "LOCAL_CONTROLLED_RESULT_ISSUED",
        "connector_id": node_code,
        "organization_id": provider_org_id,
        "energy_domain": "electricity",
        "sequence": 1,
        "previous_hash": previous_hash,
        "audit_hash": audit_hash,
        "pointer_verified": True,
        "event_hash_verified": True,
        "verification_scope": "SINGLE_SIGNED_EVENT_POINTER",
        "connector_declared_at": occurred_at,
        "platform_received_at": occurred_at,
    }
    privacy_verification = {
        **verify_signed_connector_non_export(signed_result, connector_payload),
        "result_hash": result_hash,
        "connector_audit": connector_audit,
    }
    public_result = {
        "task_id": task_id,
        "job_id": job_id,
        "request_item_id": request_item_id,
        "authorization_scope": authorization_id,
        "raw_records_returned": False,
        "connector_audit": connector_audit,
        "generated_at": signed_result["generated_at"],
        "result": signed_result["result"],
        "unit": signed_result["unit"],
        "record_count": signed_result["record_count"],
        "trend": signed_result["trend"],
        "resource_name": signed_result["resource_name"],
        "function_name": signed_result["function_name"],
        "digital_signature": "已验证",
        "audit_recorded": True,
        "capability": "本地受控计算",
        "privacy_verification": privacy_verification,
        "idempotent_replay": False,
        "asset_version_id": "prod-asset-version-001",
        "dataset_version": signed_result["dataset_version"],
        "dataset_local_ref": signed_result["dataset_local_ref"],
        "dataset_content_hash": signed_result["dataset_content_hash"],
        "verification_status": "CURRENT_SIGNATURE_VERIFIED",
        "receipt_verification_schema": "TRUSTED_QUERY_RECEIPT_V2",
    }
    guard_settings = production_settings(
        subject_node_endpoints_json=(
            '{"org-provider-prod":"https://provider.example.com"}'
        ),
        subject_node_ids_json=(
            '{"org-provider-prod":"prod-provider-node-001"}'
        ),
        subject_node_public_keys_json=(
            '{"org-provider-prod":"' + public_key + '"}'
        ),
    )
    try:
        with Session(engine) as db:
            db.add(
                User(
                    user_id=applicant_user_id,
                    org_id=applicant_org_id,
                    username="production-applicant",
                    password_hash="not-used-by-guard",
                    display_name="Production Applicant",
                    role_code="EXCHANGE",
                    permissions_json=["CREATE_COMPUTE_TASK", "VIEW_COMPUTE_RESULT"],
                    is_org_owner=False,
                    status="ACTIVE",
                )
            )
            db.add(
                DataAsset(
                    asset_id="prod-asset-001",
                    source_id="prod-source-001",
                    owner_org_id=provider_org_id,
                    asset_code="PROD_GENERATION",
                    asset_name="生产侧发电量",
                    asset_type="ELECTRICITY_METRIC",
                    classification="ENTERPRISE_DATA_PRODUCT",
                    sensitivity_level="L2",
                    current_version_id="prod-asset-version-001",
                    status="ACTIVE",
                    metadata_json={"domain": "electricity", "resource_id": "generation"},
                )
            )
            db.add(
                DataAssetVersion(
                    version_id="prod-asset-version-001",
                    asset_id="prod-asset-001",
                    version_no=1,
                    schema_version="connector-csv-v1",
                    schema_json={"fields": ["record_date", "value"]},
                    data_ref=dataset_local_ref,
                    data_hash=dataset_content_hash,
                    record_count=2,
                    immutable_hash="8" * 64,
                    status="ACTIVE",
                )
            )
            db.add(
                DataUsageRequest(
                    request_id=authorization_id,
                    asset_id="prod-asset-001",
                    asset_version_id="prod-asset-version-001",
                    applicant_user_id=applicant_user_id,
                    applicant_org_id=applicant_org_id,
                    provider_org_id=provider_org_id,
                    applicant_did="did:example:applicant",
                    provider_did="did:example:provider",
                    purpose="CONTROLLED_AGGREGATE_QUERY",
                    usage_mode="AGGREGATE_ONLY",
                    requested_scope_json={"raw_data_export": False},
                    requested_fields_json=["generation", "SUM"],
                    terms_json={"raw_data_export": False},
                    duration_days=1,
                    expires_at=utc_now() + timedelta(days=1),
                    status="APPROVED",
                    state_version=1,
                    request_fingerprint="7" * 64,
                    submitted_at=utc_now(),
                    decided_at=utc_now(),
                    trace_id="prod-trace-001",
                )
            )
            db.add(
                DataRequestBatch(
                    batch_id="prod-request-batch-001",
                    applicant_user_id=applicant_user_id,
                    applicant_org_id=applicant_org_id,
                    purpose="CONTROLLED_AGGREGATE_QUERY",
                    requested_scope_json={"raw_data_export": False},
                    allow_partial=False,
                    status="COMPLETED",
                    confirmation_hash="6" * 64,
                    idempotency_key="prod-batch-idempotency-001",
                )
            )
            db.add(
                DataRequestItem(
                    request_item_id=request_item_id,
                    batch_id="prod-request-batch-001",
                    provider_org_id=provider_org_id,
                    asset_id="prod-asset-001",
                    authorization_id=authorization_id,
                    matched_rule_id=None,
                    matched_rule_version="v1",
                    scope_json={"raw_data_export": False},
                    status="SUCCEEDED",
                    idempotency_key="prod-item-idempotency-001",
                    result_json=public_result,
                    result_hash=result_hash,
                    completed_at=utc_now(),
                )
            )
            db.add(
                TrustedQueryTask(
                    task_id=task_id,
                    applicant_user_id=applicant_user_id,
                    applicant_org_id=applicant_org_id,
                    operation_namespace="TRUSTED_QUERY_EXECUTE_V1",
                    idempotency_key="prod-query-idempotency-001",
                    request_fingerprint=sha256_json(task_payload),
                    canonical_payload_json=task_payload,
                    authorization_id=authorization_id,
                    provider_org_id=provider_org_id,
                    asset_id="prod-asset-001",
                    asset_version_id="prod-asset-version-001",
                    request_item_id=request_item_id,
                    status="SUCCEEDED",
                    result_json=public_result,
                    result_hash=result_hash,
                )
            )
            db.add(
                PrivacyComputeJob(
                    job_id=job_id,
                    task_id=task_id,
                    algorithm_code="sum",
                    adapter_code=f"LOCAL_SUBJECT_NODE_{provider_org_id}",
                    input_hashes_json=["7" * 64],
                    output_hash=result_hash,
                    result_json=public_result,
                    execution_attestation_json={
                        "connector_signature_verified": True,
                        "signature_algorithm": "Ed25519",
                        "raw_records_returned": False,
                        "raw_data_exported": False,
                        "execution_environment": "SUBJECT_CONNECTOR",
                        "attestation_status": "CONNECTOR_SIGNED",
                        "cross_domain_non_export_verified": True,
                        "connector_audit_event_verified": True,
                        "receipt_verification_schema": "TRUSTED_QUERY_RECEIPT_V2",
                        "signing_key_fingerprint": signing_key_fingerprint,
                        "authorization_id": authorization_id,
                        "applicant_org_id": applicant_org_id,
                        "applicant_user_id": applicant_user_id,
                        "provider_org_id": provider_org_id,
                        "request_item_id": request_item_id,
                        "node_code": node_code,
                        "connector_audit": connector_audit,
                        "privacy_verification": privacy_verification,
                    },
                    status="SUCCEEDED",
                    progress=100,
                    privacy_guarantees_json={
                        "connector_signature_verified": True,
                        "raw_records_returned": False,
                        "raw_data_exported": False,
                        "execution_environment": "SUBJECT_CONNECTOR",
                        "attestation_status": "CONNECTOR_SIGNED",
                        "cross_domain_non_export_verified": True,
                        "connector_audit_event_verified": True,
                        "receipt_verification_schema": "TRUSTED_QUERY_RECEIPT_V2",
                        "signing_key_fingerprint": signing_key_fingerprint,
                        "connector_audit": connector_audit,
                        "privacy_verification": privacy_verification,
                    },
                )
            )
            db.add(
                ExecutionReceipt(
                    receipt_id="prod-query-receipt-001",
                    request_item_id=request_item_id,
                    provider_org_id=provider_org_id,
                    task_id=task_id,
                    request_hash=request_hash,
                    result_hash=result_hash,
                    node_code=node_code,
                    node_signature=node_signature,
                    result_summary_json={
                        "result": signed_result["result"],
                        "unit": signed_result["unit"],
                        "record_count": signed_result["record_count"],
                        "trend": signed_result["trend"],
                        "raw_records_returned": False,
                        "raw_data_exported": False,
                        "connector_audit": connector_audit,
                        "privacy_verification": privacy_verification,
                        "verification_envelope": {
                            "schema": "TRUSTED_QUERY_RECEIPT_V2",
                            "signed_result": signed_result,
                            "signing_key_fingerprint": signing_key_fingerprint,
                            "verifier": "ED25519_CANONICAL_JSON_V1",
                        },
                    },
                    visible_to_orgs_json=[applicant_org_id, provider_org_id],
                    status="CONFIRMED",
                    audit_sequence=1,
                    previous_audit_hash=previous_hash,
                    connector_audit_hash=audit_hash,
                    audit_event_verified=True,
                )
            )
            db.commit()
            yield db, guard_settings, {
                "private_key": private_key,
                "public_key": public_key,
                "signed_result": signed_result,
                "request_hash": request_hash,
            }
    finally:
        engine.dispose()


def test_valid_production_configuration_passes() -> None:
    validate_runtime_settings(production_settings())


def test_fresh_production_lifespan_does_not_seed_demo_agent_identities(
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    isolated_session = sessionmaker(bind=engine)
    monkeypatch.setattr(main_module, "settings", production_settings())
    monkeypatch.setattr(main_module, "SessionLocal", isolated_session)
    monkeypatch.setattr(main_module, "validate_runtime_settings", lambda: None)
    monkeypatch.setattr(main_module, "assert_production_runtime_clean", lambda _settings: None)
    monkeypatch.setattr(main_module, "ensure_runtime_schema", lambda: None)

    async def start_and_stop() -> None:
        async with main_module.lifespan(main_module.app):
            pass

    try:
        asyncio.run(start_and_stop())
        with Session(engine) as db:
            assert db.scalar(select(func.count(DidIdentity.did_id))) == 0
            assert (db.scalar(select(func.count(AgentTool.tool_id))) or 0) > 0
    finally:
        engine.dispose()


def test_production_subject_node_config_uses_explicit_deployment_identity(monkeypatch) -> None:
    configured_key = base64.b64encode(b"c" * 32).decode()
    production = production_settings(
        subject_node_endpoints_json=(
            '{"org-generator-t01":"https://configured-generator.example.com"}'
        ),
        subject_node_public_keys_json=(
            '{"org-generator-t01":"' + configured_key + '"}'
        ),
        subject_node_ids_json=(
            '{"org-generator-t01":"configured-generator-node"}'
        ),
    )
    monkeypatch.setattr(local_data_boundary, "settings", production)

    with SessionLocal() as db:
        node = db.scalar(
            select(LocalSubjectNode).where(LocalSubjectNode.org_id == "org-generator-t01")
        )
        assert node is not None
        node.endpoint_ref = "https://stale-generator.example.com"
        node.public_key = "stale-public-key"
        db.commit()

        resolved = local_data_boundary.subject_node_config(db, "org-generator-t01")
        assert resolved is not None
        assert resolved["endpoint"] == "https://configured-generator.example.com"
        assert resolved["public_key"] == configured_key
        assert resolved["node_code"] == "configured-generator-node"

        monkeypatch.setattr(
            local_data_boundary,
            "settings",
            replace(production, subject_node_public_keys_json='{"another-org":"key"}'),
        )
        assert local_data_boundary.subject_node_config(db, "org-generator-t01") is None

        monkeypatch.setattr(local_data_boundary, "settings", replace(production, app_env="demo"))
        resolved = local_data_boundary.subject_node_config(db, "org-generator-t01")
        assert resolved is not None
        assert resolved["endpoint"] == "https://stale-generator.example.com"
        assert resolved["public_key"] == "stale-public-key"


def test_production_subject_maps_use_the_same_normalization_at_validation_and_runtime(
    monkeypatch,
) -> None:
    configured_key = base64.b64encode(b"n" * 32).decode()
    production = production_settings(
        subject_node_endpoints_json=(
            '{" org-normalized ":" https://normalized.example.com "}'
        ),
        subject_node_ids_json='{" org-normalized ":" normalized-node "}',
        subject_node_public_keys_json=(
            '{" org-normalized ":" ' + configured_key + ' "}'
        ),
    )
    validate_runtime_settings(production)
    assert parse_subject_map(production.subject_node_ids_json) == {
        "org-normalized": "normalized-node"
    }
    monkeypatch.setattr(local_data_boundary, "settings", production)

    with SessionLocal() as db:
        resolved = local_data_boundary.subject_node_config(db, "org-normalized")
    assert resolved is not None
    assert resolved["endpoint"] == "https://normalized.example.com"
    assert resolved["node_code"] == "normalized-node"
    assert resolved["public_key"] == configured_key


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"test_fixture_seed": True}, "TEST_FIXTURE_SEED"),
        ({"demo_catalog_seed": True}, "DEMO_CATALOG_SEED"),
        ({"demo_business_seed": True}, "DEMO_BUSINESS_SEED"),
        ({"test_compute_delay_ms": 50}, "TEST_COMPUTE_DELAY_MS"),
        ({"opa_local_fallback": True}, "OPA_LOCAL_FALLBACK"),
        ({"jwt_secret": "replace-me"}, "JWT_SECRET"),
        ({"cors_origins": ("http://localhost:8080",)}, "CORS_ORIGINS"),
        ({"cors_origins": ("http://settlement.example.com",)}, "CORS_ORIGINS"),
        ({"cors_origins": ("https://user@settlement.example.com",)}, "CORS_ORIGINS"),
        ({"cors_origins": ("https://settlement.example.com/path",)}, "CORS_ORIGINS"),
        ({"environment_name": "测试环境"}, "ENVIRONMENT_NAME"),
        ({"environment_name": "公开演示环境"}, "ENVIRONMENT_NAME"),
        ({"platform_signing_private_key": ""}, "PLATFORM_SIGNING_PRIVATE_KEY"),
        ({"subject_node_endpoints_json": "{}"}, "SUBJECT_NODE_ENDPOINTS_JSON"),
        ({"subject_node_endpoints_json": '{"org":"http://connector"}'}, "SUBJECT_NODE_ENDPOINTS_JSON"),
        ({"subject_node_public_keys_json": "{}"}, "SUBJECT_NODE_PUBLIC_KEYS_JSON"),
        ({"subject_node_public_keys_json": '{"org":"not-a-key"}'}, "SUBJECT_NODE_PUBLIC_KEYS_JSON"),
        ({"subject_node_ids_json": "{}"}, "SUBJECT_NODE_IDS_JSON"),
        ({"subject_node_ids_json": '{"org":"bad connector id"}'}, "SUBJECT_NODE_IDS_JSON"),
        (
            {"subject_node_public_key_rings_json": '{"org-generator":["not-a-key"]}'},
            "SUBJECT_NODE_PUBLIC_KEY_RINGS_JSON",
        ),
    ],
)
def test_unsafe_production_configuration_fails(changes: dict, message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        validate_runtime_settings(production_settings(**changes))


def test_public_branding_contains_white_label_fields_and_safe_feature_flags() -> None:
    payload = public_branding(
        production_settings(
            product_name="客户结算平台",
            product_short_name="客户结算",
            customer_name="示例客户",
            operator_name="示例运营方",
            logo="/branding/logo.svg",
            brand_theme_id="neutral-blue",
            brand_primary="#1769AA",
        )
    )
    assert payload["productName"] == "客户结算平台"
    assert payload["productShortName"] == "客户结算"
    assert payload["customerName"] == "示例客户"
    assert payload["operatorName"] == "示例运营方"
    assert payload["logo"] == "/branding/logo.svg"
    assert payload["brandTheme"] == {
        "themeId": "neutral-blue",
        "primary": "#1769AA",
    }
    assert payload["environment"] == "production"
    assert payload["demoAccounts"] == []
    assert payload["features"] == {
        "fixtureImport": False,
        "anomalyInjection": False,
        "testOperations": False,
    }


def test_public_demo_config_exposes_only_explicit_demo_accounts() -> None:
    payload = public_branding(production_settings(app_env="demo", environment_name="公开演示环境"))
    assert payload["environment"] == "demo"
    assert {account["label"] for account in payload["demoAccounts"]} >= {"发电企业", "监管方", "平台运维"}


def test_public_result_projection_requires_signed_resource_name() -> None:
    with pytest.raises(TrustedQueryProjectionError, match="resource name"):
        build_trusted_query_public_result(
            task_id="task-1",
            job_id="job-1",
            request_item_id="item-1",
            authorization_id="auth-1",
            canonical_payload={"function": "sum"},
            attempt=1,
            asset_version_id="version-1",
            signed_result={
                "result": 3,
                "unit": "MWh",
                "record_count": 1,
                "capability": "本地受控计算",
            },
            connector_audit={"status": "VERIFIED"},
            privacy_verification={"status": "VERIFIED"},
            receipt_schema="TRUSTED_QUERY_RECEIPT_V2",
        )


def test_public_result_projection_uses_signed_labels_and_strips_trend_extras() -> None:
    projected = build_trusted_query_public_result(
        task_id="task-1",
        job_id="job-1",
        request_item_id="item-1",
        authorization_id="auth-1",
        canonical_payload={"function": "sum"},
        attempt=1,
        asset_version_id="version-1",
        signed_result={
            "result": 3,
            "unit": "MWh",
            "record_count": 1,
            "trend": [{"date": "2026-08-29", "value": 3, "private_note": "drop"}],
            "resource_name": "签名内资源名",
            "capability": "本地受控计算",
        },
        connector_audit={"status": "VERIFIED"},
        privacy_verification={"status": "VERIFIED"},
        receipt_schema="TRUSTED_QUERY_RECEIPT_V2",
    )
    assert projected["resource_name"] == "签名内资源名"
    assert projected["function_name"] == "求和"
    assert projected["trend"] == [{"date": "2026-08-29", "value": 3.0}]


def test_production_database_guard_rejects_seeded_test_records() -> None:
    with SessionLocal() as db, pytest.raises(RuntimeError, match="non-production records"):
        assert_production_database_clean(db, production_settings())


def test_production_database_guard_allows_receipt_bound_trusted_query_restart() -> None:
    with production_database_with_trusted_query_record() as (db, guard_settings, _material):
        assert_production_database_clean(db, guard_settings)
        assert_production_database_clean(db, guard_settings)


def test_production_database_guard_rejects_a_self_consistent_forged_signature() -> None:
    with production_database_with_trusted_query_record() as (db, guard_settings, _material):
        receipt = db.get(ExecutionReceipt, "prod-query-receipt-001")
        assert receipt is not None
        receipt.node_signature = base64.b64encode(b"forged" * 10).decode()
        db.commit()
        with pytest.raises(RuntimeError, match="1 unsupported compute records"):
            assert_production_database_clean(db, guard_settings)


def test_production_database_guard_rejects_public_projection_injection() -> None:
    with production_database_with_trusted_query_record() as (db, guard_settings, _material):
        task = db.get(TrustedQueryTask, "prod-query-task-001")
        job = db.get(PrivacyComputeJob, "prod-query-job-001")
        request_item = db.get(DataRequestItem, "prod-request-item-001")
        assert task is not None and job is not None and request_item is not None
        injected = {**(job.result_json or {}), "raw_records": [{"secret": "blocked"}]}
        job.result_json = injected
        task.result_json = injected
        request_item.result_json = injected
        db.commit()
        with pytest.raises(RuntimeError, match="1 unsupported compute records"):
            assert_production_database_clean(db, guard_settings)


def test_production_database_guard_rejects_applicant_rebinding() -> None:
    with production_database_with_trusted_query_record() as (db, guard_settings, _material):
        task = db.get(TrustedQueryTask, "prod-query-task-001")
        job = db.get(PrivacyComputeJob, "prod-query-job-001")
        receipt = db.get(ExecutionReceipt, "prod-query-receipt-001")
        assert task is not None and job is not None and receipt is not None
        task.applicant_org_id = "org-rebound-prod"
        job.execution_attestation_json = {
            **(job.execution_attestation_json or {}),
            "applicant_org_id": "org-rebound-prod",
        }
        receipt.visible_to_orgs_json = ["org-rebound-prod", task.provider_org_id]
        db.commit()
        with pytest.raises(RuntimeError, match="1 unsupported compute records"):
            assert_production_database_clean(db, guard_settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_code", "LOCAL_CONTROLLED_SETTLEMENT_V1"),
        ("algorithm_code", "average"),
        ("input_hashes_json", ["0" * 64]),
    ],
)
def test_production_database_guard_rejects_compute_record_relabeling(
    field: str,
    value: object,
) -> None:
    with production_database_with_trusted_query_record() as (db, guard_settings, _material):
        job = db.get(PrivacyComputeJob, "prod-query-job-001")
        assert job is not None
        setattr(job, field, value)
        db.commit()
        with pytest.raises(RuntimeError, match="1 unsupported compute records"):
            assert_production_database_clean(db, guard_settings)


def test_production_database_guard_rejects_query_fingerprint_tampering() -> None:
    with production_database_with_trusted_query_record() as (db, guard_settings, _material):
        task = db.get(TrustedQueryTask, "prod-query-task-001")
        assert task is not None
        task.request_fingerprint = "0" * 64
        db.commit()
        with pytest.raises(RuntimeError, match="1 unsupported compute records"):
            assert_production_database_clean(db, guard_settings)


def test_production_database_guard_accepts_a_retired_configured_signing_key() -> None:
    with production_database_with_trusted_query_record() as (
        db,
        guard_settings,
        material,
    ):
        replacement_private_key = Ed25519PrivateKey.generate()
        replacement_public_key = base64.b64encode(
            replacement_private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode()
        rotated = replace(
            guard_settings,
            subject_node_public_keys_json=json.dumps(
                {"org-provider-prod": replacement_public_key}, separators=(",", ":")
            ),
            subject_node_public_key_rings_json=json.dumps(
                {"org-provider-prod": [material["public_key"]]}, separators=(",", ":")
            ),
        )
        validate_runtime_settings(rotated)
        assert_production_database_clean(db, rotated)


def _convert_fixture_to_legacy_subject_record(
    db: Session,
    material: dict,
    *,
    non_export_attested: bool,
) -> None:
    task = db.get(TrustedQueryTask, "prod-query-task-001")
    job = db.get(PrivacyComputeJob, "prod-query-job-001")
    receipt = db.get(ExecutionReceipt, "prod-query-receipt-001")
    request_item = db.get(DataRequestItem, "prod-request-item-001")
    assert all(item is not None for item in (task, job, receipt, request_item))
    assert task is not None and job is not None and receipt is not None
    assert request_item is not None
    # Real pre-V2 rows retained only this smaller scope. Optional connector
    # parameters lived exclusively in the signed request hash.
    request_item.scope_json = {
        "function": "sum",
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "region": "east",
    }
    connector_payload = canonical_connector_request_payload(
        {
            "task_id": task.task_id,
            "authorization_id": task.authorization_id,
            "request_item_id": task.request_item_id,
            "provider_org_id": task.provider_org_id,
            "rule_version": request_item.matched_rule_version,
            "resource": "generation",
            "function": "sum",
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
            "region": "east",
            "hour": 7,
            "threshold": 4.5,
            "group_by": "region",
            "decimals": 4,
        }
    )
    request_hash = sha256_json(connector_payload)
    privacy = {
        "minimum_group_size": 3,
        "raw_records_returned": False,
        "decimals": 4,
    }
    legacy_signed_result = {
        "task_id": task.task_id,
        "authorization_id": task.authorization_id,
        "request_item_id": task.request_item_id,
        "provider_org_id": task.provider_org_id,
        "rule_version": "v1",
        "connector_id": "prod-provider-node-001",
        "energy_domain": "electricity",
        "resource_name": "生产侧发电量",
        "function_name": "求和",
        "result": 42.0,
        "unit": "MWh",
        "record_count": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "privacy": privacy,
        "capability": "本地受控计算",
    }
    if non_export_attested:
        privacy.update(
            {
                "raw_data_exported": False,
                "execution_environment": "SUBJECT_CONNECTOR",
                "attestation_status": "CONNECTOR_SIGNED",
                "non_export_attestation": {
                    "status": "SIGNED",
                    "issuer": "prod-provider-node-001",
                    "boundary": "CONNECTOR_LOCAL_DATA",
                    "request_hash": request_hash,
                    "result_scope": "AGGREGATE_ONLY",
                    "raw_data_exported": False,
                },
            }
        )
        legacy_signed_result["privacy_verification"] = {
            "mode": "SIGNED_CONNECTOR_NON_EXPORT",
            "request_hash": request_hash,
            "raw_data_exported": False,
            "result_scope": "AGGREGATE_ONLY",
        }
    legacy_hash = sha256_json(legacy_signed_result)
    legacy_signature = base64.b64encode(
        material["private_key"].sign(canonical_json(legacy_signed_result).encode())
    ).decode()
    response = {
        **legacy_signed_result,
        "signature": legacy_signature,
        "public_key": material["public_key"],
        "signature_algorithm": "Ed25519",
        "signature_valid": True,
    }
    attestation = {
        "connector_signature_verified": True,
        "signature_algorithm": "Ed25519",
        "raw_records_returned": False,
        "authorization_id": task.authorization_id,
        "applicant_org_id": task.applicant_org_id,
        "provider_org_id": task.provider_org_id,
        "request_item_id": task.request_item_id,
        "node_code": "prod-provider-node-001",
    }
    if non_export_attested:
        privacy_verification = {
            **verify_signed_connector_non_export(legacy_signed_result, connector_payload),
            "result_hash": legacy_hash,
        }
        attestation.update(
            {
                "raw_data_exported": False,
                "execution_environment": "SUBJECT_CONNECTOR",
                "attestation_status": "CONNECTOR_SIGNED",
                "cross_domain_non_export_verified": True,
                "privacy_verification": privacy_verification,
            }
        )
        guarantees = {
            **privacy,
            "execution_environment": "SUBJECT_CONNECTOR",
            "attestation_status": "CONNECTOR_SIGNED",
            "connector_signature_verified": True,
            "cross_domain_non_export_verified": True,
            "privacy_verification": privacy_verification,
        }
        summary = {
            "result": legacy_signed_result["result"],
            "unit": legacy_signed_result["unit"],
            "record_count": legacy_signed_result["record_count"],
            "trend": [],
            "raw_records_returned": False,
            "raw_data_exported": False,
            "privacy_verification": privacy_verification,
        }
        request_item.result_json = {
            **response,
            "_hiddenchain_task_id": task.task_id,
            "_hiddenchain_job_id": job.job_id,
        }
    else:
        guarantees = privacy
        summary = {
            "result": legacy_signed_result["result"],
            "unit": legacy_signed_result["unit"],
            "record_count": legacy_signed_result["record_count"],
            "raw_records_returned": False,
        }
        request_item.result_json = response
    job.output_hash = legacy_hash
    job.result_json = response
    job.execution_attestation_json = attestation
    job.privacy_guarantees_json = guarantees
    request_item.result_hash = legacy_hash
    receipt.request_hash = request_hash
    receipt.result_hash = legacy_hash
    receipt.node_signature = legacy_signature
    receipt.result_summary_json = summary
    receipt.audit_sequence = None
    receipt.previous_audit_hash = None
    receipt.connector_audit_hash = None
    receipt.audit_event_verified = None
    db.delete(task)
    db.commit()


@pytest.mark.parametrize("non_export_attested", [False, True])
def test_production_database_guard_keeps_real_legacy_generations_read_only(
    non_export_attested: bool,
) -> None:
    with production_database_with_trusted_query_record() as (
        db,
        guard_settings,
        material,
    ):
        _convert_fixture_to_legacy_subject_record(
            db,
            material,
            non_export_attested=non_export_attested,
        )
        assert_production_database_clean(db, guard_settings)


@pytest.mark.parametrize(
    "adapter_code",
    [
        "UNREGISTERED_REMOTE_ADAPTER_V9",
        "LOCAL_SUBJECT_NODE_org-imposter-prod",
    ],
)
def test_production_database_guard_still_rejects_unknown_compute_adapter(
    adapter_code: str,
) -> None:
    with production_database_with_trusted_query_record() as (db, guard_settings, _material):
        job = db.get(PrivacyComputeJob, "prod-query-job-001")
        assert job is not None
        job.adapter_code = adapter_code
        db.commit()
        with pytest.raises(RuntimeError, match="1 unsupported compute records"):
            assert_production_database_clean(db, guard_settings)


def test_production_database_guard_quarantines_pre_receipt_enterprise_history() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode()
    signed_result = {
        "task_id": "legacy-enterprise-task-001",
        "result": 7,
        "resource_name": "升级前记录",
        "function_name": "求和",
        "raw_records_returned": False,
    }
    signature = base64.b64encode(
        private_key.sign(canonical_json(signed_result).encode())
    ).decode()
    with Session(engine) as db:
        db.add(
            PrivacyComputeJob(
                job_id="legacy-enterprise-job-001",
                task_id="legacy-enterprise-task-001",
                algorithm_code="sum",
                adapter_code="ENTERPRISE_CONNECTOR_ELECTRICITY",
                input_hashes_json=["1" * 64],
                output_hash=sha256_json(signed_result),
                result_json={
                    **signed_result,
                    "signature": signature,
                    "public_key": public_key,
                    "signature_algorithm": "Ed25519",
                    "signature_valid": True,
                },
                execution_attestation_json={
                    "connector_signature_verified": True,
                    "raw_records_returned": False,
                    "applicant_org_id": "org-legacy-prod",
                },
                privacy_guarantees_json={"raw_records_returned": False},
                status="SUCCEEDED",
                progress=100,
            )
        )
        db.commit()
        assert_production_database_clean(db, production_settings())
    engine.dispose()


def test_static_production_build_guard_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "backend" / "scripts" / "check_production.py")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_production_route_table_excludes_test_operations() -> None:
    blocked = {
        "/api/auth/test-users",
        "/api/settlement/import-and-run",
        "/api/anomalies/inject",
        "/api/trusted-execution/example",
        "/api/prototype/query",
        "/api/prototype/connector/sample.csv",
        "/api/prototype/connector/{connector}/resources/upload",
        "/api/prototype/policy",
        "/api/prototype/policy/rules",
        "/api/prototype/audit/tamper",
        "/api/prototype/audit/restore",
    }
    allowed = {
        "/api/prototype/header",
        "/api/prototype/dashboard",
        "/api/prototype/connector",
        "/api/prototype/audit",
        "/api/prototype/audit/verify",
    }
    program = (
        "from app.main import app; "
        f"blocked={blocked!r}; "
        f"allowed={allowed!r}; "
        "paths=set(app.openapi()['paths']); "
        "assert not (blocked & paths), sorted(blocked & paths); "
        "assert allowed <= paths, sorted(allowed - paths)"
    )
    environment = {
        **os.environ,
        "APP_ENV": "production",
        "TEST_FIXTURE_SEED": "false",
        "TEST_COMPUTE_DELAY_MS": "0",
        "OPA_LOCAL_FALLBACK": "false",
    }
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=PROJECT_ROOT / "backend",
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
