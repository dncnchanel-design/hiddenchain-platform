import json

from eth_account import Account
from eth_account.messages import encode_defunct

from app.config import settings
from app.database import SessionLocal
from app.models import DidIdentity


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
