import json

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal, engine
from app.main import app
from app.models import AuditLog, Base, DidIdentity, DidLoginChallenge, Organization, User
from app.services.rate_limit import limiter


@pytest.fixture(autouse=True)
def reset_test_database():
    """DID authentication needs identity metadata, never raw-data fixtures."""
    limiter.reset()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        org_id = "org-generator-t01"
        db.add(Organization(org_id=org_id, org_type="GENERATOR", org_name="签名登录测试企业", energy_domain="electricity"))
        db.flush()
        db.add(User(user_id="user-generator", org_id=org_id, username="generator", password_hash="unused", display_name="测试账号", role_code="GENERATOR", is_org_owner=True))
        db.add(DidIdentity(did_id=f"did:hiddenchain:org:{org_id}", owner_type="ORG", owner_id=org_id, org_id=org_id, public_key_fingerprint="metadata-only", credential_status="VALID"))
        db.commit()
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def client():
    # Metadata are initialized above; do not enter fixture-seeding lifespan.
    instance = TestClient(app, raise_server_exceptions=False)
    yield instance
    instance.close()


def _sign_challenge(challenge: dict, account) -> str:
    signed = Account.sign_message(
        encode_defunct(text=challenge["message"]),
        private_key=account.key,
    )
    return signed.signature.hex()


def test_did_wallet_login_verifies_signature_and_creates_existing_session(client):
    account = Account.create()
    with SessionLocal() as db:
        identity = db.get(DidIdentity, "did:hiddenchain:org:org-generator-t01")
        assert identity is not None
        identity.chain_address = account.address
        db.commit()

    challenge_response = client.post(
        "/api/auth/did/challenge",
        json={"wallet_address": account.address},
    )
    assert challenge_response.status_code == 200, challenge_response.text
    challenge = challenge_response.json()
    assert challenge["wallet_address"] == account.address.lower()
    assert challenge["expires_at"]

    login_response = client.post(
        "/api/auth/did/verify",
        json={
            "challenge": challenge["challenge"],
            "wallet_address": account.address,
            "signature": _sign_challenge(challenge, account),
        },
    )
    assert login_response.status_code == 200, login_response.text
    payload = login_response.json()
    assert payload["token_type"] == "bearer"
    assert payload["did"]["did_id"] == "did:hiddenchain:org:org-generator-t01"
    assert payload["user"]["username"] == "generator"

    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me_response.status_code == 200, me_response.text
    assert me_response.json()["did"]["chain_address"] == account.address.lower()

    replay_response = client.post(
        "/api/auth/did/verify",
        json={
            "challenge": challenge["challenge"],
            "wallet_address": account.address,
            "signature": _sign_challenge(challenge, account),
        },
    )
    assert replay_response.status_code == 409
    assert replay_response.json()["code"] == "DID_LOGIN_CHALLENGE_USED"


def test_did_wallet_login_rejects_wrong_signature(client):
    account = Account.create()
    wrong_account = Account.create()
    with SessionLocal() as db:
        identity = db.get(DidIdentity, "did:hiddenchain:org:org-generator-t01")
        assert identity is not None
        identity.chain_address = account.address
        db.commit()

    challenge = client.post(
        "/api/auth/did/challenge",
        json={"wallet_address": account.address},
    ).json()
    response = client.post(
        "/api/auth/did/verify",
        json={
            "challenge": challenge["challenge"],
            "wallet_address": account.address,
            "signature": _sign_challenge(challenge, wrong_account),
        },
    )
    assert response.status_code == 401
    assert response.json()["code"] == "DID_LOGIN_SIGNATURE_INVALID"


@pytest.mark.parametrize("signature", ["0x" + "0" * 130, "0x" + f"{5:064x}{1:064x}1b"])
def test_unrecoverable_wallet_signatures_are_audited_without_consuming_the_challenge(client, signature):
    account = Account.create()
    with SessionLocal() as db:
        identity = db.get(DidIdentity, "did:hiddenchain:org:org-generator-t01")
        identity.chain_address = account.address
        db.commit()
    challenge_response = client.post("/api/auth/did/challenge", json={"wallet_address": account.address})
    assert challenge_response.status_code == 200, challenge_response.text
    challenge = challenge_response.json()
    body = {"challenge": challenge["challenge"], "wallet_address": account.address, "signature": signature}

    rejected = client.post("/api/auth/did/verify", json=body)
    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["code"] == "DID_LOGIN_SIGNATURE_INVALID"
    with SessionLocal() as db:
        assert db.get(DidLoginChallenge, challenge["challenge"]).used_at is None
        failure = db.scalar(select(AuditLog).where(AuditLog.action_code == "LOGIN_DID", AuditLog.result == "FAILED", AuditLog.target_id == account.address.lower()))
        assert failure is not None
        assert failure.details_json["reason"] == "INVALID_SIGNATURE"

    body["signature"] = _sign_challenge(challenge, account)
    accepted = client.post("/api/auth/did/verify", json=body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["user"]["username"] == "generator"
    with SessionLocal() as db:
        assert db.get(DidLoginChallenge, challenge["challenge"]).used_at is not None


def test_did_wallet_login_rejects_unregistered_wallet(client):
    account = Account.create()
    challenge = client.post(
        "/api/auth/did/challenge",
        json={"wallet_address": account.address},
    ).json()
    response = client.post(
        "/api/auth/did/verify",
        json={
            "challenge": challenge["challenge"],
            "wallet_address": account.address,
            "signature": _sign_challenge(challenge, account),
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "DID_WALLET_NOT_REGISTERED"


def test_did_wallet_login_accepts_render_binding_configuration(client):
    account = Account.create()
    original_bindings = settings.did_wallet_bindings_json
    object.__setattr__(
        settings,
        "did_wallet_bindings_json",
        json.dumps({"did:hiddenchain:org:org-generator-t01": account.address}),
    )
    try:
        challenge = client.post(
            "/api/auth/did/challenge",
            json={"wallet_address": account.address},
        ).json()
        response = client.post(
            "/api/auth/did/verify",
            json={
                "challenge": challenge["challenge"],
                "wallet_address": account.address,
                "signature": _sign_challenge(challenge, account),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["did"]["did_id"] == "did:hiddenchain:org:org-generator-t01"
    finally:
        object.__setattr__(settings, "did_wallet_bindings_json", original_bindings)
