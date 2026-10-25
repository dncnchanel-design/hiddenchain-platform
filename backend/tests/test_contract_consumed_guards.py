"""Closed contract negotiation cannot alter the policy used by completed work."""
from copy import deepcopy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal, engine
from app.main import app
from app.models import (
    AuditLog, Base, ContractNegotiationEvent, DataContract, DataSpaceAgreement,
    Organization, User, utc_now,
)
from app.security import create_access_token, sha256_json
from app.services.rate_limit import limiter


CONTRACT_ID = "closed-contract"
AGREEMENT_ID = "closed-agreement"
POLICY = {"max_uses": 1, "aggregate_only": True}
PROPOSED_TERMS = {"max_uses": 999, "aggregate_only": False}


@pytest.fixture(autouse=True)
def reset_test_database():
    """Override demo seeding; these HTTP tests need metadata rows only."""
    limiter.reset()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for org_id, role in (("provider", "GENERATOR"), ("consumer", "EXCHANGE")):
            db.add(Organization(org_id=org_id, org_name=org_id, org_type=role, energy_domain="electricity"))
        db.flush()
        db.add(User(user_id="provider-user", org_id="provider", username="provider", password_hash="unused",
                    display_name="provider", role_code="GENERATOR"))
        db.commit()
    yield
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@pytest.fixture
def http():
    # Avoid a lifespan context: it starts demo workers and is unnecessary
    # for the contract router's ordinary database transactions.
    client = TestClient(app)
    yield client
    client.close()


def _contract(state):
    now = utc_now()
    with SessionLocal() as db:
        db.add(DataContract(contract_id=CONTRACT_ID, provider_org_id="provider", consumer_type="consumer",
                            purpose="受控聚合", policy_json=deepcopy(POLICY), policy_hash=sha256_json(POLICY),
                            valid_from=now, expires_at=now + timedelta(days=30)))
        db.flush()
        db.add(DataSpaceAgreement(agreement_id=AGREEMENT_ID, contract_id=CONTRACT_ID,
                                 provider_org_id="provider", consumer_org_id="consumer",
                                 provider_did="did:test:provider", consumer_did="did:test:consumer",
                                 state=state, requested_purpose="受控聚合", algorithm_code="SUM",
                                 offered_policy_hash=sha256_json(POLICY), negotiated_policy_hash=sha256_json(POLICY),
                                 valid_from=now, expires_at=now + timedelta(days=30), max_uses=1,
                                 use_count=int(state == "CONSUMED"), decision_json={"approved": True},
                                 last_receipt_json={"result_hash": "a" * 64}, trace_id="closed-contract-test"))
        db.commit()
    return {"Authorization": "Bearer " + create_access_token("provider-user", "GENERATOR", "provider")}


def _snapshot():
    with SessionLocal() as db:
        contract, agreement = db.get(DataContract, CONTRACT_ID), db.get(DataSpaceAgreement, AGREEMENT_ID)
        return {
            "state": agreement.state, "use_count": agreement.use_count, "max_uses": agreement.max_uses,
            "policy": deepcopy(contract.policy_json), "policy_hash": contract.policy_hash,
            "negotiated_policy_hash": agreement.negotiated_policy_hash,
            "decision": deepcopy(agreement.decision_json), "receipt": deepcopy(agreement.last_receipt_json),
            "events": db.scalar(select(func.count(ContractNegotiationEvent.event_id))),
            "audit_logs": db.scalar(select(func.count(AuditLog.log_id))),
        }


@pytest.mark.parametrize("state", ["ACTIVE", "CONSUMED"])
@pytest.mark.parametrize("action", ["counter", "accept", "reject"])
def test_closed_negotiation_rejects_business_changes_without_persisting_anything(http, state, action):
    headers = _contract(state)
    before = _snapshot()
    response = http.post(f"/api/trust-space/contracts/{CONTRACT_ID}/{action}",
                         headers={**headers, "If-Match": '"0"'},
                         json={"message": "不可重开已生效或耗尽的协议", "terms": PROPOSED_TERMS})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "NEGOTIATION_STATE_CLOSED"
    assert _snapshot() == before
    detail = http.get(f"/api/trust-space/contracts/{CONTRACT_ID}", headers=headers)
    assert detail.status_code == 200 and detail.json()["allowed_actions"] == ["comment"]


@pytest.mark.parametrize("state", ["ACTIVE", "CONSUMED", "NEGOTIATED"])
@pytest.mark.parametrize("event_type", ["COMMENT", "ATTACHMENT"])
def test_comment_and_attachment_terms_are_event_metadata_not_formal_policy(http, state, event_type):
    headers = _contract(state)
    before = _snapshot()
    response = http.post(f"/api/trust-space/contracts/{CONTRACT_ID}/events",
                         headers={**headers, "If-Match": '"0"'}, json={
                             "event_type": event_type, "message": "仅留痕，不变更正式协议",
                             "terms": PROPOSED_TERMS,
                             "attachments": [{"evidence_id": "metadata-reference", "name": "reference"}],
                         })
    assert response.status_code == 201, response.text
    event = response.json()
    assert event["from_state"] == event["to_state"] == state
    assert event["terms"] == PROPOSED_TERMS and event["state_version"] == 1
    assert _snapshot() == {**before, "events": 1, "audit_logs": 1}
    with SessionLocal() as db:
        saved = db.get(ContractNegotiationEvent, event["event_id"])
        assert saved.terms_json == PROPOSED_TERMS and saved.event_hash == event["event_hash"]


@pytest.mark.parametrize("action,target_state", [("counter", "NEGOTIATED"), ("accept", "ACTIVE"), ("reject", "REJECTED")])
def test_open_negotiation_keeps_existing_positive_actions(http, action, target_state):
    headers = _contract("NEGOTIATED")
    response = http.post(f"/api/trust-space/contracts/{CONTRACT_ID}/{action}",
                         headers={**headers, "If-Match": '"0"'},
                         json={"message": "正常协商", "terms": {"max_uses": 2}})
    assert response.status_code == 200, response.text
    assert response.json()["to_state"] == target_state
    after = _snapshot()
    assert after["state"] == target_state and after["events"] == 1
    assert after["policy"] == {**POLICY, "max_uses": 2}
    assert after["policy_hash"] == sha256_json(after["policy"])
