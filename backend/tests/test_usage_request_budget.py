from datetime import timedelta

from fastapi import BackgroundTasks
import pytest

from app.database import SessionLocal, engine
from app.models import Base, DataContract, DataSpaceAgreement, DataUsageRequest, Organization, User, utc_now
from app.routers import trusted_query
from app.services.data_usage_requests import to_payload
from app.trust_models import DataAsset, DataAssetVersion, DataSource


@pytest.fixture(autouse=True)
def reset_test_database():
    """Budget projections need metadata only, never historical Vault fixtures."""
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
        user = User(user_id="applicant", org_id="applicant", username="applicant", password_hash="unused", display_name="applicant", role_code="EXCHANGE", permissions_json=["CREATE_COMPUTE_TASK"])
        db.add(user)
        db.add(DataSource(source_id="source", source_code="source", source_name="metadata", owner_org_id="provider", source_type="ENTERPRISE_CONNECTOR", security_domain="electricity"))
        db.flush()
        db.add(DataAsset(asset_id="asset", source_id="source", owner_org_id="provider", asset_code="GENERATION", asset_name="发电量", asset_type="ENERGY_METRIC", classification="ENTERPRISE_DATA_PRODUCT", sensitivity_level="L2", current_version_id="version", status="ACTIVE", metadata_json={"domain": "electricity", "resource_id": "generation"}))
        db.flush()
        db.add(DataAssetVersion(version_id="version", asset_id="asset", version_no=1, schema_version="metadata-only", data_ref="connector://provider/generation/versions/1", data_hash="a" * 64, immutable_hash="b" * 64))
        db.flush()
        now = utc_now()
        grant = DataUsageRequest(request_id="grant", asset_id="asset", asset_version_id="version", applicant_user_id="applicant", applicant_org_id="applicant", provider_org_id="provider", applicant_did="did:test:applicant", provider_did="did:test:provider", purpose="CONTROLLED_AGGREGATE_QUERY", usage_mode="MPC_AGGREGATE", requested_scope_json={}, requested_fields_json=["generation", "sum"], terms_json={}, duration_days=30, expires_at=now + timedelta(days=30), status="APPROVED", trace_id="budget-metadata-only")
        db.add(grant)
        contract = DataContract(provider_org_id="provider", consumer_type="applicant", purpose=grant.purpose, data_refs_json=[], policy_json={}, policy_hash="c" * 64, status="ACTIVE", valid_from=now, expires_at=grant.expires_at)
        db.add(contract)
        db.flush()
        agreement = DataSpaceAgreement(contract_id=contract.contract_id, provider_org_id="provider", consumer_org_id="applicant", provider_did=grant.provider_did, consumer_did=grant.applicant_did, state="ACTIVE", requested_purpose=grant.purpose, algorithm_code="CONTROLLED_DATA_USAGE_V1", offered_policy_hash=contract.policy_hash, negotiated_policy_hash=contract.policy_hash, valid_from=now, expires_at=grant.expires_at, max_uses=1, use_count=0, trace_id="budget-metadata-only")
        db.add(agreement)
        db.flush()
        grant.contract_id, grant.agreement_id = contract.contract_id, agreement.agreement_id
        db.commit()
        yield db, grant, agreement, user


def _queue(db, grant, user, key="budget-query"):
    conditions = {"authorization_id": grant.request_id, "provider_org_id": "provider", "energy_domain": "electricity", "resource": "generation", "function": "sum", "start_date": "2026-06-01", "end_date": "2026-06-03", "region": None, "decimals": 2}
    token = trusted_query._issue_confirmation_token(trusted_query._confirmation_claims(trusted_query.ConfirmRequest(**conditions), user))
    return trusted_query.execute_query(trusted_query.ExecuteRequest(**conditions, confirmation_token=token), BackgroundTasks(), key, user, db)


def test_single_use_budget_changes_after_a_real_reservation_and_not_on_replay(records):
    db, grant, agreement, user = records
    assert to_payload(db, grant, user)["usage_budget"] == {"remaining_uses": 1, "usable": True, "agreement_state": "ACTIVE"}

    queued = _queue(db, grant, user)
    replay = _queue(db, grant, user)
    assert replay["task_id"] == queued["task_id"]
    db.refresh(agreement)
    assert grant.status == "APPROVED" and agreement.state == "CONSUMED"
    assert to_payload(db, grant, user)["usage_budget"] == {"remaining_uses": 0, "usable": False, "agreement_state": "CONSUMED"}


@pytest.mark.parametrize(("request_limit", "agreement_limit", "queries", "external_uses", "remaining"), [
    (3, 5, 3, 0, 0),
    (5, 2, 1, 0, 1),
    (3, 5, 1, 3, 1),
])
def test_projection_intersects_request_budget_with_all_agreement_uses(records, request_limit, agreement_limit, queries, external_uses, remaining):
    db, grant, agreement, user = records
    grant.requested_scope_json = {"max_uses": request_limit}
    agreement.max_uses = agreement_limit
    db.commit()
    for index in range(queries):
        _queue(db, grant, user, f"budget-{index}")
    db.refresh(agreement)
    agreement.use_count += external_uses
    db.commit()
    budget = to_payload(db, grant, user)["usage_budget"]
    assert budget["remaining_uses"] == remaining
    assert budget["usable"] is (remaining > 0)


@pytest.mark.parametrize("state", ["CONSUMED", "REVOKED", "EXPIRED", "REJECTED"])
def test_unavailable_agreement_states_do_not_advertise_execution(records, state):
    db, grant, agreement, user = records
    agreement.max_uses = 5
    agreement.state = state
    db.commit()
    assert to_payload(db, grant, user)["usage_budget"] == {"remaining_uses": 0, "usable": False, "agreement_state": state}


@pytest.mark.parametrize("condition", ["expired", "not_yet_valid", "consumer", "provider", "contract", "missing", "request_expired", "request_revoked"])
def test_invalid_bound_agreement_or_request_is_unusable(records, condition):
    db, grant, agreement, user = records
    if condition == "expired":
        agreement.expires_at = utc_now() - timedelta(seconds=1)
    elif condition == "not_yet_valid":
        agreement.valid_from = utc_now() + timedelta(days=1)
    elif condition == "consumer":
        agreement.consumer_org_id = "provider"
    elif condition == "provider":
        agreement.provider_org_id = "applicant"
    elif condition == "contract":
        grant.contract_id = None
    elif condition == "missing":
        grant.agreement_id = "missing"
    elif condition == "request_expired":
        grant.expires_at = utc_now() - timedelta(seconds=1)
    else:
        grant.status = "REVOKED"
    if condition != "missing":
        db.commit()
    budget = to_payload(db, grant, user)["usage_budget"]
    assert budget["remaining_uses"] == 0
    assert budget["usable"] is False


def test_unbound_rule_grants_keep_existing_unlimited_compatibility(records):
    db, grant, _agreement, user = records
    grant.agreement_id = None
    grant.contract_id = None
    db.commit()
    assert "usage_budget" not in to_payload(db, grant, user)


def test_unbound_explicit_budget_counts_real_query_reservations(records):
    db, grant, _agreement, user = records
    grant.agreement_id = None
    grant.contract_id = None
    grant.requested_scope_json = {"max_uses": 1}
    db.commit()
    assert to_payload(db, grant, user)["usage_budget"]["remaining_uses"] == 1
    _queue(db, grant, user)
    assert to_payload(db, grant, user)["usage_budget"] == {"remaining_uses": 0, "usable": False, "agreement_state": None}
