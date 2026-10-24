from datetime import date, timedelta

from fastapi import BackgroundTasks, HTTPException
import pytest
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.models import Base, DataRequestItem, DataUsageRequest, Organization, TrustedQueryTask, User, utc_now
from app.routers import trusted_query
from app.services.query_periods import comparison_period
from app.trust_models import DataAsset, DataAssetVersion, DataSource


@pytest.fixture(autouse=True)
def reset_test_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def records():
    with SessionLocal() as db:
        for org_id, role in (("provider", "GENERATOR"), ("applicant", "EXCHANGE")):
            db.add(Organization(org_id=org_id, org_name=org_id, org_type=role, energy_domain="electricity"))
        db.flush()
        user = User(user_id="applicant", org_id="applicant", username="applicant", password_hash="unused", display_name="applicant", role_code="EXCHANGE", permissions_json=["CREATE_COMPUTE_TASK", "VIEW_COMPUTE_RESULT"])
        db.add(user)
        db.add(DataSource(source_id="source", source_code="source", source_name="metadata", owner_org_id="provider", source_type="ENTERPRISE_CONNECTOR", security_domain="electricity"))
        db.flush()
        db.add(DataAsset(asset_id="asset", source_id="source", owner_org_id="provider", asset_code="GENERATION", asset_name="发电量", asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", current_version_id="version", status="ACTIVE", metadata_json={"domain": "electricity", "resource_id": "generation"}))
        db.flush()
        db.add(DataAssetVersion(version_id="version", asset_id="asset", version_no=1, schema_version="metadata-only", data_ref="connector://provider/generation/versions/1", data_hash="a" * 64, immutable_hash="b" * 64))
        db.flush()
        grant = DataUsageRequest(request_id="comparison-grant", asset_id="asset", asset_version_id="version", applicant_user_id="applicant", applicant_org_id="applicant", provider_org_id="provider", applicant_did="did:test:applicant", provider_did="did:test:provider", purpose="CONTROLLED_AGGREGATE_QUERY", usage_mode="MPC_AGGREGATE", requested_scope_json={"start_date": "2025-01-01", "end_date": "2026-12-31", "max_uses": 3}, requested_fields_json=["summary"], terms_json={}, duration_days=30, expires_at=utc_now() + timedelta(days=30), status="APPROVED", trace_id="comparison-metadata-only")
        db.add(grant)
        db.commit()
        yield db, grant, user


def conditions(function="yoy"):
    return {"authorization_id": "comparison-grant", "provider_org_id": "provider", "energy_domain": "electricity", "resource": "generation", "function": function, "start_date": "2026-06-01", "end_date": "2026-06-30", "region": None, "decimals": 2}


@pytest.mark.parametrize(("function", "start", "end", "expected"), [
    ("mom", "2024-03-01", "2024-03-31", ("2024-02-01", "2024-02-29")),
    ("yoy", "2024-02-01", "2024-02-29", ("2023-02-01", "2023-02-28")),
    ("yoy", "2024-02-29", "2024-02-29", ("2023-02-28", "2023-02-28")),
    ("mom", "2026-01-12", "2026-01-22", ("2025-12-12", "2025-12-22")),
    ("mom", "2026-04-01", "2026-06-30", ("2026-03-01", "2026-05-31")),
])
def test_calendar_comparison_preserves_whole_months_and_clips_leap_days(function, start, end, expected):
    assert tuple(day.isoformat() for day in comparison_period(function, date.fromisoformat(start), date.fromisoformat(end))) == expected


@pytest.mark.parametrize("function", ["yoy", "mom"])
def test_comparison_baseline_must_be_covered_at_confirmation_and_execution(records, function):
    db, grant, user = records
    grant.requested_scope_json = {"start_date": "2026-06-01", "end_date": "2026-06-30", "max_uses": 3}
    db.commit()
    request = trusted_query.ConfirmRequest(**conditions(function))
    with pytest.raises(HTTPException) as denied:
        trusted_query.confirm_query(request, user, db)
    assert denied.value.status_code == 403 and "基期" in str(denied.value.detail)
    token = trusted_query._issue_confirmation_token(trusted_query._confirmation_claims(request, user))
    with pytest.raises(HTTPException) as execution_denied:
        trusted_query.execute_query(trusted_query.ExecuteRequest(**conditions(function), confirmation_token=token), BackgroundTasks(), "outside-baseline", user, db)
    assert execution_denied.value.status_code == 403
    assert db.scalar(select(TrustedQueryTask.task_id)) is None


def test_frozen_baseline_is_signed_and_cannot_be_rebound_during_dispatch(records):
    db, _grant, user = records
    confirmation = trusted_query.confirm_query(trusted_query.ConfirmRequest(**conditions()), user, db)
    response = trusted_query.execute_query(trusted_query.ExecuteRequest(**conditions(), confirmation_token=confirmation["confirmation_token"]), BackgroundTasks(), "comparison-good", user, db)
    task = db.get(TrustedQueryTask, response["task_id"])
    assert task.canonical_payload_json["comparison_start_date"] == "2025-06-01"
    assert task.canonical_payload_json["comparison_end_date"] == "2025-06-30"
    request_item = db.get(DataRequestItem, task.request_item_id)
    assert request_item.scope_json["comparison_start_date"] == "2025-06-01"
    actor, grant, _asset, version, item = trusted_query._revalidate_query_dispatch(db, task=task)
    signed = trusted_query._connector_query_payload(task, grant, version, item)
    assert signed["comparison_start_date"] == "2025-06-01" and signed["comparison_end_date"] == "2025-06-30"
    task.canonical_payload_json = {**task.canonical_payload_json, "comparison_start_date": "2025-05-01"}
    db.commit()
    with pytest.raises(trusted_query.TrustedQueryExecutionError) as tampered:
        trusted_query._revalidate_query_dispatch(db, task=task)
    assert tampered.value.code == "AUTHORIZATION_SCOPE_CHANGED"


def test_non_comparison_claims_and_connector_canonicalization_keep_legacy_shape(records):
    db, grant, user = records
    request = trusted_query.ConfirmRequest(**conditions("average"))
    claims = trusted_query._confirmation_claims(request, user)
    assert "comparison_start_date" not in claims and "comparison_end_date" not in claims
    from app.services.privacy_attestation import canonical_connector_request_payload
    assert canonical_connector_request_payload({"function": "average", "comparison_start_date": None, "comparison_end_date": None, "minimum_record_count": None}) == {"function": "average"}


@pytest.mark.parametrize(("field", "value", "changed"), [("hour", 6, 7), ("threshold", 100, 150), ("group_by", "region", "record_date")])
def test_non_default_fixed_function_parameters_are_locked_by_confirmation(records, field, value, changed):
    db, grant, user = records
    original = {**conditions("average"), field: value}
    confirmed = trusted_query.confirm_query(trusted_query.ConfirmRequest(**original), user, db)
    tampered = {**original, field: changed, "confirmation_token": confirmed["confirmation_token"]}
    with pytest.raises(HTTPException) as denied:
        trusted_query.execute_query(trusted_query.ExecuteRequest(**tampered), BackgroundTasks(), "changed-" + field, user, db)
    assert denied.value.status_code == 409
    assert db.scalar(select(TrustedQueryTask.task_id)) is None
    token = trusted_query._issue_confirmation_token(trusted_query._confirmation_claims(trusted_query.ConfirmRequest(**original), user))
    trusted_query._verify_confirmation_token(token, trusted_query.ExecuteRequest(**original, confirmation_token=token), user)


def test_selected_asset_is_bound_to_the_approved_grant_and_confirmation(records):
    db, grant, user = records
    with pytest.raises(HTTPException) as mismatch:
        trusted_query.confirm_query(trusted_query.ConfirmRequest(**conditions("average"), asset_id="another-asset"), user, db)
    assert mismatch.value.status_code == 403
    confirmation_request = trusted_query.ConfirmRequest(**conditions("average"), asset_id="asset")
    confirmation = trusted_query.confirm_query(confirmation_request, user, db)
    assert confirmation["authorization_id"] == grant.request_id and confirmation["asset_id"] == "asset"
    assert trusted_query._confirmation_claims(confirmation_request, user)["asset_id"] == "asset"
    token = confirmation["confirmation_token"]
    with pytest.raises(HTTPException) as changed:
        trusted_query._verify_confirmation_token(token, trusted_query.ExecuteRequest(**conditions("average"), asset_id="another-asset", confirmation_token=token), user)
    assert changed.value.status_code == 409


def test_execution_rejects_changed_provider_before_normalizing_resolved_grant(records):
    db, grant, user = records
    confirmed = trusted_query.confirm_query(trusted_query.ConfirmRequest(**conditions("average")), user, db)
    changed = {**conditions("average"), "provider_org_id": "another-provider", "confirmation_token": confirmed["confirmation_token"]}
    with pytest.raises(HTTPException) as denied:
        trusted_query.execute_query(trusted_query.ExecuteRequest(**changed), BackgroundTasks(), "provider-change", user, db)
    assert denied.value.status_code == 403
    assert db.scalar(select(TrustedQueryTask.task_id)) is None
