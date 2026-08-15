from __future__ import annotations

import hashlib
import importlib.util
from typing import Any


# Keep the context in the application so credential processing never needs to
# dereference a user-controlled URL. The vocabulary covers the demo
# credentials issued by the seed data and agent registry.
LOCAL_JSON_LD_CONTEXT: dict[str, Any] = {
    "@version": 1.1,
    "id": "@id",
    "type": "@type",
    "VerifiableCredential": "https://www.w3.org/2018/credentials#VerifiableCredential",
    "EnergyMarketParticipantCredential": (
        "https://hiddenchain.example/vocab/EnergyMarketParticipantCredential"
    ),
    "AgentCapabilityCredential": "https://hiddenchain.example/vocab/AgentCapabilityCredential",
    "issuer": {
        "@id": "https://www.w3.org/2018/credentials#issuer",
        "@type": "@id",
    },
    "credentialSubject": "https://www.w3.org/2018/credentials#credentialSubject",
    "orgType": "https://schema.org/organizationType",
    "capabilities": "https://hiddenchain.example/vocab/capabilities",
    "toolAllowlist": "https://hiddenchain.example/vocab/toolAllowlist",
}


class JsonLdCredentialAdapter:
    """Create a stable, non-reversible fingerprint for DID/VC evidence.

    PyLD performs W3C JSON-LD 1.1/RDF Dataset Canonicalization (URDNA2015).
    This adapter does not verify a cryptographic proof and does not replace the
    existing credential status check; it gives audit records a portable
    canonicalization result while refusing remote JSON-LD context loading.
    """

    code = "PYLD_JSONLD_CANONICALIZATION_3_1"
    version = "3.1.0"

    @classmethod
    def status(cls) -> dict[str, Any]:
        installed = importlib.util.find_spec("pyld") is not None
        return {
            "code": cls.code,
            "version": cls.version,
            "installed": installed,
            "normalization": "URDNA2015",
            "context_mode": "PINNED_LOCAL_ONLY",
            "remote_context_fetch": False,
            "raw_data_exposed": False,
        }

    @staticmethod
    def _remote_context_requested(context: Any) -> bool:
        if isinstance(context, str):
            return True
        if isinstance(context, list) and any(isinstance(item, str) for item in context):
            return True
        if isinstance(context, dict) and "@import" in context:
            return True
        return False

    @classmethod
    def fingerprint(cls, credential: dict[str, Any] | None) -> dict[str, Any]:
        base = dict(credential or {})
        supplied_context = base.pop("@context", None)
        if supplied_context is not None and cls._remote_context_requested(supplied_context):
            return {
                **cls.status(),
                "status": "EXTERNAL_CONTEXT_BLOCKED",
                "raw_data_exposed": False,
            }

        if importlib.util.find_spec("pyld") is None:
            return {
                **cls.status(),
                "status": "UNAVAILABLE",
                "raw_data_exposed": False,
            }

        try:
            from pyld import jsonld

            normalized = jsonld.normalize(
                {**base, "@context": LOCAL_JSON_LD_CONTEXT},
                {
                    "algorithm": "URDNA2015",
                    "format": "application/n-quads",
                },
            )
        except Exception:
            # Do not return parser details or the credential body in an API
            # response. A canonicalization failure is evidence failure, while
            # the caller's existing DID status remains the source of truth.
            return {
                **cls.status(),
                "status": "CANONICALIZATION_FAILED",
                "raw_data_exposed": False,
            }

        return {
            **cls.status(),
            "status": "CANONICALIZED",
            "credential_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "statement_count": len([line for line in normalized.splitlines() if line.strip()]),
            "raw_data_exposed": False,
        }
