from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DidIdentity, Organization, utc_now
from ..trust_models import AgentPermission, AgentTool
from .adapters import AGENT_DEFINITIONS
from .tool_catalog import (
    CONTROLLED_TOOL_BINDINGS,
    agent_tool_catalog_readiness,
    ensure_agent_tool_catalog,
)


MANIFEST_SCHEMA_VERSION = "HIDDENCHAIN_PRODUCTION_AGENT_MANIFEST_V1"
MAX_MANIFEST_BYTES = 1_048_576
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class AgentProvisioningError(RuntimeError):
    """Raised when production Agent identity provisioning cannot be trusted."""


@dataclass(frozen=True)
class ProductionOrganizationEntry:
    organization_id: str
    organization_type: str
    organization_name: str
    credit_code: str
    energy_domain: str | None
    profile: dict[str, Any]
    status: str


@dataclass(frozen=True)
class ProductionIssuerEntry:
    did: str
    organization_id: str
    external_public_key_fingerprint: str
    chain_address: str | None
    credential: dict[str, Any]


@dataclass(frozen=True)
class ProductionAgentEntry:
    agent_code: str
    did: str
    organization_id: str
    external_public_key_fingerprint: str
    chain_address: str | None
    credential: dict[str, Any]


@dataclass(frozen=True)
class ProductionAgentManifest:
    schema_version: str
    grant_issuer_did: str
    organizations: tuple[ProductionOrganizationEntry, ...]
    grant_issuer: ProductionIssuerEntry
    agents: tuple[ProductionAgentEntry, ...]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AgentProvisioningError(f"MANIFEST_DUPLICATE_KEY:{key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise AgentProvisioningError(f"MANIFEST_NON_STANDARD_NUMBER:{value}")


def _assert_no_secret_fields(value: Any, *, context: str = "manifest") -> None:
    forbidden = {
        "accesstoken",
        "clientsecret",
        "mnemonic",
        "password",
        "privatekey",
        "refreshtoken",
        "secret",
        "seed",
        "seedphrase",
        "token",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in forbidden:
                raise AgentProvisioningError(f"{context}.{key} is forbidden")
            _assert_no_secret_fields(item, context=f"{context}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_secret_fields(item, context=f"{context}[{index}]")


def _exact_object(
    value: Any,
    *,
    keys: set[str],
    context: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentProvisioningError(f"{context} must be a JSON object")
    actual = set(value)
    if actual != keys:
        missing = ",".join(sorted(keys - actual)) or "-"
        extra = ",".join(sorted(actual - keys)) or "-"
        raise AgentProvisioningError(
            f"{context} keys mismatch (missing={missing}; extra={extra})"
        )
    return value


def _required_string(
    value: Any,
    *,
    context: str,
    max_length: int,
) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise AgentProvisioningError(f"{context} must be an explicit non-empty string")
    if len(value) > max_length:
        raise AgentProvisioningError(f"{context} exceeds {max_length} characters")
    return value


def _nullable_string(
    value: Any,
    *,
    context: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    return _required_string(value, context=context, max_length=max_length)


def _sha256(value: Any, *, context: str) -> str:
    text = _required_string(value, context=context, max_length=64)
    if SHA256_PATTERN.fullmatch(text) is None or text == "0" * 64:
        raise AgentProvisioningError(
            f"{context} must be a non-zero lowercase SHA-256 hex value"
        )
    return text


def _aware_iso_timestamp(value: Any, *, context: str) -> str:
    text = _required_string(value, context=context, max_length=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AgentProvisioningError(
            f"{context} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AgentProvisioningError(f"{context} must include a timezone")
    return text


def _validate_proof_and_verification(
    credential: dict[str, Any],
    *,
    proof_controller_did: str,
    external_public_key_fingerprint: str,
    context: str,
) -> None:
    proof = _exact_object(
        credential["proof"],
        keys={"type", "created", "verificationMethod", "proofPurpose", "proofHash"},
        context=f"{context}.proof",
    )
    if proof["type"] != "DataIntegrityProof":
        raise AgentProvisioningError(
            f"{context}.proof.type must be DataIntegrityProof"
        )
    _aware_iso_timestamp(proof["created"], context=f"{context}.proof.created")
    verification_method = _required_string(
        proof["verificationMethod"],
        context=f"{context}.proof.verificationMethod",
        max_length=255,
    )
    if not verification_method.startswith(f"{proof_controller_did}#"):
        raise AgentProvisioningError(
            f"{context}.proof.verificationMethod has the wrong controller"
        )
    if proof["proofPurpose"] != "assertionMethod":
        raise AgentProvisioningError(
            f"{context}.proof.proofPurpose must be assertionMethod"
        )
    _sha256(proof["proofHash"], context=f"{context}.proof.proofHash")

    verification = _exact_object(
        credential["verification"],
        keys={
            "status",
            "method",
            "verifierDid",
            "verifiedAt",
            "publicKeyFingerprint",
        },
        context=f"{context}.verification",
    )
    if verification["status"] != "VERIFIED":
        raise AgentProvisioningError(f"{context}.verification.status must be VERIFIED")
    if verification["method"] != "EXTERNAL_VC_PROOF_VERIFICATION_V1":
        raise AgentProvisioningError(
            f"{context}.verification.method is unsupported"
        )
    if verification["verifierDid"] != proof_controller_did:
        raise AgentProvisioningError(
            f"{context}.verification.verifierDid mismatch"
        )
    _aware_iso_timestamp(
        verification["verifiedAt"],
        context=f"{context}.verification.verifiedAt",
    )
    if verification["publicKeyFingerprint"] != external_public_key_fingerprint:
        raise AgentProvisioningError(
            f"{context}.verification.publicKeyFingerprint mismatch"
        )


def _validate_credential(
    value: Any,
    *,
    definition: dict[str, Any],
    grant_issuer_did: str,
    external_public_key_fingerprint: str,
    context: str,
) -> dict[str, Any]:
    credential = _exact_object(
        value,
        keys={"type", "issuer", "credentialSubject", "proof", "verification"},
        context=context,
    )
    if credential["type"] != [
        "VerifiableCredential",
        "AgentCapabilityCredential",
    ]:
        raise AgentProvisioningError(f"{context}.type is not the required VC type list")
    if credential["issuer"] != grant_issuer_did:
        raise AgentProvisioningError(f"{context}.issuer must equal grant_issuer_did")

    subject = _exact_object(
        credential["credentialSubject"],
        keys={"id", "agentCode", "capabilities"},
        context=f"{context}.credentialSubject",
    )
    if subject["id"] != definition["did"]:
        raise AgentProvisioningError(f"{context}.credentialSubject.id mismatch")
    if subject["agentCode"] != definition["code"]:
        raise AgentProvisioningError(f"{context}.credentialSubject.agentCode mismatch")
    if subject["capabilities"] != definition["tools"]:
        raise AgentProvisioningError(f"{context}.credentialSubject.capabilities mismatch")

    _validate_proof_and_verification(
        credential,
        proof_controller_did=grant_issuer_did,
        external_public_key_fingerprint=external_public_key_fingerprint,
        context=context,
    )
    return deepcopy(credential)


def _validate_organizations(value: Any) -> tuple[ProductionOrganizationEntry, ...]:
    if not isinstance(value, list):
        raise AgentProvisioningError("manifest.organizations must be a JSON array")
    organizations: list[ProductionOrganizationEntry] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(value):
        context = f"manifest.organizations[{index}]"
        entry = _exact_object(
            raw_entry,
            keys={
                "organization_id",
                "organization_type",
                "organization_name",
                "credit_code",
                "energy_domain",
                "profile",
                "status",
            },
            context=context,
        )
        organization_id = _required_string(
            entry["organization_id"],
            context=f"{context}.organization_id",
            max_length=36,
        )
        if organization_id in seen:
            raise AgentProvisioningError(
                f"manifest.organizations contains duplicate {organization_id}"
            )
        seen.add(organization_id)
        profile = entry["profile"]
        if not isinstance(profile, dict):
            raise AgentProvisioningError(f"{context}.profile must be a JSON object")
        if entry["status"] != "ACTIVE":
            raise AgentProvisioningError(f"{context}.status must be ACTIVE")
        organizations.append(
            ProductionOrganizationEntry(
                organization_id=organization_id,
                organization_type=_required_string(
                    entry["organization_type"],
                    context=f"{context}.organization_type",
                    max_length=32,
                ),
                organization_name=_required_string(
                    entry["organization_name"],
                    context=f"{context}.organization_name",
                    max_length=128,
                ),
                credit_code=_required_string(
                    entry["credit_code"],
                    context=f"{context}.credit_code",
                    max_length=64,
                ),
                energy_domain=_nullable_string(
                    entry["energy_domain"],
                    context=f"{context}.energy_domain",
                    max_length=24,
                ),
                profile=deepcopy(profile),
                status="ACTIVE",
            )
        )
    return tuple(organizations)


def _validate_grant_issuer(
    value: Any,
    *,
    grant_issuer_did: str,
) -> ProductionIssuerEntry:
    context = "manifest.grant_issuer"
    entry = _exact_object(
        value,
        keys={
            "did",
            "organization_id",
            "owner_type",
            "credential_status",
            "external_public_key_fingerprint",
            "chain_address",
            "credential",
        },
        context=context,
    )
    if entry["did"] != grant_issuer_did:
        raise AgentProvisioningError(f"{context}.did must equal grant_issuer_did")
    if entry["owner_type"] != "ORG":
        raise AgentProvisioningError(f"{context}.owner_type must be ORG")
    if entry["credential_status"] != "VALID":
        raise AgentProvisioningError(f"{context}.credential_status must be VALID")
    organization_id = _required_string(
        entry["organization_id"],
        context=f"{context}.organization_id",
        max_length=36,
    )
    fingerprint = _sha256(
        entry["external_public_key_fingerprint"],
        context=f"{context}.external_public_key_fingerprint",
    )
    chain_address = _nullable_string(
        entry["chain_address"],
        context=f"{context}.chain_address",
        max_length=128,
    )
    credential = _exact_object(
        entry["credential"],
        keys={"type", "issuer", "credentialSubject", "proof", "verification"},
        context=f"{context}.credential",
    )
    if credential["type"] != [
        "VerifiableCredential",
        "OrganizationGrantIssuerCredential",
    ]:
        raise AgentProvisioningError(
            f"{context}.credential.type is not the required VC type list"
        )
    external_verifier_did = _required_string(
        credential["issuer"],
        context=f"{context}.credential.issuer",
        max_length=160,
    )
    if not external_verifier_did.startswith("did:") or external_verifier_did == grant_issuer_did:
        raise AgentProvisioningError(
            f"{context}.credential.issuer must be an external verifier DID"
        )
    subject = _exact_object(
        credential["credentialSubject"],
        keys={"id", "organizationId", "grantAuthority"},
        context=f"{context}.credential.credentialSubject",
    )
    if subject != {
        "id": grant_issuer_did,
        "organizationId": organization_id,
        "grantAuthority": "AGENT_TOOL_GRANT",
    }:
        raise AgentProvisioningError(
            f"{context}.credential.credentialSubject mismatch"
        )
    _validate_proof_and_verification(
        credential,
        proof_controller_did=external_verifier_did,
        external_public_key_fingerprint=fingerprint,
        context=f"{context}.credential",
    )
    return ProductionIssuerEntry(
        did=grant_issuer_did,
        organization_id=organization_id,
        external_public_key_fingerprint=fingerprint,
        chain_address=chain_address,
        credential=deepcopy(credential),
    )


def validate_production_agent_manifest(payload: Any) -> ProductionAgentManifest:
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AgentProvisioningError("manifest must contain only JSON values") from exc
    _assert_no_secret_fields(payload)
    root = _exact_object(
        payload,
        keys={
            "schema_version",
            "grant_issuer_did",
            "organizations",
            "grant_issuer",
            "agents",
        },
        context="manifest",
    )
    if root["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise AgentProvisioningError(
            f"manifest.schema_version must equal {MANIFEST_SCHEMA_VERSION}"
        )
    grant_issuer_did = _required_string(
        root["grant_issuer_did"],
        context="manifest.grant_issuer_did",
        max_length=160,
    )
    if not grant_issuer_did.startswith("did:"):
        raise AgentProvisioningError("manifest.grant_issuer_did must be a DID")
    organizations = _validate_organizations(root["organizations"])
    grant_issuer = _validate_grant_issuer(
        root["grant_issuer"],
        grant_issuer_did=grant_issuer_did,
    )

    raw_agents = root["agents"]
    if not isinstance(raw_agents, list):
        raise AgentProvisioningError("manifest.agents must be a JSON array")
    definitions_by_code = {str(item["code"]): item for item in AGENT_DEFINITIONS}
    expected_pairs = {
        (str(item["code"]), str(item["did"])) for item in AGENT_DEFINITIONS
    }
    parsed_entries: list[ProductionAgentEntry] = []
    actual_pairs: list[tuple[str, str]] = []
    fingerprints: set[str] = {grant_issuer.external_public_key_fingerprint}
    for index, raw_entry in enumerate(raw_agents):
        context = f"manifest.agents[{index}]"
        entry = _exact_object(
            raw_entry,
            keys={
                "agent_code",
                "did",
                "organization_id",
                "external_public_key_fingerprint",
                "chain_address",
                "credential",
            },
            context=context,
        )
        agent_code = _required_string(
            entry["agent_code"], context=f"{context}.agent_code", max_length=64
        )
        did = _required_string(entry["did"], context=f"{context}.did", max_length=160)
        organization_id = _required_string(
            entry["organization_id"],
            context=f"{context}.organization_id",
            max_length=36,
        )
        fingerprint = _sha256(
            entry["external_public_key_fingerprint"],
            context=f"{context}.external_public_key_fingerprint",
        )
        if fingerprint in fingerprints:
            raise AgentProvisioningError(
                f"{context}.external_public_key_fingerprint must be unique"
            )
        fingerprints.add(fingerprint)
        chain_address = entry["chain_address"]
        if chain_address is not None:
            chain_address = _required_string(
                chain_address,
                context=f"{context}.chain_address",
                max_length=128,
            )
        definition = definitions_by_code.get(agent_code)
        if definition is None or definition["did"] != did:
            raise AgentProvisioningError(f"{context} is not an exact AGENT_DEFINITIONS pair")
        credential = _validate_credential(
            entry["credential"],
            definition=definition,
            grant_issuer_did=grant_issuer_did,
            external_public_key_fingerprint=fingerprint,
            context=f"{context}.credential",
        )
        actual_pairs.append((agent_code, did))
        parsed_entries.append(
            ProductionAgentEntry(
                agent_code=agent_code,
                did=did,
                organization_id=organization_id,
                external_public_key_fingerprint=fingerprint,
                chain_address=chain_address,
                credential=credential,
            )
        )

    if len(actual_pairs) != len(set(actual_pairs)):
        raise AgentProvisioningError("manifest.agents contains a duplicate Agent")
    if set(actual_pairs) != expected_pairs or len(actual_pairs) != len(expected_pairs):
        raise AgentProvisioningError(
            "manifest.agents must exactly match every AGENT_DEFINITIONS code and DID"
        )
    if grant_issuer_did in {entry.did for entry in parsed_entries}:
        raise AgentProvisioningError("grant_issuer_did cannot be an Agent DID")
    referenced_organizations = {
        grant_issuer.organization_id,
        *(entry.organization_id for entry in parsed_entries),
    }
    manifest_organizations = {
        entry.organization_id for entry in organizations
    }
    if manifest_organizations != referenced_organizations:
        raise AgentProvisioningError(
            "manifest.organizations must exactly match issuer and Agent references"
        )
    entries_by_code = {entry.agent_code: entry for entry in parsed_entries}
    return ProductionAgentManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        grant_issuer_did=grant_issuer_did,
        organizations=organizations,
        grant_issuer=grant_issuer,
        agents=tuple(
            entries_by_code[str(definition["code"])]
            for definition in AGENT_DEFINITIONS
        ),
    )


def load_production_agent_manifest(path: str | Path) -> ProductionAgentManifest:
    manifest_path = Path(path)
    try:
        with manifest_path.open("rb") as manifest_file:
            raw_bytes = manifest_file.read(MAX_MANIFEST_BYTES + 1)
        if len(raw_bytes) > MAX_MANIFEST_BYTES:
            raise AgentProvisioningError(
                f"manifest exceeds the {MAX_MANIFEST_BYTES}-byte limit"
            )
        raw = raw_bytes.decode("utf-8")
    except AgentProvisioningError:
        raise
    except (OSError, UnicodeError) as exc:
        raise AgentProvisioningError("manifest cannot be read as UTF-8 JSON") from exc
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except AgentProvisioningError:
        raise
    except json.JSONDecodeError as exc:
        raise AgentProvisioningError("manifest is not valid JSON") from exc
    return validate_production_agent_manifest(payload)


def _organization_mismatches(
    organization: Organization,
    entry: ProductionOrganizationEntry,
) -> list[str]:
    expected = {
        "org_type": entry.organization_type,
        "org_name": entry.organization_name,
        "credit_code": entry.credit_code,
        "energy_domain": entry.energy_domain,
        "profile_json": entry.profile,
        "status": entry.status,
    }
    return [
        field for field, value in expected.items() if getattr(organization, field) != value
    ]


def _issuer_mismatches(
    identity: DidIdentity,
    entry: ProductionIssuerEntry,
) -> list[str]:
    expected = {
        "owner_type": "ORG",
        "owner_id": entry.organization_id,
        "org_id": entry.organization_id,
        "public_key_fingerprint": entry.external_public_key_fingerprint,
        "chain_address": entry.chain_address,
        "credential_status": "VALID",
        "credential_json": entry.credential,
    }
    return [field for field, value in expected.items() if getattr(identity, field) != value]


def _identity_mismatches(
    identity: DidIdentity,
    entry: ProductionAgentEntry,
) -> list[str]:
    expected = {
        "owner_type": "AGENT",
        "owner_id": entry.agent_code,
        "org_id": entry.organization_id,
        "public_key_fingerprint": entry.external_public_key_fingerprint,
        "chain_address": entry.chain_address,
        "credential_status": "VALID",
        "credential_json": entry.credential,
    }
    return [field for field, value in expected.items() if getattr(identity, field) != value]


def _permission_window_is_live(permission: AgentPermission) -> bool:
    now = utc_now()
    return (
        permission.status == "ACTIVE"
        and permission.valid_from <= now
        and (permission.expires_at is None or permission.expires_at > now)
    )


def _assert_no_conflicting_grants(
    db: Session,
    manifest: ProductionAgentManifest,
) -> None:
    definitions = {str(item["code"]): item for item in AGENT_DEFINITIONS}
    tools = {
        item.tool_code: item
        for item in db.scalars(select(AgentTool)).all()
    }
    for binding in CONTROLLED_TOOL_BINDINGS:
        tool = tools.get(str(binding["tool_code"]))
        if tool is None:
            continue
        for agent_code in binding["agents"]:
            definition = definitions[str(agent_code)]
            permissions = db.scalars(
                select(AgentPermission).where(
                    AgentPermission.agent_did == definition["did"],
                    AgentPermission.tool_id == tool.tool_id,
                    AgentPermission.status == "ACTIVE",
                )
            ).all()
            for permission in permissions:
                if not _permission_window_is_live(permission):
                    continue
                exact_grant = (
                    permission.granted_by_did == manifest.grant_issuer_did
                    and permission.agent_role == agent_code
                    and {str(item).upper() for item in permission.operations_json}
                    == {"INVOKE"}
                    and permission.scope_json == {"allow_all_tasks": True}
                )
                if not exact_grant:
                    raise AgentProvisioningError(
                        "AGENT_PERMISSION_CONFLICT:"
                        f"{agent_code}:{binding['tool_code']}"
                    )


def _provision_production_agents(
    db: Session,
    manifest: ProductionAgentManifest,
) -> dict[str, Any]:
    organizations_to_create: list[ProductionOrganizationEntry] = []
    for entry in manifest.organizations:
        organization = db.get(Organization, entry.organization_id)
        if organization is None:
            organizations_to_create.append(entry)
            continue
        mismatches = _organization_mismatches(organization, entry)
        if mismatches:
            raise AgentProvisioningError(
                f"AGENT_ORGANIZATION_CONFLICT:{entry.organization_id}:"
                + ",".join(sorted(mismatches))
            )

    issuer_to_create = False
    issuer = db.get(DidIdentity, manifest.grant_issuer.did)
    if issuer is None:
        issuer_to_create = True
    else:
        mismatches = _issuer_mismatches(issuer, manifest.grant_issuer)
        if mismatches:
            raise AgentProvisioningError(
                "AGENT_GRANT_ISSUER_CONFLICT:"
                + ",".join(sorted(mismatches))
            )

    expected_fingerprints = {
        manifest.grant_issuer.did: manifest.grant_issuer.external_public_key_fingerprint,
        **{
            entry.did: entry.external_public_key_fingerprint
            for entry in manifest.agents
        },
    }
    fingerprint_collisions = db.scalars(
        select(DidIdentity).where(
            DidIdentity.public_key_fingerprint.in_(
                list(expected_fingerprints.values())
            )
        )
    ).all()
    for identity in fingerprint_collisions:
        if expected_fingerprints.get(identity.did_id) != identity.public_key_fingerprint:
            raise AgentProvisioningError(
                f"AGENT_PUBLIC_KEY_FINGERPRINT_CONFLICT:{identity.did_id}"
            )

    identities_to_create: list[ProductionAgentEntry] = []
    for entry in manifest.agents:
        identity = db.get(DidIdentity, entry.did)
        if identity is None:
            identities_to_create.append(entry)
            continue
        mismatches = _identity_mismatches(identity, entry)
        if mismatches:
            raise AgentProvisioningError(
                f"AGENT_IDENTITY_CONFLICT:{entry.agent_code}:"
                + ",".join(sorted(mismatches))
            )

    _assert_no_conflicting_grants(db, manifest)
    for entry in organizations_to_create:
        db.add(
            Organization(
                org_id=entry.organization_id,
                org_type=entry.organization_type,
                org_name=entry.organization_name,
                credit_code=entry.credit_code,
                energy_domain=entry.energy_domain,
                profile_json=deepcopy(entry.profile),
                status=entry.status,
            )
        )
    db.flush()
    if issuer_to_create:
        entry = manifest.grant_issuer
        db.add(
            DidIdentity(
                did_id=entry.did,
                owner_type="ORG",
                owner_id=entry.organization_id,
                org_id=entry.organization_id,
                public_key_fingerprint=entry.external_public_key_fingerprint,
                chain_address=entry.chain_address,
                credential_status="VALID",
                credential_json=deepcopy(entry.credential),
            )
        )
        db.flush()
    for entry in identities_to_create:
        db.add(
            DidIdentity(
                did_id=entry.did,
                owner_type="AGENT",
                owner_id=entry.agent_code,
                org_id=entry.organization_id,
                public_key_fingerprint=entry.external_public_key_fingerprint,
                chain_address=entry.chain_address,
                credential_status="VALID",
                credential_json=deepcopy(entry.credential),
            )
        )
    db.flush()

    catalog_result = ensure_agent_tool_catalog(
        db,
        grant_issuer_did=manifest.grant_issuer_did,
    )
    readiness = agent_tool_catalog_readiness(
        db,
        grant_issuer_did=manifest.grant_issuer_did,
    )
    if readiness["status"] != "READY":
        raise AgentProvisioningError(
            "AGENT_PROVISIONING_NOT_READY:" + ",".join(readiness["issues"])
        )
    return {
        "status": "READY",
        "schema_version": manifest.schema_version,
        "grant_issuer_did": manifest.grant_issuer_did,
        "required_organization_count": len(manifest.organizations),
        "required_agent_count": len(manifest.agents),
        "organizations_created": len(organizations_to_create),
        "grant_issuer_created": int(issuer_to_create),
        "identities_created": len(identities_to_create),
        **catalog_result,
        "readiness": readiness,
    }


def provision_production_agents(
    db: Session,
    manifest: ProductionAgentManifest,
) -> dict[str, Any]:
    """Atomically provision the manifest without generating key material."""

    with db.begin_nested():
        return _provision_production_agents(db, manifest)
