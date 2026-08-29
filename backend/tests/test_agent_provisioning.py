from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Base, DidIdentity, Organization
from app.services.adapters import AGENT_DEFINITIONS
from app.services.agent_provisioning import (
    AgentProvisioningError,
    ProductionAgentManifest,
    load_production_agent_manifest,
    provision_production_agents,
    validate_production_agent_manifest,
)
from app.services.tool_catalog import (
    agent_tool_catalog_readiness,
    ensure_agent_tool_catalog,
)
from app.trust_models import AgentPermission, AgentTool


ISSUER_DID = "did:hiddenchain:org:platform-operator-prod"
AGENT_ORG_ID = "platform-operator-prod"
EXTERNAL_VERIFIER_DID = "did:example:credential-authority-prod"


@pytest.fixture
def isolated_db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _manifest_payload() -> dict[str, object]:
    agents = []
    for definition in AGENT_DEFINITIONS:
        fingerprint = _hash(f"external-public-key:{definition['code']}")
        agents.append(
            {
                "agent_code": definition["code"],
                "did": definition["did"],
                "organization_id": AGENT_ORG_ID,
                "external_public_key_fingerprint": fingerprint,
                "chain_address": None,
                "credential": {
                    "type": [
                        "VerifiableCredential",
                        "AgentCapabilityCredential",
                    ],
                    "issuer": ISSUER_DID,
                    "credentialSubject": {
                        "id": definition["did"],
                        "agentCode": definition["code"],
                        "capabilities": definition["tools"],
                    },
                    "proof": {
                        "type": "DataIntegrityProof",
                        "created": "2026-08-29T09:00:00+08:00",
                        "verificationMethod": f"{ISSUER_DID}#agent-issuer-key-1",
                        "proofPurpose": "assertionMethod",
                        "proofHash": _hash(f"external-vc-proof:{definition['code']}"),
                    },
                    "verification": {
                        "status": "VERIFIED",
                        "method": "EXTERNAL_VC_PROOF_VERIFICATION_V1",
                        "verifierDid": ISSUER_DID,
                        "verifiedAt": "2026-08-29T09:01:00+08:00",
                        "publicKeyFingerprint": fingerprint,
                    },
                },
            }
        )
    return {
        "schema_version": "HIDDENCHAIN_PRODUCTION_AGENT_MANIFEST_V1",
        "grant_issuer_did": ISSUER_DID,
        "organizations": [
            {
                "organization_id": AGENT_ORG_ID,
                "organization_type": "PLATFORM_OPERATOR",
                "organization_name": "Production platform operator",
                "credit_code": "PRODUCTION-OPERATOR-001",
                "energy_domain": None,
                "profile": {"identity_source": "external"},
                "status": "ACTIVE",
            }
        ],
        "grant_issuer": {
            "did": ISSUER_DID,
            "organization_id": AGENT_ORG_ID,
            "owner_type": "ORG",
            "credential_status": "VALID",
            "external_public_key_fingerprint": _hash(
                "external-public-key:grant-issuer"
            ),
            "chain_address": None,
            "credential": {
                "type": [
                    "VerifiableCredential",
                    "OrganizationGrantIssuerCredential",
                ],
                "issuer": EXTERNAL_VERIFIER_DID,
                "credentialSubject": {
                    "id": ISSUER_DID,
                    "organizationId": AGENT_ORG_ID,
                    "grantAuthority": "AGENT_TOOL_GRANT",
                },
                "proof": {
                    "type": "DataIntegrityProof",
                    "created": "2026-08-29T08:00:00+08:00",
                    "verificationMethod": (
                        f"{EXTERNAL_VERIFIER_DID}#credential-authority-key-1"
                    ),
                    "proofPurpose": "assertionMethod",
                    "proofHash": _hash("external-vc-proof:grant-issuer"),
                },
                "verification": {
                    "status": "VERIFIED",
                    "method": "EXTERNAL_VC_PROOF_VERIFICATION_V1",
                    "verifierDid": EXTERNAL_VERIFIER_DID,
                    "verifiedAt": "2026-08-29T08:01:00+08:00",
                    "publicKeyFingerprint": _hash(
                        "external-public-key:grant-issuer"
                    ),
                },
            },
        },
        "agents": agents,
    }


def _manifest() -> ProductionAgentManifest:
    return validate_production_agent_manifest(_manifest_payload())


def test_empty_production_database_moves_from_not_ready_to_manifest_ready(
    isolated_db: Session,
) -> None:
    result = ensure_agent_tool_catalog(isolated_db, grant_issuer_did=None)
    readiness = agent_tool_catalog_readiness(isolated_db)

    assert result["tools_created"] > 0
    assert isolated_db.scalar(select(func.count(AgentTool.tool_id))) > 0
    assert isolated_db.scalar(select(func.count(AgentPermission.permission_id))) == 0
    assert readiness["status"] == "NOT_READY"
    assert any(issue.startswith("AGENT_DID_MISSING:") for issue in readiness["issues"])

    provisioned = provision_production_agents(isolated_db, _manifest())
    isolated_db.commit()

    assert provisioned["status"] == "READY"
    assert provisioned["organizations_created"] == 1
    assert provisioned["grant_issuer_created"] == 1
    assert provisioned["identities_created"] == len(AGENT_DEFINITIONS)
    assert provisioned["permissions_created"] > 0
    assert provisioned["readiness"]["status"] == "READY"
    for definition in AGENT_DEFINITIONS:
        identity = isolated_db.get(DidIdentity, definition["did"])
        assert identity is not None
        assert identity.owner_type == "AGENT"
        assert identity.owner_id == definition["code"]
        assert identity.credential_json["issuer"] == ISSUER_DID


def test_manifest_provisioning_is_idempotent(isolated_db: Session) -> None:
    manifest = _manifest()
    provision_production_agents(isolated_db, manifest)
    isolated_db.commit()

    repeated = provision_production_agents(isolated_db, manifest)
    isolated_db.commit()

    assert repeated["status"] == "READY"
    assert repeated["organizations_created"] == 0
    assert repeated["grant_issuer_created"] == 0
    assert repeated["identities_created"] == 0
    assert repeated["tools_created"] == 0
    assert repeated["tools_updated"] == 0
    assert repeated["permissions_created"] == 0


def test_manifest_provisioning_rejects_existing_identity_conflict_without_writes(
    isolated_db: Session,
) -> None:
    manifest = _manifest()
    provision_production_agents(isolated_db, manifest)
    isolated_db.commit()
    entry = manifest.agents[0]
    identity = isolated_db.get(DidIdentity, entry.did)
    assert identity is not None
    identity.public_key_fingerprint = _hash("different-external-key")
    isolated_db.commit()

    before_permission_count = isolated_db.scalar(
        select(func.count(AgentPermission.permission_id))
    )

    with pytest.raises(AgentProvisioningError, match="AGENT_IDENTITY_CONFLICT"):
        provision_production_agents(isolated_db, manifest)

    assert isolated_db.scalar(
        select(func.count(AgentPermission.permission_id))
    ) == before_permission_count


def test_manifest_provisioning_rejects_conflicting_live_grant(
    isolated_db: Session,
) -> None:
    manifest = _manifest()
    provision_production_agents(isolated_db, manifest)
    isolated_db.commit()
    permission = isolated_db.scalar(select(AgentPermission).limit(1))
    assert permission is not None
    permission.granted_by_did = "did:hiddenchain:org:unexpected-issuer-prod"
    isolated_db.commit()

    with pytest.raises(AgentProvisioningError, match="AGENT_PERMISSION_CONFLICT"):
        provision_production_agents(isolated_db, manifest)


def test_readiness_rejects_a_revoked_manifest_grant_issuer(
    isolated_db: Session,
) -> None:
    manifest = _manifest()
    provision_production_agents(isolated_db, manifest)
    issuer = isolated_db.get(DidIdentity, manifest.grant_issuer.did)
    assert issuer is not None
    issuer.credential_status = "REVOKED"
    isolated_db.flush()

    readiness = agent_tool_catalog_readiness(isolated_db)

    assert readiness["status"] == "NOT_READY"
    assert any(
        issue.startswith("AGENT_GRANT_ISSUER_INVALID:")
        for issue in readiness["issues"]
    )


def test_manifest_provisioning_rolls_back_on_organization_conflict(
    isolated_db: Session,
) -> None:
    manifest = _manifest()
    organization = manifest.organizations[0]
    isolated_db.add(
        Organization(
            org_id=organization.organization_id,
            org_type=organization.organization_type,
            org_name="Conflicting operator name",
            credit_code=organization.credit_code,
            energy_domain=organization.energy_domain,
            profile_json=organization.profile,
            status=organization.status,
        )
    )
    isolated_db.commit()

    with pytest.raises(AgentProvisioningError, match="AGENT_ORGANIZATION_CONFLICT"):
        provision_production_agents(isolated_db, manifest)

    assert isolated_db.scalar(select(func.count(Organization.org_id))) == 1
    assert isolated_db.scalar(select(func.count(DidIdentity.did_id))) == 0
    assert isolated_db.scalar(select(func.count(AgentTool.tool_id))) == 0
    assert isolated_db.scalar(select(func.count(AgentPermission.permission_id))) == 0


def test_manifest_provisioning_rolls_back_on_grant_issuer_conflict(
    isolated_db: Session,
) -> None:
    manifest = _manifest()
    organization = manifest.organizations[0]
    isolated_db.add(
        Organization(
            org_id=organization.organization_id,
            org_type=organization.organization_type,
            org_name=organization.organization_name,
            credit_code=organization.credit_code,
            energy_domain=organization.energy_domain,
            profile_json=organization.profile,
            status=organization.status,
        )
    )
    isolated_db.flush()
    issuer = manifest.grant_issuer
    isolated_db.add(
        DidIdentity(
            did_id=issuer.did,
            owner_type="ORG",
            owner_id=issuer.organization_id,
            org_id=issuer.organization_id,
            public_key_fingerprint=_hash("conflicting-issuer-public-key"),
            chain_address=issuer.chain_address,
            credential_status="VALID",
            credential_json=issuer.credential,
        )
    )
    isolated_db.commit()

    with pytest.raises(AgentProvisioningError, match="AGENT_GRANT_ISSUER_CONFLICT"):
        provision_production_agents(isolated_db, manifest)

    assert isolated_db.scalar(select(func.count(Organization.org_id))) == 1
    assert isolated_db.scalar(select(func.count(DidIdentity.did_id))) == 1
    assert isolated_db.scalar(select(func.count(AgentTool.tool_id))) == 0
    assert isolated_db.scalar(select(func.count(AgentPermission.permission_id))) == 0


def test_manifest_requires_the_exact_agent_set_and_rejects_unknown_fields() -> None:
    missing_agent = _manifest_payload()
    missing_agent["agents"] = list(missing_agent["agents"])[:-1]
    with pytest.raises(AgentProvisioningError, match="exactly match"):
        validate_production_agent_manifest(missing_agent)

    unknown_field = _manifest_payload()
    unknown_field["private_key"] = "must-never-be-accepted"
    with pytest.raises(AgentProvisioningError, match="forbidden"):
        validate_production_agent_manifest(unknown_field)


def test_repository_example_manifest_loads_with_the_exact_production_schema() -> None:
    example_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "PRODUCTION_AGENT_PROVISIONING.example.json"
    )

    manifest = load_production_agent_manifest(example_path)

    assert len(manifest.organizations) == 1
    assert manifest.grant_issuer.did == manifest.grant_issuer_did
    assert {entry.did for entry in manifest.agents} == {
        str(definition["did"]) for definition in AGENT_DEFINITIONS
    }


def test_production_cli_migrates_and_provisions_an_empty_database(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "production-agent-manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    database_path = tmp_path / "production.db"
    public_key = base64.b64encode(b"k" * 32).decode()
    environment = {
        **os.environ,
        "APP_ENV": "production",
        "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
        "TEST_FIXTURE_SEED": "false",
        "TEST_COMPUTE_DELAY_MS": "0",
        "OPA_LOCAL_FALLBACK": "false",
        "OPA_URL": "https://policy.example.com",
        "JWT_SECRET": "j" * 64,
        "SIGNING_SECRET": "s" * 64,
        "CORS_ORIGINS": "https://platform.example.com",
        "PLATFORM_SIGNING_PRIVATE_KEY": base64.b64encode(b"p" * 32).decode(),
        "SUBJECT_NODE_ENDPOINTS_JSON": json.dumps(
            {"provider-prod": "https://connector.example.com"}
        ),
        "SUBJECT_NODE_BROWSER_ENDPOINTS_JSON": json.dumps(
            {"provider-prod": "https://connector.example.com"}
        ),
        "SUBJECT_NODE_IDS_JSON": json.dumps(
            {"provider-prod": "provider-connector-prod"}
        ),
        "SUBJECT_NODE_PUBLIC_KEYS_JSON": json.dumps(
            {"provider-prod": public_key}
        ),
    }
    command = [
        sys.executable,
        "scripts/provision_production_agents.py",
        "--manifest",
        str(manifest_path),
    ]

    first = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_payload = json.loads(first.stdout)
    assert first_payload["database"]["status"] == "READY"
    assert first_payload["agents"]["status"] == "READY"
    assert first_payload["agents"]["organizations_created"] == 1
    assert first_payload["agents"]["grant_issuer_created"] == 1

    repeated = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    repeated_agents = json.loads(repeated.stdout)["agents"]
    assert repeated_agents["organizations_created"] == 0
    assert repeated_agents["grant_issuer_created"] == 0
    assert repeated_agents["identities_created"] == 0
    assert repeated_agents["permissions_created"] == 0
