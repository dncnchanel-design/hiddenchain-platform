from __future__ import annotations

from typing import Any

from ..config import settings
from ..security import sha256_json


class OpenDataContractAdapter:
    """Project the sanitized catalog into an ODCS 3.1.0 local profile."""

    code = "ODCS_DATA_CONTRACT_3_1_0"
    standard = "Open Data Contract Standard"
    version = "3.1.0"
    profile = "ODCS_V3_1_0_LOCAL_PROJECTION"

    _LOGICAL_TYPES = {
        "boolean": "boolean",
        "integer": "integer",
        "number": "number",
        "string": "string",
        "array": "array",
    }

    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "code": cls.code,
            "standard": cls.standard,
            "version": cls.version,
            "profile": cls.profile,
            "validation": "LOCAL_REQUIRED_FIELDS_AND_PRIVACY_BOUNDARY",
            "raw_data_exposed": False,
        }

    @classmethod
    def _contract(cls, entry: dict[str, Any]) -> dict[str, Any]:
        product_id = str(entry["data_product_id"])
        fields = []
        for field in cls._fields_for(entry.get("asset_type")):
            field_type = str(field.get("type", "string"))
            fields.append(
                {
                    "name": str(field["name"]),
                    "logicalType": cls._LOGICAL_TYPES.get(field_type, "string"),
                    "physicalType": field_type,
                    "required": False,
                    "classification": str(entry.get("sensitivity_level") or "UNKNOWN"),
                }
            )
        allowed_purposes = (entry.get("usage") or {}).get("allowed_purposes") or [
            "POWER_SETTLEMENT"
        ]
        descriptor = {
            "apiVersion": "v3.1.0",
            "kind": "DataContract",
            "version": str(entry.get("schema_version") or "1.0.0"),
            "id": f"urn:hiddenchain:odcs:{sha256_json({'product_id': product_id})[:32]}",
            "name": product_id,
            "status": "active",
            "domain": "energy",
            "description": {
                "usage": "受控能源数据空间调用",
                "purpose": str(allowed_purposes[0]),
                "limitations": "只允许聚合输出；原始记录留在提供方连接器内。",
            },
            "servers": [
                {
                    "server": str(entry.get("endpoint") or f"connector://hiddenchain/products/{product_id}"),
                    "type": "custom",
                    "environment": settings.app_env,
                }
            ],
            "schema": [
                {
                    "name": product_id.lower(),
                    "logicalType": "object",
                    "physicalType": "connector",
                    "properties": fields,
                }
            ],
            "customProperties": [
                {"property": "hiddenchainRawDataExposed", "value": False},
                {"property": "hiddenchainUsageControl", "value": "OPA_REGO_COMPAT"},
                {"property": "hiddenchainSemanticRef", "value": str(entry.get("semantic_ref") or "")},
            ],
        }
        errors = cls.validate(descriptor)
        return {
            "descriptor": descriptor,
            "schema_validation": {"valid": not errors, "errors": errors, "profile": cls.profile},
            "contract_hash": sha256_json(descriptor),
            "raw_data_exposed": False,
        }

    @staticmethod
    def _fields_for(asset_type: Any) -> list[dict[str, str]]:
        return {
            "GENERATION_DATA": [{"name": "energy_mwh", "type": "number"}],
            "RETAIL_DATA": [{"name": "energy_mwh", "type": "number"}],
            "RENEWABLE_FORECAST": [
                {"name": "forecast_energy_mwh", "type": "number"},
                {"name": "forecast_accuracy_pct", "type": "number"},
            ],
            "USER_LOAD_CURVE": [{"name": "load_curve", "type": "array"}],
            "VPP_RESOURCE": [
                {"name": "adjustable_capacity_mw", "type": "number"},
                {"name": "storage_energy_mwh", "type": "number"},
                {"name": "response_minutes", "type": "number"},
            ],
            "GRID_CONSTRAINT": [
                {"name": "n_minus_one_passed", "type": "boolean"},
                {"name": "max_residual_imbalance_mwh", "type": "number"},
            ],
        }.get(str(asset_type), [])

    @classmethod
    def validate(cls, descriptor: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for key in ("version", "apiVersion", "kind", "id", "status", "servers", "schema"):
            if key not in descriptor:
                errors.append(f"$.{key} is required")
        if descriptor.get("apiVersion") != "v3.1.0":
            errors.append("$.apiVersion must be v3.1.0")
        if descriptor.get("kind") != "DataContract":
            errors.append("$.kind must be DataContract")
        if descriptor.get("status") != "active":
            errors.append("$.status must be active")
        if not isinstance(descriptor.get("servers"), list) or not descriptor["servers"]:
            errors.append("$.servers must contain at least one server")
        if not isinstance(descriptor.get("schema"), list) or not descriptor["schema"]:
            errors.append("$.schema must contain at least one object")
        else:
            for index, schema in enumerate(descriptor["schema"]):
                if schema.get("logicalType") != "object":
                    errors.append(f"$.schema[{index}].logicalType must be object")
                if not isinstance(schema.get("properties"), list) or not schema["properties"]:
                    errors.append(f"$.schema[{index}].properties must be non-empty")
        if descriptor.get("customProperties", [{}])[0].get("value") is not False:
            errors.append("$.customProperties must explicitly mark raw data as false")
        return errors

    @classmethod
    def build(cls, entries: list[dict[str, Any]]) -> dict[str, Any]:
        contracts = [cls._contract(entry) for entry in entries]
        errors = [
            error
            for contract in contracts
            for error in contract["schema_validation"]["errors"]
        ]
        return {
            **cls.status(),
            "contract_count": len(contracts),
            "contracts": contracts,
            "contracts_hash": sha256_json(contracts),
            "schema_validation": {"valid": not errors, "errors": errors, "profile": cls.profile},
            "raw_data_exposed": False,
        }
