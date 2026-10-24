"""Owner confirmation persists a single-use grant; worker access is revalidated."""
from datetime import timedelta

from fastapi import BackgroundTasks, HTTPException
import pytest
from sqlalchemy import func, select

from app.database import SessionLocal, engine
from app.models import AccessRule, Base, DataRequestItem, DataUsageRequest, DidIdentity, Organization, TrustedQueryTask, User, utc_now
from app.routers import trusted_query
from app.trust_models import DataAsset, DataAssetVersion, DataSource


@pytest.fixture(autouse=True)
def reset_test_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(params=[("coal", "COAL_ENTERPRISE", "production"), ("heat", "HEAT_ENTERPRISE", "supply"), ("gas", "GAS_ENTERPRISE", "supply"), ("oil", "OIL_ENTERPRISE", "production")])
def owned_records(request):
    domain, role, resource = request.param
    with SessionLocal() as db:
        db.add(Organization(org_id="owner", org_name=domain, org_type=role, energy_domain=domain))
        db.flush()
        user = User(user_id="owner-user", org_id="owner", username="owner", password_hash="unused", display_name="owner", role_code=role, permissions_json=["VIEW_DATA", "APPROVE_AUTHORIZATION", "CREATE_COMPUTE_TASK", "VIEW_COMPUTE_RESULT"])
        db.add(user)
        db.add(DidIdentity(did_id="did:test:owner", owner_type="ORG", owner_id="owner", org_id="owner", public_key_fingerprint="metadata-only"))
        db.add(DataSource(source_id="source", source_code="source", source_name="owner-node", owner_org_id="owner", source_type="ENTERPRISE_CONNECTOR", security_domain=domain))
        db.flush()
        db.add(DataAsset(asset_id="owned-asset", source_id="source", owner_org_id="owner", asset_code=resource, asset_name=resource, asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", current_version_id="version", status="ACTIVE", metadata_json={"domain": domain, "resource_id": resource}))
        db.flush()
        db.add(DataAssetVersion(version_id="version", asset_id="owned-asset", version_no=1, schema_version="metadata-only", data_ref=f"connector://owner/{resource}/versions/1", data_hash="a" * 64, immutable_hash="b" * 64))
        db.add(AccessRule(owner_org_id="owner", rule_code="external-forbidden", version_no=1, energy_domain=domain, resource_id=resource, function_code="yoy", mode="FORBIDDEN", scope_json={}, limits_json={}, status="ACTIVE", rule_hash="c" * 64))
        db.commit()
        conditions = {"provider_org_id": "owner", "asset_id": "owned-asset", "energy_domain": domain, "resource": resource, "function": "yoy", "start_date": "2026-06-01", "end_date": "2026-06-30", "decimals": 2}
        yield db, user, conditions


def _confirm(db, user, conditions):
    return trusted_query.confirm_query(trusted_query.ConfirmRequest(**conditions), user, db)


def _execute(db, user, conditions, confirmed, key="owner-one"):
    resolved = {**conditions, **{key: confirmed[key] for key in ("authorization_id", "provider_org_id", "asset_id")}}
    return trusted_query.execute_query(trusted_query.ExecuteRequest(**resolved, confirmation_token=confirmed["confirmation_token"]), BackgroundTasks(), key, user, db)


def test_four_non_electric_owners_can_confirm_queue_and_replay_once(owned_records):
    db, user, conditions = owned_records
    confirmed = _confirm(db, user, conditions)
    grant = db.get(DataUsageRequest, confirmed["authorization_id"])
    assert grant.provider_org_id == grant.applicant_org_id == user.org_id
    assert grant.applicant_user_id == user.user_id
    assert grant.terms_json["authorization_source"] == "SELF_OWNED_QUERY"
    assert grant.requested_scope_json == {"start_date": "2025-06-01", "end_date": "2026-06-30", "region": None, "max_uses": 1, "output_mode": "AGGREGATE_ONLY", "raw_data_export": False}
    assert timedelta(minutes=14) < grant.expires_at - utc_now() <= timedelta(minutes=15)
    queued = _execute(db, user, conditions, confirmed)
    replay = _execute(db, user, conditions, confirmed)
    assert replay["idempotent_replay"] is True and replay["task_id"] == queued["task_id"]
    assert db.scalar(select(func.count()).select_from(TrustedQueryTask)) == 1
    task = db.get(TrustedQueryTask, queued["task_id"])
    assert task.canonical_payload_json["asset_id"] == "owned-asset"
    item = db.get(DataRequestItem, task.request_item_id)
    assert item.matched_rule_id is None
    actor, resolved, asset, version, item = trusted_query._revalidate_query_dispatch(db, task=task)
    signed = trusted_query._connector_query_payload(task, resolved, version, item)
    assert signed["dataset_version"] == 1 and signed["comparison_start_date"] == "2025-06-01"
    with pytest.raises(HTTPException) as exhausted:
        _execute(db, user, conditions, confirmed, key="owner-two")
    assert exhausted.value.status_code == 403


def test_owner_comparison_union_cannot_be_reconfirmed_as_another_current_period(owned_records):
    db, user, conditions = owned_records
    confirmed = _confirm(db, user, conditions)
    different = {**conditions, "authorization_id": confirmed["authorization_id"], "start_date": "2025-06-01", "end_date": "2025-06-30", "function": "yoy"}
    with pytest.raises(HTTPException) as denied:
        _confirm(db, user, different)
    assert denied.value.status_code == 403
    assert db.scalar(select(TrustedQueryTask.task_id)) is None


@pytest.mark.parametrize("mutation", ["permissions", "identity", "version", "revoked", "asset", "source"])
def test_owner_access_is_revalidated_before_execute_and_worker_dispatch(owned_records, mutation):
    db, user, conditions = owned_records
    confirmed = _confirm(db, user, conditions)
    queued = _execute(db, user, conditions, confirmed)
    task = db.get(TrustedQueryTask, queued["task_id"])
    if mutation == "permissions":
        user.permissions_json = ["CREATE_COMPUTE_TASK", "VIEW_COMPUTE_RESULT"]
    elif mutation == "identity":
        db.get(DidIdentity, "did:test:owner").credential_status = "REVOKED"
    elif mutation == "version":
        db.add(DataAssetVersion(version_id="version-two", asset_id="owned-asset", version_no=2, schema_version="metadata-only", data_ref="connector://owner/current/versions/2", data_hash="d" * 64, immutable_hash="e" * 64))
        db.get(DataAsset, "owned-asset").current_version_id = "version-two"
    elif mutation == "revoked":
        db.get(DataUsageRequest, confirmed["authorization_id"]).status = "REVOKED"
    elif mutation == "asset":
        db.get(DataAsset, "owned-asset").status = "DISABLED"
    else:
        db.get(DataSource, "source").status = "DISABLED"
    db.commit()
    with pytest.raises(HTTPException) as execution_denied:
        _execute(db, user, conditions, confirmed)
    assert execution_denied.value.status_code in {403, 409}
    with pytest.raises(trusted_query.TrustedQueryExecutionError):
        trusted_query._revalidate_query_dispatch(db, task=task)


def test_owner_confirmation_does_not_create_a_grant_for_another_subject_or_admin(owned_records):
    db, user, conditions = owned_records
    with pytest.raises(HTTPException) as external:
        _confirm(db, user, {**conditions, "provider_org_id": "another-owner"})
    assert external.value.status_code == 403
    with pytest.raises(HTTPException) as missing_asset:
        _confirm(db, user, {key: value for key, value in conditions.items() if key != "asset_id"})
    assert missing_asset.value.status_code == 422
    user.role_code = "ADMIN"
    db.commit()
    with pytest.raises(HTTPException) as admin:
        _confirm(db, user, conditions)
    assert admin.value.status_code == 403
    assert db.scalar(select(DataUsageRequest.request_id)) is None


def test_owner_cannot_execute_without_the_confirmed_authorization_id(owned_records):
    db, user, conditions = owned_records
    confirmed = _confirm(db, user, conditions)
    with pytest.raises(HTTPException) as denied:
        trusted_query.execute_query(trusted_query.ExecuteRequest(**conditions, confirmation_token=confirmed["confirmation_token"]), BackgroundTasks(), "missing-grant", user, db)
    assert denied.value.status_code == 403
    assert db.scalar(select(TrustedQueryTask.task_id)) is None
