from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from threading import Barrier

from fastapi import BackgroundTasks, HTTPException
import pytest
from sqlalchemy import func, select

from app.database import SessionLocal, engine
from app.models import AccessRule, Base, DataContract, DataSpaceAgreement, DataUsageRequest, DidIdentity, Organization, TrustedQueryTask, User
from app.routers import trusted_query
from app.security import sha256_json
from app.services import trust_space
from app.trust_models import DataAsset, DataAssetVersion, DataSource


@pytest.fixture(autouse=True)
def reset_test_database():
    """These checks need only metadata, never the shared fixture Vault."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def metadata():
    with SessionLocal() as db:
        for key, role in (("provider", "GENERATOR"), ("applicant", "REGULATOR"), ("exchange", "EXCHANGE")):
            db.add(Organization(org_id=key, org_type=role, org_name=key, energy_domain="electricity"))
            db.flush()
            db.add(User(user_id=key, org_id=key, username=key, password_hash="unused", display_name=key, role_code=role, permissions_json=["CREATE_COMPUTE_TASK", "VIEW_COMPUTE_RESULT", "CREATE_CROSS_ENERGY_QUERY", "APPROVE_AUTHORIZATION"]))
            db.add(DidIdentity(did_id=f"did:test:{key}", owner_type="ORG", owner_id=key, org_id=key, public_key_fingerprint="metadata-only"))
        db.flush()
        db.add(DataSource(source_id="source", source_code="source", source_name="发电量连接器", owner_org_id="provider", source_type="ENTERPRISE_CONNECTOR", connector_type="TRUSTED_DATA_SPACE_CONNECTOR", security_domain="electricity"))
        db.flush()
        db.add(DataAsset(asset_id="asset", source_id="source", owner_org_id="provider", asset_code="GENERATION", asset_name="发电量", asset_type="ELECTRICITY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", current_version_id="version", status="ACTIVE", metadata_json={"domain": "electricity", "resource_id": "generation"}))
        db.flush()
        db.add(DataAssetVersion(version_id="version", asset_id="asset", version_no=1, schema_version="metadata-only", data_ref="connector://provider/generation/versions/1", data_hash="a" * 64, immutable_hash="b" * 64))
        db.add(AccessRule(owner_org_id="provider", rule_code="generation-average", version_no=1, energy_domain="electricity", resource_id="generation", function_code="average", mode="AUTO_CALL", scope_json={}, limits_json={"max_duration_days": 31}, status="ACTIVE", rule_hash="c" * 64))
        db.commit()
    return "applicant"


def _conditions(**overrides):
    return {"provider_org_id": "provider", "energy_domain": "electricity", "resource": "generation", "function": "average", "start_date": "2026-06-01", "end_date": "2026-06-10", "region": "东部片区", "decimals": 2, **overrides}


def _grant(db, *, scope=None, fields=None):
    now = trusted_query.utc_now()
    grant = DataUsageRequest(asset_id="asset", asset_version_id="version", applicant_user_id="applicant", applicant_org_id="applicant", provider_org_id="provider", applicant_did="did:test:applicant", provider_did="did:test:provider", purpose="CONTROLLED_AGGREGATE_QUERY", usage_mode="AGGREGATE_ONLY", requested_scope_json=scope or {}, requested_fields_json=fields or ["日期", "地区", "发电量"], terms_json={"raw_data_export": False}, duration_days=30, expires_at=now + timedelta(days=30), status="APPROVED", state_version=1, request_fingerprint=sha256_json(scope or {}), submitted_at=now, trace_id="review-metadata-only")
    db.add(grant)
    db.commit()
    return grant


def _execute(db, grant, user, key="one", **changes):
    conditions = _conditions(authorization_id=grant.request_id, **changes)
    confirmation = trusted_query.ConfirmRequest(**conditions)
    token = trusted_query._issue_confirmation_token(trusted_query._confirmation_claims(confirmation, user))
    return trusted_query.execute_query(trusted_query.ExecuteRequest(**conditions, confirmation_token=token), BackgroundTasks(), key, user, db)


def _bind_agreement(db, grant, *, max_uses=1, use_count=0):
    """Mirror the agreement created when the ordinary usage form is approved."""
    now = trusted_query.utc_now()
    contract = DataContract(provider_org_id=grant.provider_org_id, consumer_type=grant.applicant_org_id, purpose=grant.purpose, data_refs_json=[], policy_json={"constraint": {"data_scope": grant.requested_scope_json}}, policy_hash="d" * 64, status="ACTIVE", valid_from=now, expires_at=grant.expires_at)
    db.add(contract)
    db.flush()
    agreement = DataSpaceAgreement(contract_id=contract.contract_id, provider_org_id=grant.provider_org_id, consumer_org_id=grant.applicant_org_id, provider_did=grant.provider_did, consumer_did=grant.applicant_did, state="ACTIVE", requested_purpose=grant.purpose, algorithm_code="CONTROLLED_DATA_USAGE_V1", offered_policy_hash=contract.policy_hash, negotiated_policy_hash=contract.policy_hash, valid_from=now, expires_at=grant.expires_at, max_uses=max_uses, use_count=use_count, trace_id="review-bound-agreement")
    db.add(agreement)
    db.flush()
    grant.contract_id, grant.agreement_id = contract.contract_id, agreement.agreement_id
    db.commit()
    return agreement


@pytest.mark.parametrize(("question", "resource", "function"), [
    ("查一下6月份各地区的电网负荷，用于运行监测", "load", "sum"),
    ("查询2026年6月电力交易成交均价", "price", "average"),
])
def test_manual_shortcuts_match_the_published_single_metric_contract(question, resource, function):
    parsed = trusted_query._manual_parse(question)
    assert parsed.energy_domain == "electricity"
    assert parsed.resource == resource
    assert parsed.function == function


@pytest.mark.parametrize("function", ["中位数", "同比", "环比", "增长率", "按地区", "阈值", "PSI", "MPC"])
def test_unsupported_manual_functions_request_input_instead_of_raising(function):
    parsed = trusted_query._manual_parse(f"2026年6月电力发电量{function}")
    assert parsed.function is None


@pytest.mark.parametrize("question", [
    "2026年6月电力交易的成交均价和成交量，用于市场监测",
    "2026年6月煤炭库存和供应量平均值",
    "2026年6月煤炭库存平均值和最高值",
    "2026年6月煤炭和天然气价格平均值",
])
def test_ambiguous_manual_queries_do_not_drop_part_of_the_request(question):
    parsed = trusted_query._manual_parse(question)
    assert not all((parsed.energy_domain, parsed.resource, parsed.function, parsed.start_date, parsed.end_date))


def test_expired_rule_auto_grant_is_reissued_without_changing_history(metadata, monkeypatch):
    clock = [datetime(2026, 10, 24, 12)]
    monkeypatch.setattr(trusted_query, "utc_now", lambda: clock[0])
    with SessionLocal() as db:
        user = db.get(User, metadata)
        # Resolve takes the shared query scope, without display-only precision.
        def resolve():
            conditions = _conditions()
            conditions.pop("decimals")
            conditions.update(start_date=date(2026, 6, 1), end_date=date(2026, 6, 10))
            return trusted_query._resolve_authorization(db, authorization_id=None, user=user, **conditions)
        old, _ = resolve()
        db.commit()
        old_expiry = old.expires_at
        clock[0] += timedelta(days=2)
        fresh, _ = resolve()
        db.commit()
        again, _ = resolve()
        assert fresh.request_id != old.request_id
        assert again.request_id == fresh.request_id
        assert old.status == "APPROVED" and old.expires_at == old_expiry
        assert fresh.expires_at > clock[0]
        assert db.scalar(select(func.count(DataUsageRequest.request_id))) == 2


@pytest.mark.parametrize(("status", "source"), [("REVOKED", "SUBJECT_APPROVED_RULE"), ("REJECTED", "SUBJECT_APPROVED_RULE"), ("APPROVED", "MANUAL")])
def test_auto_resolution_does_not_revive_revoked_or_manual_grants(metadata, monkeypatch, status, source):
    clock = [datetime(2026, 10, 24, 12)]
    monkeypatch.setattr(trusted_query, "utc_now", lambda: clock[0])
    with SessionLocal() as db:
        user = db.get(User, metadata)
        conditions = _conditions()
        conditions.pop("decimals")
        conditions.update(start_date=date(2026, 6, 1), end_date=date(2026, 6, 10))
        old, _ = trusted_query._resolve_authorization(db, authorization_id=None, user=user, **conditions)
        old.status = status
        old.terms_json = {**old.terms_json, "authorization_source": source}
        db.commit()
        clock[0] += timedelta(days=2)
        with pytest.raises(HTTPException) as denied:
            trusted_query._resolve_authorization(db, authorization_id=None, user=user, **conditions)
        assert denied.value.status_code == 403
        assert db.scalar(select(func.count(DataUsageRequest.request_id))) == 1


@pytest.mark.parametrize(("scope", "fields", "changes"), [
    ({"start_date": "2026-06-02"}, None, {}),
    ({"end_date": "2026-06-09"}, None, {}),
    ({"region": "西部片区"}, None, {}),
    ({"region": "东部片区"}, None, {"region": None}),
    ({"function": "sum"}, None, {}),
    ({"functions": ["sum"]}, None, {}),
    ({}, ["generation", "sum"], {}),
])
def test_explicit_grant_scope_is_enforced_before_queuing(metadata, scope, fields, changes):
    with SessionLocal() as db:
        grant = _grant(db, scope=scope, fields=fields)
        user = db.get(User, metadata)
        with pytest.raises(HTTPException) as denied:
            _execute(db, grant, user, **changes)
        assert denied.value.status_code == 403
        assert db.scalar(select(func.count(TrustedQueryTask.task_id))) == 0


def test_legacy_column_names_are_not_misread_as_function_restrictions(metadata):
    with SessionLocal() as db:
        grant = _grant(db)
        user = db.get(User, metadata)
        response = _execute(db, grant, user)
        assert response["status"] == "QUEUED"


def test_query_inside_declared_scope_keeps_the_grant_unchanged(metadata):
    with SessionLocal() as db:
        scope = {"start_date": "2026-06-01", "end_date": "2026-06-30", "region": "东部片区", "functions": ["average"], "max_uses": "01"}
        grant = _grant(db, scope=scope, fields=["generation", "average"])
        user = db.get(User, metadata)
        original = (grant.state_version, grant.updated_at, dict(grant.requested_scope_json))
        submitted = _execute(db, grant, user)
        trusted_query._revalidate_query_dispatch(db, task=db.get(TrustedQueryTask, submitted["task_id"]))
        db.refresh(grant)
        assert (grant.state_version, grant.updated_at, grant.requested_scope_json) == original


def test_matching_replay_cannot_bypass_a_narrowed_grant(metadata):
    with SessionLocal() as db:
        grant = _grant(db)
        user = db.get(User, metadata)
        _execute(db, grant, user)
        grant.requested_scope_json = {"region": "西部片区"}
        db.commit()
        with pytest.raises(HTTPException) as denied:
            _execute(db, grant, user)
        assert denied.value.status_code == 403
        assert db.scalar(select(func.count(TrustedQueryTask.task_id))) == 1


def test_explicit_use_budget_preserves_matching_idempotent_replay(metadata):
    with SessionLocal() as db:
        grant = _grant(db, scope={"max_uses": 1})
        user = db.get(User, metadata)
        first = _execute(db, grant, user)
        replay = _execute(db, grant, user)
        assert replay["task_id"] == first["task_id"]
        assert replay["idempotent_replay"] is True
        with pytest.raises(HTTPException) as denied:
            _execute(db, grant, user, "another")
        assert denied.value.status_code == 403
        assert db.scalar(select(func.count(TrustedQueryTask.task_id))) == 1


@pytest.mark.parametrize(("scope", "agreement_limit"), [({}, 1), ({"max_uses": 5}, 1), ({"max_uses": 1}, 5)])
def test_bound_agreement_default_and_explicit_budgets_both_apply(metadata, scope, agreement_limit):
    with SessionLocal() as db:
        grant = _grant(db, scope=scope)
        agreement = _bind_agreement(db, grant, max_uses=agreement_limit)
        user = db.get(User, metadata)
        first = _execute(db, grant, user)
        assert _execute(db, grant, user)["task_id"] == first["task_id"]
        with pytest.raises(HTTPException) as denied:
            _execute(db, grant, user, "another")
        assert denied.value.status_code == 403
        db.refresh(agreement)
        assert agreement.use_count == 1
        assert agreement.state == ("CONSUMED" if agreement_limit == 1 else "ACTIVE")
        trusted_query._revalidate_query_dispatch(db, task=db.get(TrustedQueryTask, first["task_id"]))


def test_bound_agreement_use_consumed_elsewhere_cannot_be_reused(metadata):
    with SessionLocal() as db:
        grant = _grant(db)
        _bind_agreement(db, grant, use_count=1)
        with pytest.raises(HTTPException) as denied:
            _execute(db, grant, db.get(User, metadata))
        assert denied.value.status_code == 403
        assert db.scalar(select(func.count(TrustedQueryTask.task_id))) == 0


@pytest.mark.parametrize("same_key", [True, False])
def test_bound_agreement_concurrent_queries_reserve_one_use(metadata, same_key):
    with SessionLocal() as db:
        grant = _grant(db)
        agreement_id = _bind_agreement(db, grant).agreement_id
        grant_id = grant.request_id
    barrier = Barrier(2)
    def submit(index):
        with SessionLocal() as db:
            user = db.get(User, metadata)
            grant = db.get(DataUsageRequest, grant_id)
            barrier.wait(timeout=10)
            try:
                result = _execute(db, grant, user, "same" if same_key else f"separate-{index}")
                return 202, result["task_id"]
            except HTTPException as error:
                return error.status_code, None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert sorted(code for code, _ in results) == ([202, 202] if same_key else [202, 403])
    if same_key:
        assert results[0][1] == results[1][1]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(TrustedQueryTask.task_id))) == 1
        assert db.get(DataSpaceAgreement, agreement_id).use_count == 1


@pytest.mark.parametrize(("location", "allowed"), [(None, False), ("", False), ("全部地区", False), ("西部片区", False), ("东部片区", True)])
@pytest.mark.parametrize("source", ["limits_json", "scope_json"])
def test_location_limited_auto_rule_requires_an_explicit_matching_region(metadata, location, allowed, source):
    with SessionLocal() as db:
        rule = db.scalar(select(AccessRule))
        setattr(rule, source, {**getattr(rule, source), "region": "东部片区"})
        db.commit()
        user = db.get(User, metadata)
        conditions = _conditions(region=location)
        conditions.pop("decimals")
        conditions.update(start_date=date(2026, 6, 1), end_date=date(2026, 6, 10))
        if allowed:
            grant, _ = trusted_query._resolve_authorization(db, authorization_id=None, user=user, **conditions)
            assert grant.requested_scope_json["region"] == location
        else:
            with pytest.raises(HTTPException) as denied:
                trusted_query._resolve_authorization(db, authorization_id=None, user=user, **conditions)
            assert denied.value.status_code == 403
            assert db.scalar(select(func.count(DataUsageRequest.request_id))) == 0


def test_concurrent_new_queries_cannot_exceed_explicit_use_budget(metadata):
    with SessionLocal() as db:
        grant_id = _grant(db, scope={"max_uses": 1}).request_id
    barrier = Barrier(2)
    def submit(index):
        with SessionLocal() as db:
            user = db.get(User, metadata)
            grant = db.get(DataUsageRequest, grant_id)
            barrier.wait(timeout=10)
            try:
                _execute(db, grant, user, f"concurrent-{index}")
                return 202
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [202, 403]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(TrustedQueryTask.task_id))) == 1


@pytest.mark.parametrize("scope", [{"max_uses": 1}, {}])
def test_concurrent_matching_replays_share_the_reserved_use(metadata, scope):
    with SessionLocal() as db:
        grant_id = _grant(db, scope=scope).request_id
    barrier = Barrier(2)
    def submit(_index):
        with SessionLocal() as db:
            user = db.get(User, metadata)
            grant = db.get(DataUsageRequest, grant_id)
            barrier.wait(timeout=10)
            return _execute(db, grant, user)["task_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        task_ids = list(pool.map(submit, range(2)))
    assert task_ids[0] == task_ids[1]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(TrustedQueryTask.task_id))) == 1


@pytest.mark.parametrize(("region", "blocked"), [(None, True), ("", True), ("东部片区", True), ("西部片区", False)])
def test_regional_forbidden_rule_still_blocks_queries_covering_that_region(metadata, region, blocked):
    with SessionLocal() as db:
        rule = db.scalar(select(AccessRule))
        rule.mode = "FORBIDDEN"
        rule.limits_json = {**rule.limits_json, "region": "东部片区"}
        grant = _grant(db)
        user = db.get(User, metadata)
        if blocked:
            with pytest.raises(HTTPException) as denied:
                _execute(db, grant, user, region=region)
            assert denied.value.status_code == 403
        else:
            assert _execute(db, grant, user, region=region)["status"] == "QUEUED"


def test_auto_rule_duration_is_checked_before_an_approval_is_created(metadata):
    with SessionLocal() as db:
        user = db.get(User, metadata)
        conditions = _conditions()
        conditions.pop("decimals")
        conditions.update(start_date=date(2026, 6, 1), end_date=date(2026, 7, 31))
        with pytest.raises(HTTPException) as denied:
            trusted_query._resolve_authorization(db, authorization_id=None, user=user, **conditions)
        assert denied.value.status_code == 403
        assert db.scalar(select(func.count(DataUsageRequest.request_id))) == 0


def test_dispatch_revalidates_declared_scope_after_a_task_is_queued(metadata):
    with SessionLocal() as db:
        grant = _grant(db)
        user = db.get(User, metadata)
        submitted = _execute(db, grant, user)
        grant.requested_scope_json = {"region": "西部片区"}
        db.commit()
        with pytest.raises(trusted_query.TrustedQueryExecutionError) as denied:
            trusted_query._revalidate_query_dispatch(db, task=db.get(TrustedQueryTask, submitted["task_id"]))
        assert denied.value.code == "AUTHORIZATION_SCOPE_CHANGED"


def test_exchange_review_capability_intersects_current_account_permission(metadata):
    with SessionLocal() as db:
        user = db.get(User, "exchange")
        assert trust_space.role_context(db, user)["role_capabilities"]["can_review_inbound_requests"] is True
        assert trust_space.contextual_help(db, user, "authorizations")["role_capabilities"]["can_review_inbound_requests"] is True
        user.permissions_json = []
        assert trust_space.role_context(db, user)["role_capabilities"]["can_review_inbound_requests"] is False
        assert trust_space.contextual_help(db, user, "authorizations")["role_capabilities"]["can_review_inbound_requests"] is False
        assert trust_space.ROLE_CAPABILITIES["EXCHANGE"]["can_review_inbound_requests"] is True


@pytest.mark.parametrize("domain", ["electricity", "coal", "heat", "gas", "oil", None])
@pytest.mark.parametrize("can_create", [True, False])
def test_exchange_settlement_capability_and_workbench_action_follow_domain_and_permission(metadata, domain, can_create):
    with SessionLocal() as db:
        user = db.get(User, "exchange")
        organization = db.get(Organization, user.org_id)
        organization.energy_domain = domain
        if not can_create:
            user.permissions_json = [item for item in user.permissions_json if item != "CREATE_COMPUTE_TASK"]
        db.commit()
        expected_settlement = domain == "electricity" and can_create
        assert trust_space.role_context(db, user)["role_capabilities"]["can_create_settlement"] is expected_settlement
        assert trust_space.contextual_help(db, user, "authorizations")["role_capabilities"]["can_create_settlement"] is expected_settlement
        actions = trust_space.workbench(db, user)["quick_action_items"]
        creation = next(item for item in actions if item["code"] in {"CREATE_SETTLEMENT", "CREATE_CONTROLLED_QUERY"})
        assert creation["allowed"] is can_create
        if domain == "electricity":
            assert (creation["code"], creation["label"], creation["path"]) == ("CREATE_SETTLEMENT", "发起结算任务", "/trusted-space/mpc/new")
        else:
            assert (creation["code"], creation["label"], creation["path"]) == ("CREATE_CONTROLLED_QUERY", "发起智能计算", "/trusted-space/query")
        if not can_create:
            assert creation["disabled_reason"]
