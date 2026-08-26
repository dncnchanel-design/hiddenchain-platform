from __future__ import annotations

import os


VERSION = "0.2.0"
API_CONTRACT_VERSION = "2026-08-20"
BUILD_SHA = (
    os.getenv("RENDER_GIT_COMMIT")
    or os.getenv("GIT_COMMIT")
    or os.getenv("SOURCE_VERSION")
    or "UNAVAILABLE"
)


CAPABILITIES: tuple[dict[str, str], ...] = (
    {
        "code": "DETERMINISTIC_SETTLEMENT",
        "implementation_status": "LOCAL_REAL",
        "boundary": "single service process with commitment-referenced inputs",
    },
    {
        "code": "DIFFERENTIAL_PRIVACY",
        "implementation_status": "LOCAL_REAL",
        "boundary": "OpenDP local adapter",
    },
    {
        "code": "MPC_AGGREGATION",
        "implementation_status": "LOCAL_REAL",
        "boundary": "protocol semantics only; independent cross-domain nodes are not deployed",
    },
    {
        "code": "PAILLIER_HOMOMORPHIC_AGGREGATION",
        "implementation_status": "LOCAL_REAL_EXPERIMENTAL_SINGLE_HOST",
        "boundary": "actual additive homomorphism; key custody and orchestration remain local",
    },
    {
        "code": "ECLIPSE_EDC",
        "implementation_status": "ADAPTER",
        "boundary": "dataspace protocol projection; no EDC control/data plane runtime",
    },
    {
        "code": "TEE_ATTESTATION",
        "implementation_status": "BLOCKED",
        "boundary": "no attested TEE runtime or key-release service configured",
    },
    {
        "code": "BLOCKCHAIN_ANCHOR",
        "implementation_status": "DEMO",
        "boundary": "local deterministic hash receipt; no consensus network confirmation",
    },
)


def version_payload() -> dict[str, object]:
    capabilities = [dict(item) for item in CAPABILITIES]
    try:
        from .services.formal_evidence import selected_anchor_adapter_status

        anchor = selected_anchor_adapter_status()
        if anchor.get("capability_label") != "DEMO":
            for item in capabilities:
                if item["code"] == "BLOCKCHAIN_ANCHOR":
                    item["implementation_status"] = str(anchor["capability_label"])
                    item["boundary"] = (
                        "external FISCO BCOS receipt verification; no consensus/finality claim"
                    )
                    break
    except Exception:
        # Version reporting must never make the health endpoint unavailable.
        pass
    return {
        "service_version": VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "build_sha": BUILD_SHA,
        "capabilities": capabilities,
    }
