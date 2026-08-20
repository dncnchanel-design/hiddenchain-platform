from __future__ import annotations

from dataclasses import replace

import pytest

from app.security import sha256_json
from app.services.algorithm_registry import AlgorithmRegistry


def test_controlled_settlement_descriptor_is_complete_and_stable():
    first = AlgorithmRegistry.get("CONTROLLED_SETTLEMENT_V1").payload()
    second = AlgorithmRegistry.get("CONTROLLED_SETTLEMENT_V1").payload()

    assert first == second
    assert first["implementation_status"] == "LOCAL_REAL"
    assert first["deterministic"] is True
    assert first["attestation_status"] == "NOT_PROVIDED"
    assert first["unit_contract"]["energy"] == "MWh"
    assert first["adapter_code"] == "LOCAL_CONTROLLED_SETTLEMENT_V1"
    assert {
        "LocalControlledComputeAdapter",
        "PandapowerGridAdapter",
        "RulePackageAdapter",
        "LocalDomainVault",
        "verify_signature",
    } <= set(first["component_source_hashes"])
    assert all(
        len(component_hash) == 64
        for component_hash in first["component_source_hashes"].values()
    )
    assert first["source_hash"] == sha256_json(
        {
            "component_source_hashes": first["component_source_hashes"],
            "build_manifest": first["build_manifest"],
        }
    )
    execution = AlgorithmRegistry.execution_descriptor("CONTROLLED_SETTLEMENT_V1")
    assert execution["adapter_code"] == first["adapter_code"]
    assert execution["component_source_hashes"] == first["component_source_hashes"]
    assert execution["build_manifest"] == first["build_manifest"]
    assert AlgorithmRegistry.verify_descriptor(
        "CONTROLLED_SETTLEMENT_V1", first["descriptor_hash"]
    )


def test_unknown_algorithm_is_rejected():
    with pytest.raises(ValueError, match="not registered"):
        AlgorithmRegistry.get("UNREGISTERED")


def test_descriptor_hash_detects_loaded_execution_component_drift(monkeypatch):
    code = "CONTROLLED_SETTLEMENT_V1"
    frozen = AlgorithmRegistry.execution_descriptor(code)
    original = AlgorithmRegistry.get(code)
    changed_components = dict(original.component_source_hashes)
    changed_components["PandapowerGridAdapter"] = "0" * 64
    monkeypatch.setitem(
        AlgorithmRegistry._algorithms,
        code,
        replace(original, component_source_hashes=changed_components),
    )

    current = AlgorithmRegistry.execution_descriptor(code)

    assert current["hash"] != frozen["hash"]
    assert not AlgorithmRegistry.verify_descriptor(code, frozen["hash"])
