"""Rule auto comparisons require one rule covering both complete periods and span."""
from fastapi import BackgroundTasks, HTTPException
import pytest
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.models import AccessRule, Base, DataUsageRequest, DidIdentity, Organization, TrustedQueryTask, User
from app.routers import trusted_query
from app.trust_models import DataAsset, DataAssetVersion, DataSource


@pytest.fixture(autouse=True)
def reset_test_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(params=["yoy", "mom"])
def records(request):
    with SessionLocal() as db:
        for org_id, role in (("provider", "GENERATOR"), ("regulator", "REGULATOR")):
            db.add(Organization(org_id=org_id, org_name=org_id, org_type=role, energy_domain="electricity"))
            db.flush()
            db.add(DidIdentity(did_id=f"did:test:{org_id}", owner_type="ORG", owner_id=org_id, org_id=org_id, public_key_fingerprint="metadata-only"))
        user = User(user_id="regulator", org_id="regulator", username="regulator", password_hash="unused", display_name="regulator", role_code="REGULATOR", permissions_json=["CREATE_COMPUTE_TASK", "VIEW_COMPUTE_RESULT", "CREATE_CROSS_ENERGY_QUERY"])
        db.add(user)
        db.add(DataSource(source_id="source", source_code="source", source_name="metadata", owner_org_id="provider", source_type="ENTERPRISE_CONNECTOR", security_domain="electricity"))
        db.flush()
        db.add(DataAsset(asset_id="asset", source_id="source", owner_org_id="provider", asset_code="load", asset_name="负荷", asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", current_version_id="version", status="ACTIVE", metadata_json={"domain": "electricity", "resource_id": "load"}))
        db.flush()
        db.add(DataAssetVersion(version_id="version", asset_id="asset", version_no=1, schema_version="metadata-only", data_ref="connector://provider/load/versions/1", data_hash="a" * 64, immutable_hash="b" * 64))
        rule = AccessRule(rule_id="comparison-rule", owner_org_id="provider", rule_code="load-comparison", version_no=1, energy_domain="electricity", asset_id="asset", resource_id="load", function_code=request.param, mode="AUTO_CALL", scope_json={"start_date": "2025-01-01", "end_date": "2026-09-30", "region": "东部片区"}, limits_json={"max_duration_days": 400, "minimum_record_count": 5, "output_mode": "AGGREGATE_ONLY"}, status="ACTIVE", rule_hash="c" * 64)
        db.add(rule)
        db.commit()
        conditions = {"provider_org_id": "provider", "asset_id": "asset", "energy_domain": "electricity", "resource": "load", "function": request.param, "start_date": "2026-06-01", "end_date": "2026-06-03", "region": "东部片区", "decimals": 2}
        yield db, user, rule, conditions


def confirm(db, user, conditions):
    return trusted_query.confirm_query(trusted_query.ConfirmRequest(**conditions), user, db)


def execute(db, user, conditions, confirmed, key="rule-comparison"):
    resolved = {**conditions, "authorization_id": confirmed["authorization_id"]}
    return trusted_query.execute_query(trusted_query.ExecuteRequest(**resolved, confirmation_token=confirmed["confirmation_token"]), BackgroundTasks(), key, user, db)


def test_auto_rule_explicitly_covering_both_periods_can_confirm_execute_and_dispatch(records):
    db, user, _rule, conditions = records
    confirmed = confirm(db, user, conditions)
    grant = db.get(DataUsageRequest, confirmed["authorization_id"])
    baseline = "2025-06-01" if conditions["function"] == "yoy" else "2026-05-01"
    assert grant.requested_scope_json["start_date"] == baseline
    assert grant.requested_scope_json["end_date"] == "2026-06-03"
    assert grant.requested_scope_json["minimum_record_count"] == 5
    assert grant.terms_json["confirmed_period"] == {"start_date": "2026-06-01", "end_date": "2026-06-03", "comparison_start_date": baseline, "comparison_end_date": baseline[:-2] + "03"}
    queued = execute(db, user, conditions, confirmed)
    task = db.get(TrustedQueryTask, queued["task_id"])
    actor, authorization, asset, version, item = trusted_query._revalidate_query_dispatch(db, task=task)
    assert item.matched_rule_id == "comparison-rule"
    signed = trusted_query._connector_query_payload(task, authorization, version, item)
    assert signed["comparison_start_date"] == baseline and signed["minimum_record_count"] == 5
    assert item.scope_json["minimum_record_count"] == 5


def test_default_31_day_rule_cannot_be_widened_by_comparison_union(records):
    db, user, rule, conditions = records
    rule.limits_json = {**rule.limits_json, "max_duration_days": 31}
    db.commit()
    with pytest.raises(HTTPException) as denied:
        confirm(db, user, conditions)
    assert denied.value.status_code == 403
    assert db.scalar(select(DataUsageRequest.request_id)) is None


@pytest.mark.parametrize("constraint", ["start_date", "period_start", "end_date", "region", "asset", "function", "forbidden", "invalid_date", "granularity", "scope_output"])
def test_current_and_baseline_must_both_obey_the_same_explicit_rule(records, constraint):
    db, user, rule, conditions = records
    if constraint in {"start_date", "period_start"}:
        rule.scope_json = {**rule.scope_json, constraint: "2026-06-01"}
    elif constraint == "end_date":
        rule.limits_json = {**rule.limits_json, "end_date": "2026-06-02"}
    elif constraint == "region":
        rule.scope_json = {**rule.scope_json, "region": "西部片区"}
    elif constraint == "asset":
        rule.asset_id = "another-asset"
    elif constraint == "function":
        rule.function_code = "average"
    elif constraint == "forbidden":
        rule.mode = "FORBIDDEN"
    elif constraint == "granularity":
        rule.limits_json = {**rule.limits_json, "granularity": "HOUR"}
    elif constraint == "scope_output":
        rule.scope_json = {**rule.scope_json, "output_mode": "MODEL_INPUT"}
    else:
        rule.scope_json = {**rule.scope_json, "start_date": "invalid-date"}
    db.commit()
    with pytest.raises(HTTPException) as denied:
        confirm(db, user, conditions)
    assert denied.value.status_code == 403
    assert db.scalar(select(DataUsageRequest.request_id)) is None


def test_auto_comparison_union_cannot_be_reused_for_a_different_current_period(records):
    db, user, _rule, conditions = records
    confirmed = confirm(db, user, conditions)
    with pytest.raises(HTTPException) as denied:
        confirm(db, user, {**conditions, "authorization_id": confirmed["authorization_id"], "start_date": "2026-06-02"})
    assert denied.value.status_code == 403


@pytest.mark.parametrize("change", ["date", "duration", "revoked", "minimum"])
def test_rule_comparison_constraints_are_revalidated_before_execute_and_dispatch(records, change):
    db, user, rule, conditions = records
    confirmed = confirm(db, user, conditions)
    queued = execute(db, user, conditions, confirmed)
    task = db.get(TrustedQueryTask, queued["task_id"])
    if change == "date":
        rule.scope_json = {**rule.scope_json, "start_date": "2026-06-01"}
    elif change == "duration":
        rule.limits_json = {**rule.limits_json, "max_duration_days": 31}
    elif change == "minimum":
        rule.limits_json = {**rule.limits_json, "minimum_record_count": 6}
    else:
        rule.status = "REVOKED"
    db.commit()
    with pytest.raises(HTTPException) as denied:
        execute(db, user, conditions, confirmed)
    assert denied.value.status_code == 403
    with pytest.raises(trusted_query.TrustedQueryExecutionError):
        trusted_query._revalidate_query_dispatch(db, task=task)


def test_hour_granularity_is_checked_and_signed_for_both_comparison_periods(records):
    db, user, rule, conditions = records
    rule.limits_json = {**rule.limits_json, "granularity": "HOUR"}
    rule.scope_json = {**rule.scope_json, "hour": 6}
    db.commit()
    conditions = {**conditions, "hour": 6}
    confirmed = confirm(db, user, conditions)
    queued = execute(db, user, conditions, confirmed)
    task = db.get(TrustedQueryTask, queued["task_id"])
    actor, authorization, asset, version, item = trusted_query._revalidate_query_dispatch(db, task=task)
    assert trusted_query._connector_query_payload(task, authorization, version, item)["hour"] == 6
    with pytest.raises(HTTPException) as denied:
        confirm(db, user, {**conditions, "hour": 7})
    assert denied.value.status_code == 403
