from __future__ import annotations

import hashlib
import inspect
import platform
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version as distribution_version
from typing import Any

from ..security import sha256_json, verify_signature
from .adapters import (
    LocalControlledComputeAdapter,
    PandapowerGridAdapter,
    RulePackageAdapter,
)
from .vault import LocalDomainVault


@dataclass(frozen=True)
class AlgorithmDescriptor:
    code: str
    version: str
    implementation_status: str
    adapter_code: str
    source_hash: str
    component_source_hashes: dict[str, str]
    build_manifest: dict[str, str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    parameter_schema: dict[str, Any]
    unit_contract: dict[str, str]
    deterministic: bool
    attestation_status: str
    boundary: str

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value["descriptor_hash"] = sha256_json(value)
        return value


def _source_hash(component: Any) -> str:
    """Hash the loaded implementation, failing closed if it is not inspectable."""

    source = inspect.getsource(component)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _installed_version(distribution: str) -> str:
    try:
        return distribution_version(distribution)
    except PackageNotFoundError:
        return "NOT_INSTALLED"


def _controlled_settlement_descriptor() -> AlgorithmDescriptor:
    # The official result calls all of these components.  A single composite
    # hash prevents a snapshot from silently surviving a change to the Vault
    # integrity boundary, rule builder, arithmetic adapter, or grid gate.
    component_source_hashes = {
        "LocalControlledComputeAdapter": _source_hash(LocalControlledComputeAdapter),
        "PandapowerGridAdapter": _source_hash(PandapowerGridAdapter),
        "RulePackageAdapter": _source_hash(RulePackageAdapter),
        "LocalDomainVault": _source_hash(LocalDomainVault),
        "verify_signature": _source_hash(verify_signature),
    }
    build_manifest = {
        "python_runtime": platform.python_version(),
        "numeric_engine": "decimal.Decimal/ROUND_HALF_UP",
        "pandapower_distribution": _installed_version("pandapower"),
        "pandapower_adapter": PandapowerGridAdapter.code,
        "pandapower_network": PandapowerGridAdapter.network_version,
        "vault_adapter": f"LocalDomainVault/{LocalDomainVault.scheme}",
    }
    return AlgorithmDescriptor(
        code="CONTROLLED_SETTLEMENT_V1",
        version="decimal-v1.0.0",
        implementation_status="LOCAL_REAL",
        adapter_code=LocalControlledComputeAdapter.code,
        source_hash=sha256_json(
            {
                "component_source_hashes": component_source_hashes,
                "build_manifest": build_manifest,
            }
        ),
        component_source_hashes=component_source_hashes,
        build_manifest=build_manifest,
        input_schema={
            "generator": "GENERATION_DATA/v1",
            "retailer": "RETAIL_DATA/v1",
            "optional": [
                "RENEWABLE_FORECAST/v1",
                "VPP_RESOURCE/v1",
                "GRID_CONSTRAINT/v1",
            ],
        },
        output_schema={
            "settlement_energy_mwh": "decimal(18,3)",
            "deviation_mwh": "decimal(18,3)",
            "payable_amount_yuan": "decimal(20,6)",
            "result_hash": "sha256",
        },
        parameter_schema={
            "contract_price": "number>0",
            "deviation_threshold_mwh": "number>=0",
            "deviation_penalty_rate": "number>=0",
            "service_fee_rate": "number>=0",
            "rounding": "integer[0,6]",
        },
        unit_contract={
            "energy": "MWh",
            "capacity": "MW",
            "currency": "CNY yuan",
            "price": "CNY yuan/MWh",
        },
        deterministic=True,
        attestation_status="NOT_PROVIDED",
        boundary=(
            "Runs in the application process; it does not prove MPC, TEE, "
            "or independent cross-domain non-export."
        ),
    )


class AlgorithmRegistry:
    _algorithms: dict[str, AlgorithmDescriptor] = {
        "CONTROLLED_SETTLEMENT_V1": _controlled_settlement_descriptor(),
    }

    @classmethod
    def get(cls, code: str) -> AlgorithmDescriptor:
        try:
            return cls._algorithms[code]
        except KeyError as exc:
            raise ValueError(f"algorithm is not registered: {code}") from exc

    @classmethod
    def list(cls) -> list[dict[str, Any]]:
        return [cls._algorithms[code].payload() for code in sorted(cls._algorithms)]

    @classmethod
    def execution_descriptor(cls, code: str) -> dict[str, Any]:
        """Return the only descriptor accepted by Rule Freeze.

        Callers never supply trust labels or hashes.  They select a registered
        code and the repository-owned registry binds its implementation,
        schemas, parameters and units into the immutable snapshot.
        """

        registered = cls.get(code).payload()
        return {
            "code": registered["code"],
            "version": registered["version"],
            "hash": registered["descriptor_hash"],
            "adapter_code": registered["adapter_code"],
            "source_hash": registered["source_hash"],
            "component_source_hashes": registered["component_source_hashes"],
            "build_manifest": registered["build_manifest"],
            "deterministic": registered["deterministic"],
            "capability_label": registered["implementation_status"],
            "input_schema": registered["input_schema"],
            "output_schema": registered["output_schema"],
            "parameters": registered["parameter_schema"],
            "units": registered["unit_contract"],
            "attestation_status": registered["attestation_status"],
            "boundary": registered["boundary"],
        }

    @classmethod
    def verify_descriptor(cls, code: str, expected_hash: str) -> bool:
        return cls.execution_descriptor(code)["hash"] == expected_hash
