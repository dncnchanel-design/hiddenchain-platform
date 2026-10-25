"""Scope and purity checks for controlled assistant reads, without seed data."""
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal, engine
from app.models import (
    AuditLog, AuditReport, Base, BlockchainEvidence, DataContract, DataSpaceAgreement,
    DataUsageRequest, DidIdentity,
    Organization, PrivacyComputeJob, SettlementRule, SettlementTask, TaskParticipant,
    User, UserNotification, utc_now,
)
from app.security import sha256_json
from app.services.assistant_catalog import read_action, target_candidates, validate_target
from app.trust_models import DataAsset, DataAssetVersion, DataSource


ACCOUNTS = {
    "generator": ("GENERATOR", "electricity"), "retailer": ("RETAILER", "electricity"),
    "exchange": ("EXCHANGE", "electricity"), "regulator": ("REGULATOR", "electricity"),
    "admin": ("ADMIN", "electricity"),
    **{name: (role, name) for name, role in (("coal", "COAL_ENTERPRISE"), ("heat", "HEAT_ENTERPRISE"), ("gas", "GAS_ENTERPRISE"), ("oil", "OIL_ENTERPRISE"))},
    **{"exchange_" + domain: ("EXCHANGE", domain) for domain in ("coal", "heat", "gas", "oil")},
}


def request(db, request_id="request-owned", *, provider="generator", applicant="exchange", status="SUBMITTED"):
    item = DataUsageRequest(
        request_id=request_id, asset_id="asset-" + provider, asset_version_id="version-" + provider,
        applicant_user_id=applicant, applicant_org_id=applicant, provider_org_id=provider,
        applicant_did="did:test:" + applicant, provider_did="did:test:" + provider,
        purpose="受控查询", usage_mode="MPC_AGGREGATE", duration_days=30,
        expires_at=utc_now() + timedelta(days=30), status=status, trace_id=request_id,
    )
    db.add(item)
    db.flush()
    return item


@pytest.fixture(autouse=True)
def reset_test_database():
    """Override conftest's shared demo seeding with a small isolated fixture."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for account, (role, domain) in ACCOUNTS.items():
            db.add(Organization(org_id=account, org_name=account, org_type=role, energy_domain=domain))
            db.flush()
            permissions = ["VIEW_DATA", "APPROVE_AUTHORIZATION"]
            if role in {"EXCHANGE", "REGULATOR"}:
                permissions += ["VIEW_AUDIT"]
            if role == "REGULATOR":
                permissions += ["VIEW_AUDIT:TASK:task-owned", "CREATE_CROSS_ENERGY_QUERY"]
            db.add(User(user_id=account, org_id=account, username=account, password_hash="unused", display_name=account, role_code=role, permissions_json=permissions))
            db.add(DidIdentity(did_id="did:test:" + account, owner_type="ORG", owner_id=account, org_id=account, public_key_fingerprint="a" * 64, credential_status="VALID"))
            db.add(DataSource(source_id="source-" + account, source_code="source-" + account, source_name=account, owner_org_id=account, source_type="ENTERPRISE_CONNECTOR", security_domain=domain, endpoint_ref="https://private-node.invalid/secret"))
            db.flush()
            db.add(DataAsset(asset_id="asset-" + account, asset_code="asset-" + account, asset_name=account + "本方数据", source_id="source-" + account, owner_org_id=account, asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", status="ACTIVE", metadata_json={"domain": domain, "private_payload": "secret-source-value"}))
            db.flush()
            db.add(DataAssetVersion(version_id="version-" + account, asset_id="asset-" + account, version_no=1, schema_version="metadata", schema_json={"period_start": "2026-01-01", "period_end": "2026-09-30"}, data_ref="connector://private-payload/" + account, data_hash="a" * 64, immutable_hash="b" * 64, record_count=100))
            db.flush()
        db.add(SettlementRule(rule_id="rule", rule_name="规则", rule_version="1", formula_dsl="{}", rule_hash="a" * 64))
        db.flush()
        for task_id, creator in (("task-owned", "exchange"), ("task-foreign", "retailer"), ("task-coal", "coal")):
            db.add(SettlementTask(task_id=task_id, capsule_id=task_id, task_name=task_id, trade_batch_no=task_id, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), creator_org_id=creator, rule_id="rule", ttc_state="RULE_FROZEN", status="READY"))
        db.flush()
        db.add(TaskParticipant(task_id="task-owned", org_id="generator", role_in_task="DATA_PROVIDER"))
        request(db)
        request(db, "request-foreign", provider="coal", applicant="retailer")
        for suffix in ("owned", "foreign"):
            payload = {"private_payload": "never-export-evidence-body"}
            db.add(BlockchainEvidence(evidence_id="evidence-" + suffix, task_id="task-" + suffix, stage="AUDIT", biz_type="AUDIT_REPORT", biz_id="report-" + suffix, evidence_hash=sha256_json(payload), payload_json=payload, tx_hash="tx-" + suffix, block_height=1))
            db.add(AuditReport(report_id="report-" + suffix, task_id="task-" + suffix, template_code="AUDIT", report_title=suffix + "审计报告", report_content="private-report-body", report_hash="c" * 64, risk_level="LOW"))
        db.add(PrivacyComputeJob(job_id="job-owned", task_id="task-owned", algorithm_code="CONTROLLED", status="SUCCEEDED", result_json={"secret-result": 123}))
        db.add(PrivacyComputeJob(job_id="job-foreign", task_id="task-foreign", algorithm_code="CONTROLLED", status="SUCCEEDED"))
        db.add(PrivacyComputeJob(job_id="job-coal-settlement", task_id="task-coal", algorithm_code="CONTROLLED"))
        db.add(PrivacyComputeJob(job_id="job-coal-query", task_id="query-detached", algorithm_code="CONTROLLED", status="SUCCEEDED", execution_attestation_json={"request_item_id": "item-controlled", "applicant_org_id": "exchange_coal", "provider_org_id": "coal"}, result_json={"secret-result": 321}))
        db.add(PrivacyComputeJob(job_id="job-orphan", task_id="no-task", algorithm_code="CONTROLLED"))
        db.add(User(user_id="exchange-other", org_id="exchange", username="exchange-other", password_hash="unused", display_name="other", role_code="EXCHANGE"))
        db.flush()
        db.add(UserNotification(notification_id="notification-own", user_id="exchange", org_id="exchange", notification_type="TEST", title="我的通知", body="private-body", dedupe_key="own"))
        db.add(UserNotification(notification_id="notification-peer", user_id="exchange-other", org_id="exchange", notification_type="TEST", title="同组织他人通知", body="private-body", dedupe_key="peer"))
        db.add(UserNotification(notification_id="notification-wrong-org", user_id="exchange", org_id="coal", notification_type="TEST", title="异主体通知", body="private-body", dedupe_key="wrong-org"))
        db.commit()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def user(db, account="exchange"):
    return db.get(User, account)


@pytest.mark.parametrize("account", ACCOUNTS)
def test_personal_catalog_is_scoped_metadata_for_every_account(db, account):
    output = read_action(db, user(db, account), "LIST_DATA_ASSETS")
    if account == "admin":
        assert output["status"] == "BLOCKED"
        return
    assert output["status"] == "SUCCEEDED" and output["scope"] == "OWN_ORGANIZATION"
    assert [item["asset_id"] for item in output["items"]] == ["asset-" + account]
    assert output["items"][0]["record_count"] == 100
    assert output["items"][0]["period_end"] == "2026-09-30"
    assert output["raw_data_accessed"] is False
    assert not any(secret in str(output) for secret in ("secret-source-value", "connector://", "private-node"))


def test_visible_catalog_and_integrity_keep_different_scopes(db):
    actor = user(db, "exchange_coal")
    visible = read_action(db, actor, "LIST_VISIBLE_DATA_ASSETS")
    assert {item["asset_id"] for item in visible["items"]} == {"asset-coal", "asset-exchange_coal"}
    assert visible["usage_authority_granted"] is False
    assert read_action(db, actor, "CHECK_ASSET_INTEGRITY", "asset-generator", "data_asset")["status"] == "BLOCKED"
    assert read_action(db, user(db, "generator"), "CHECK_ASSET_INTEGRITY", "asset-retailer", "data_asset")["status"] == "BLOCKED"
    integrity = read_action(db, user(db, "generator"), "CHECK_ASSET_INTEGRITY", "asset-generator", "data_asset")
    assert integrity["version"]["version_no"] == 1 and integrity["integrity"]["passport_present"] is False


def test_requests_use_party_scope_even_for_exchange_and_regulator(db):
    assert read_action(db, user(db), "QUERY_AUTHORIZATION_STATUS", "request-foreign", "data_usage_request")["status"] == "BLOCKED"
    assert read_action(db, user(db, "regulator"), "QUERY_AUTHORIZATION_STATUS", "request-owned", "data_usage_request")["status"] == "BLOCKED"
    assert {item["request_id"] for item in read_action(db, user(db), "LIST_AUTHORIZATIONS")["items"]} == {"request-owned"}
    assert read_action(db, user(db, "regulator"), "LIST_AUTHORIZATIONS")["total"] == 0


def test_task_reads_include_creator_participant_and_detached_query_but_not_foreign_tasks(db):
    assert read_action(db, user(db), "CHECK_TTC_STATUS", "task-owned", "settlement_task")["status"] == "SUCCEEDED"
    assert read_action(db, user(db, "generator"), "CHECK_TTC_STATUS", "task-owned", "settlement_task")["status"] == "SUCCEEDED"
    assert read_action(db, user(db), "CHECK_TTC_STATUS", "task-foreign", "settlement_task")["status"] == "BLOCKED"
    assert read_action(db, user(db, "exchange_coal"), "CHECK_TTC_STATUS", "task-owned", "settlement_task")["status"] == "BLOCKED"
    coal = read_action(db, user(db, "coal"), "LIST_TASKS")
    assert {item["entity_id"] for item in coal["items"]} == {"task-coal", "job-coal-settlement", "job-coal-query"}
    job = read_action(db, user(db, "coal"), "CHECK_TTC_STATUS", "job-coal-query", "privacy_compute_job")
    assert job["task_kind"] == "TRUSTED_QUERY" and "secret-result" not in str(job)
    assert read_action(db, user(db), "CHECK_TTC_STATUS", "job-orphan", "privacy_compute_job")["status"] == "BLOCKED"


def test_audit_grants_control_evidence_reports_and_regulatory_task_reads(db):
    actor = user(db, "regulator")
    assert read_action(db, actor, "CHECK_TTC_STATUS", "task-owned", "settlement_task")["error_code"] == "TTC_SCOPE_DENIED"
    assert read_action(db, actor, "CHECK_TTC_STATUS", "task-foreign", "settlement_task")["status"] == "BLOCKED"
    assert read_action(db, actor, "LIST_TASKS")["items"] == []
    assert target_candidates(db, actor, "CHECK_TTC_STATUS") == []
    evidence = read_action(db, actor, "VERIFY_EVIDENCE_SUMMARY", "evidence-owned", "blockchain_evidence")
    assert evidence["items"][0]["verify"]["matched"] is True
    assert "never-export-evidence-body" not in str(evidence)
    assert read_action(db, actor, "VERIFY_EVIDENCE_SUMMARY", "evidence-foreign", "blockchain_evidence")["status"] == "BLOCKED"
    assert read_action(db, actor, "EXPLAIN_AUDIT", "report-foreign", "audit_report")["status"] == "BLOCKED"
    assert read_action(db, actor, "EXPLAIN_AUDIT", "report-owned", "audit_report")["report_count"] == 1
    assert [item["report_id"] for item in read_action(db, actor, "LIST_AUDIT_REPORTS")["items"]] == ["report-owned"]
    assert read_action(db, user(db), "LIST_AUDIT_REPORTS")["status"] == "BLOCKED"
    actor.permissions_json = ["VIEW_DATA", "VIEW_AUDIT:ALL"]
    assert read_action(db, actor, "VERIFY_EVIDENCE_SUMMARY", "task-owned", "settlement_task")["status"] == "BLOCKED"


@pytest.mark.parametrize("provider", ["generator", "retailer", "coal", "heat", "gas", "oil", "exchange_coal"])
def test_provider_review_uses_individual_permission_for_all_provider_roles(db, provider):
    item = request(db, "request-review", provider=provider, applicant="regulator")
    actor = user(db, provider)
    assert validate_target(db, actor, "APPROVE_USAGE_REQUEST", "data_usage_request", item.request_id) is None
    assert validate_target(db, actor, "REJECT_USAGE_REQUEST", "data_usage_request", item.request_id) is None
    actor.permissions_json = ["VIEW_DATA"]
    assert validate_target(db, actor, "APPROVE_USAGE_REQUEST", "data_usage_request", item.request_id)[0] == "PROVIDER_REVIEW_REQUIRED"


def test_write_targets_are_scoped_before_any_review_envelope(db):
    assert validate_target(db, user(db, "generator"), "APPROVE_USAGE_REQUEST", "data_usage_request", "request-foreign")[0] == "REQUEST_SCOPE_DENIED"
    assert validate_target(db, user(db), "REVOKE_USAGE_AUTHORIZATION", "data_usage_request", "request-owned") is None
    assert validate_target(db, user(db), "SUBMIT_USAGE_REQUEST", "data_asset", "asset-generator") is None
    assert validate_target(db, user(db), "SUBMIT_USAGE_REQUEST", "data_asset", "asset-exchange")[0] == "REQUEST_SCOPE_DENIED"
    assert validate_target(db, user(db), "ADVANCE_TTC_STATE", "settlement_task", "task-owned") is None
    assert validate_target(db, user(db), "ADVANCE_TTC_STATE", "settlement_task", "task-foreign")[0] == "TTC_SCOPE_DENIED"
    assert validate_target(db, user(db, "regulator"), "ADVANCE_TTC_STATE", "settlement_task", "task-owned")[0] == "TTC_SCOPE_DENIED"
    assert read_action(db, user(db, "generator"), "APPROVE_USAGE_REQUEST", "request-owned", "data_usage_request")["error_code"] == "ASSISTANT_REVIEW_REQUIRED"


def test_candidates_are_scoped_deterministic_searchable_and_bounded(db):
    for index in range(25):
        db.add(DataAsset(asset_id=f"asset-more-{index:02}", asset_code=f"asset-more-{index:02}", asset_name="重名本方数据", source_id="source-exchange", owner_org_id="exchange", asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", status="ACTIVE"))
    db.flush()
    choices = target_candidates(db, user(db), "CHECK_ASSET_INTEGRITY", search="重名")
    assert len(choices) == 20
    assert choices == target_candidates(db, user(db), "CHECK_ASSET_INTEGRITY", search="重名")
    assert [item["entity_id"] for item in choices] == [f"asset-more-{index:02}" for index in range(20)]
    assert all(set(item) == {"entity_id", "entity_type", "label", "status"} for item in choices)
    output = read_action(db, user(db), "LIST_DATA_ASSETS", search="重名")
    assert output["total"] == 25 and output["has_more"] is True
    assert not target_candidates(db, user(db, "exchange_coal"), "CHECK_TTC_STATUS", search="task-owned")
    assert not target_candidates(db, user(db), "UNKNOWN_INTENT")


def test_metadata_queries_do_not_expire_business_rows_or_deliver_notifications(db, monkeypatch):
    item = db.get(DataUsageRequest, "request-owned")
    item.status, item.expires_at = "APPROVED", utc_now() - timedelta(days=1)
    db.commit()
    before_logs = db.scalar(select(func.count(AuditLog.log_id)))
    commits = []
    monkeypatch.setattr(db, "commit", lambda: commits.append(True))
    result = read_action(db, user(db), "QUERY_AUTHORIZATION_STATUS", item.request_id, "data_usage_request")
    assert result["status_value"] == "EXPIRED" and result["persisted_status"] == "APPROVED"
    assert item.status == "APPROVED" and item.state_version == 1
    notices = read_action(db, user(db), "LIST_NOTIFICATIONS")
    assert [notice["entity_id"] for notice in notices["items"]] == ["notification-own"]
    assert "private-body" not in str(notices)
    assert not commits and not db.dirty and not db.new
    assert db.scalar(select(func.count(AuditLog.log_id))) == before_logs


def test_administrator_only_gets_sanitized_platform_operations(db):
    actor = user(db, "admin")
    output = read_action(db, actor, "SYSTEM_OVERVIEW")
    assert output["status"] == "SUCCEEDED" and output["scope"] == "OPERATIONS_ONLY"
    assert output["overview"]["counts"]["organizations_total"] == len(ACCOUNTS)
    assert not any(value in str(output) for value in ("asset-generator", "task-owned", "request-owned", "private-node", "secret-source-value"))
    for action in ("LIST_VISIBLE_DATA_ASSETS", "LIST_TASKS", "LIST_AUTHORIZATIONS", "LIST_AUDIT_REPORTS", "LIST_NOTIFICATIONS", "APPROVE_USAGE_REQUEST"):
        assert read_action(db, actor, action)["status"] == "BLOCKED"
    assert read_action(db, user(db), "SYSTEM_OVERVIEW")["status"] == "BLOCKED"


def test_invalid_or_missing_targets_return_guidance_without_resource_enumeration(db):
    actor = user(db)
    assert validate_target(db, actor, "CHECK_TTC_STATUS", None, None)[0] == "ASSISTANT_TARGET_REQUIRED"
    assert validate_target(db, actor, "CHECK_TTC_STATUS", "data_asset", "asset-exchange")[0] == "ASSISTANT_TARGET_TYPE_MISMATCH"
    assert validate_target(db, actor, "CHECK_TTC_STATUS", "settlement_task", "task-absent")[0] == "TTC_SCOPE_DENIED"
    assert validate_target(db, actor, "LIST_DATA_ASSETS", "organization", "coal")[0] == "ASSISTANT_CATALOG_SCOPE_DENIED"


def test_regulatory_applicant_keeps_own_withdrawal_scope_without_provider_review_authority(db):
    current = request(db, "request-regulator", applicant="regulator")
    regulator = user(db, "regulator")
    assert validate_target(db, regulator, "REVOKE_USAGE_AUTHORIZATION", "data_usage_request", current.request_id) is None
    assert validate_target(db, regulator, "APPROVE_USAGE_REQUEST", "data_usage_request", current.request_id)[0] == "PROVIDER_REVIEW_REQUIRED"
    assert validate_target(db, regulator, "REVOKE_USAGE_AUTHORIZATION", "data_usage_request", "request-owned")[0] == "REQUEST_SCOPE_DENIED"
    assert read_action(db, regulator, "REVOKE_USAGE_AUTHORIZATION", current.request_id, "data_usage_request")["error_code"] == "ASSISTANT_REVIEW_REQUIRED"
    assert current.status == "SUBMITTED" and current.revoked_at is None


def test_authorized_assets_require_own_compute_permission_or_a_current_usable_grant(db, monkeypatch):
    actor = user(db)
    actor.permissions_json = [*actor.permissions_json, "CREATE_COMPUTE_TASK"]
    db.get(DataAsset, "asset-exchange").current_version_id = "version-exchange"
    db.add(DataAssetVersion(version_id="version-generator-granted", asset_id="asset-generator", version_no=0, schema_version="prior", data_ref="connector://private-prior", data_hash="d" * 64, immutable_hash="e" * 64, record_count=45, schema_json={"period_start": "2025-01-01", "period_end": "2025-12-31"}))
    db.flush()

    def grant(suffix, provider, *, request_status="APPROVED", expired=False, revoked=False, exhausted=False, agreement_state="ACTIVE", version_id=None):
        item = request(db, "grant-" + suffix, provider=provider, status=request_status)
        if version_id:
            item.asset_version_id = version_id
        contract = DataContract(contract_id="contract-" + suffix, provider_org_id=provider, consumer_type="exchange", purpose="CONTROLLED", policy_hash="a" * 64, status="ACTIVE")
        db.add(contract)
        db.flush()
        agreement = DataSpaceAgreement(agreement_id="agreement-" + suffix, contract_id=contract.contract_id,
            provider_org_id=provider, consumer_org_id="exchange", provider_did="did:test:" + provider,
            consumer_did="did:test:exchange", state=agreement_state, requested_purpose="CONTROLLED", algorithm_code="CONTROLLED",
            offered_policy_hash="a" * 64, negotiated_policy_hash="a" * 64,
            valid_from=utc_now() - timedelta(days=1), expires_at=utc_now() + timedelta(days=30),
            max_uses=2, use_count=2 if exhausted else 0, trace_id=suffix)
        db.add(agreement)
        db.flush()
        item.contract_id, item.agreement_id = contract.contract_id, agreement.agreement_id
        item.requested_scope_json = {"max_uses": 2}
        if expired:
            item.expires_at = utc_now() - timedelta(days=1)
        if revoked:
            item.revoked_at = utc_now()
        db.flush()
        return item

    grant("usable", "generator", version_id="version-generator-granted")
    grant("revoked", "retailer", revoked=True)
    grant("expired", "coal", expired=True)
    grant("exhausted", "heat", exhausted=True)
    grant("agreement-revoked", "gas", agreement_state="REVOKED")
    grant("not-approved", "oil", request_status="SUBMITTED")
    db.commit()
    monkeypatch.setattr(db, "commit", lambda: pytest.fail("A catalog read must not commit"))
    output = read_action(db, actor, "LIST_AUTHORIZED_DATA_ASSETS")
    assert {(item["asset_id"], item["asset_version_id"]) for item in output["items"]} == {
        ("asset-exchange", "version-exchange"), ("asset-generator", "version-generator-granted"),
    }
    supplied = next(item for item in output["items"] if item["asset_id"] == "asset-generator")
    assert supplied["authorization_id"] == "grant-usable" and supplied["remaining_uses"] == 2
    assert supplied["record_count"] == 45 and supplied["period_end"] == "2025-12-31"
    assert supplied["version_id"] != "version-generator"
    assert output["requires_execution_recheck"] is True and output["raw_data_accessed"] is False
    assert not any(value in str(output) for value in ("connector://", "secret-source-value", "private-node"))
    assert db.get(DataUsageRequest, "grant-expired").status == "APPROVED"
    assert not db.dirty and not db.new
    assert read_action(db, user(db, "admin"), "LIST_AUTHORIZED_DATA_ASSETS")["status"] == "BLOCKED"
    actor.permissions_json = ["VIEW_DATA", "APPROVE_AUTHORIZATION"]
    assert read_action(db, actor, "LIST_AUTHORIZED_DATA_ASSETS")["total"] == 0


def test_status_groups_filter_all_scoped_rows_before_total_and_page_limit(db):
    actor = user(db)
    db.get(UserNotification, "notification-own").read_at = utc_now()
    for index in range(25):
        item = request(db, f"request-filter-a-{index:02}", status="APPROVED")
        item.purpose = "筛选申请"
        db.add(PrivacyComputeJob(job_id=f"job-filter-a-{index:02}", task_id=f"detached-{index}", algorithm_code="CONTROLLED", status="SUCCEEDED", execution_attestation_json={"request_item_id": f"item-{index}", "applicant_org_id": "exchange", "provider_org_id": "generator"}))
        db.add(UserNotification(notification_id=f"notice-filter-a-{index:02}", user_id="exchange", org_id="exchange", notification_type="TEST", title=f"筛选通知 a{index:02}", body="private", read_at=utc_now(), dedupe_key=f"filter-{index}"))
    pending = request(db, "request-filter-z-pending")
    pending.purpose = "筛选申请"
    db.add(PrivacyComputeJob(job_id="job-filter-z-failed", task_id="detached-failed", algorithm_code="CONTROLLED", status="FAILED", execution_attestation_json={"request_item_id": "item-failed", "applicant_org_id": "exchange", "provider_org_id": "generator"}))
    db.add(UserNotification(notification_id="notice-filter-z-unread", user_id="exchange", org_id="exchange", notification_type="TEST", title="筛选通知 z未读", body="private", dedupe_key="filter-unread"))
    db.flush()
    requests = read_action(db, actor, "LIST_AUTHORIZATIONS", search="筛选申请", status_filter="PENDING")
    assert requests["total"] == 1 and requests["items"][0]["request_id"] == "request-filter-z-pending"
    tasks = read_action(db, actor, "LIST_TASKS", status_filter="failed")
    assert tasks["total"] == 1 and tasks["items"][0]["entity_id"] == "job-filter-z-failed"
    notices = read_action(db, actor, "LIST_NOTIFICATIONS", status_filter="UNREAD")
    assert notices["total"] == 1 and notices["items"][0]["notification_id"] == "notice-filter-z-unread"
    candidates = target_candidates(db, actor, "QUERY_AUTHORIZATION_STATUS", search="筛选申请", status_filter="PENDING")
    assert [item["entity_id"] for item in candidates] == ["request-filter-z-pending"]
    assert read_action(db, actor, "LIST_AUTHORIZATIONS", search="筛选申请", status_filter="APPROVED")["total"] == 25
    assert read_action(db, actor, "LIST_NOTIFICATIONS", status_filter="READ")["total"] == 26
